"""Schema discovery from source configs (infer columns from samples/connections).

Infers columns + types from file samples, API fixtures, or DB metadata.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SchemaColumn:
    name: str
    type: str = "string"
    nullable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "type": self.type, "nullable": self.nullable}


@dataclass
class SchemaResult:
    columns: list[SchemaColumn] = field(default_factory=list)
    sample_rows: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "columns": [c.to_dict() for c in self.columns],
        }
        if self.sample_rows:
            out["sample_rows"] = self.sample_rows
        return out


_SOURCE_ALIASES = {
    "csv": "local_file_source",
    "file_source": "local_file_source",
    "local_file": "local_file_source",
    "excel": "excel_source",
    "http": "http_api_source",
    "api": "http_api_source",
    "kafka": "kafka_source",
    "s3": "s3_source",
    "sqlite": "sqlite_source",
    "postgres": "postgres_source",
    "mysql": "mysql_source",
}


def _repo_root() -> Path:
    # packages/runner/formulaetl/schema/discover.py → repo root
    return Path(__file__).resolve().parents[4]


def _resolve_work_dir(work_dir: Path | str | None) -> Path:
    if work_dir is not None:
        return Path(work_dir)
    env = os.environ.get("FORMULAETL_WORK_DIR")
    if env:
        return Path(env)
    return _repo_root()


def _resolve_path(work_dir: Path, path: str | Path) -> Path:
    p = Path(path)
    if p.is_absolute():
        return p
    return work_dir / p

def _rel_str(work_dir: Path, path: Path) -> str:
    try:
        return str(path.relative_to(work_dir))
    except ValueError:
        return str(path)




def _infer_type(values: list[Any]) -> str:
    non_null = [v for v in values if v is not None and v != ""]
    if not non_null:
        return "string"
    boolish = 0
    intish = 0
    floatish = 0
    dateish = 0
    for v in non_null:
        if isinstance(v, bool):
            boolish += 1
            continue
        if isinstance(v, int) and not isinstance(v, bool):
            intish += 1
            continue
        if isinstance(v, float):
            floatish += 1
            continue
        s = str(v).strip()
        low = s.lower()
        if low in ("true", "false", "yes", "no", "1", "0") and isinstance(v, str):
            # Prefer string unless all look boolean words
            if low in ("true", "false", "yes", "no"):
                boolish += 1
            continue
        if re.fullmatch(r"-?\d+", s):
            intish += 1
            continue
        if re.fullmatch(r"-?\d+\.\d+", s):
            floatish += 1
            continue
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) or re.fullmatch(
            r"\d{1,2}/\d{1,2}/\d{4}", s
        ):
            dateish += 1
            continue
    n = len(non_null)
    if boolish == n:
        return "boolean"
    if intish == n:
        return "int"
    if floatish + intish == n and floatish > 0:
        return "float"
    if dateish == n:
        return "date"
    return "string"


def _columns_from_rows(rows: list[dict[str, Any]], sample_limit: int = 5) -> SchemaResult:
    if not rows:
        return SchemaResult(columns=[], sample_rows=[])
    # Preserve column order from first row, then union
    names: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for k in row.keys():
            if k not in seen:
                seen.add(k)
                names.append(str(k))
    columns: list[SchemaColumn] = []
    for name in names:
        vals = [r.get(name) for r in rows[:50]]
        nullable = any(v is None or v == "" for v in vals)
        columns.append(
            SchemaColumn(name=name, type=_infer_type(vals), nullable=nullable)
        )
    sample = []
    for r in rows[:sample_limit]:
        sample.append({k: r.get(k) for k in names})
    return SchemaResult(columns=columns, sample_rows=sample)


def _normalize_excel_value(v: Any) -> Any:
    if v is None:
        return None
    try:
        import math

        if isinstance(v, float) and math.isnan(v):
            return None
    except Exception:
        pass
    try:
        import numpy as np

        if isinstance(v, (np.integer,)):
            return int(v)
        if isinstance(v, (np.floating,)):
            if np.isnan(v):
                return None
            return float(v)
        if isinstance(v, (np.bool_,)):
            return bool(v)
    except Exception:
        pass
    try:
        import pandas as pd

        if isinstance(v, pd.Timestamp):
            if v.hour == 0 and v.minute == 0 and v.second == 0:
                return v.strftime("%Y-%m-%d")
            return v.isoformat()
    except Exception:
        pass
    return v


def _discover_excel(config: dict[str, Any], work_dir: Path) -> SchemaResult:
    import pandas as pd

    path = _resolve_path(work_dir, config.get("path") or "")
    if not path.exists():
        raise FileNotFoundError(f"Excel file not found: {path}")

    sheet = config.get("sheet_name", 0)
    if sheet is None or sheet == "":
        sheet = 0
    elif isinstance(sheet, str) and sheet.isdigit():
        sheet = int(sheet)

    has_header = config.get("has_header", True)
    if isinstance(has_header, str):
        has_header = has_header.strip().lower() in ("1", "true", "yes", "y")

    header = 0 if has_header else None
    suffix = path.suffix.lower()
    engine = "openpyxl" if suffix != ".xls" else None
    kwargs: dict[str, Any] = {
        "sheet_name": sheet,
        "header": header,
        "dtype": object,
        "nrows": 50,
    }
    if engine:
        kwargs["engine"] = engine
    df = pd.read_excel(path, **kwargs)

    cols: list[str] = []
    seen: dict[str, int] = {}
    for i, c in enumerate(df.columns):
        name = str(c) if c is not None and str(c) != "nan" else f"col_{i}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 0
        cols.append(name)
    df.columns = cols

    rows: list[dict[str, Any]] = []
    for rec in df.to_dict(orient="records"):
        rows.append({k: _normalize_excel_value(v) for k, v in rec.items()})
    return _columns_from_rows(rows)


def _discover_csv_file(path: Path, encoding: str = "utf-8") -> SchemaResult:
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {path}")
    text = path.read_text(encoding=encoding)
    reader = csv.DictReader(io.StringIO(text))
    rows = [dict(r) for i, r in enumerate(reader) if i < 50]
    return _columns_from_rows(rows)


def _discover_json_file(path: Path, encoding: str = "utf-8") -> SchemaResult:
    if not path.exists():
        raise FileNotFoundError(f"JSON file not found: {path}")
    data = json.loads(path.read_text(encoding=encoding))
    if isinstance(data, list):
        rows = [r for r in data if isinstance(r, dict)][:50]
    elif isinstance(data, dict):
        for key in ("records", "data", "items", "results", "rows"):
            val = data.get(key)
            if isinstance(val, list):
                rows = [r for r in val if isinstance(r, dict)][:50]
                break
            if isinstance(val, dict):
                for sub in ("records", "data", "items", "results", "rows"):
                    if isinstance(val.get(sub), list):
                        rows = [r for r in val[sub] if isinstance(r, dict)][:50]
                        break
                else:
                    continue
                break
        else:
            rows = [data]
    else:
        raise ValueError(f"Unsupported JSON root type: {type(data).__name__}")
    return _columns_from_rows(rows)


def _discover_local_file(config: dict[str, Any], work_dir: Path) -> SchemaResult:
    path = _resolve_path(work_dir, config.get("path") or "")
    encoding = str(config.get("encoding") or "utf-8")
    fmt = config.get("format") or "auto"
    if fmt == "auto":
        suffix = path.suffix.lower()
        if suffix == ".csv":
            fmt = "csv"
        elif suffix == ".json":
            fmt = "json"
        elif suffix in (".xlsx", ".xls", ".xlsm"):
            return _discover_excel({**config, "path": _rel_str(work_dir, path)}, work_dir)
        else:
            raise ValueError(f"Cannot infer schema for format of {path.name}")
    if fmt == "csv":
        return _discover_csv_file(path, encoding=encoding)
    if fmt == "json":
        return _discover_json_file(path, encoding=encoding)
    raise ValueError(f"Unsupported local file format for schema discover: {fmt}")


_RECORD_KEYS = ("records", "data", "items", "results", "rows")


def _get_by_path(data: Any, path: str) -> Any:
    cur = data
    for part in path.split("."):
        if part == "":
            continue
        if isinstance(cur, dict):
            cur = cur[part]
        elif isinstance(cur, list):
            cur = cur[int(part)]
        else:
            raise KeyError(f"json_path cannot descend into {type(cur).__name__}")
    return cur


def _extract_api_rows(payload: Any, json_path: str | None) -> list[dict[str, Any]]:
    if json_path:
        payload = _get_by_path(payload, json_path)
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        found = None
        for key in _RECORD_KEYS:
            val = payload.get(key)
            if isinstance(val, list):
                found = val
                break
            if isinstance(val, dict):
                for sub in _RECORD_KEYS:
                    if isinstance(val.get(sub), list):
                        found = val[sub]
                        break
            if found is not None:
                break
        rows = found if found is not None else [payload]
    else:
        raise ValueError(f"API payload is not object/array ({type(payload).__name__})")
    out: list[dict[str, Any]] = []
    for i, row in enumerate(rows[:50]):
        if isinstance(row, dict):
            out.append(dict(row))
        else:
            out.append({"value": row, "_index": i})
    return out


def _load_api_fixture(work_dir: Path) -> Any:
    candidates = [
        work_dir / "fixtures" / "sample" / "api_orders.json",
        _repo_root() / "fixtures" / "sample" / "api_orders.json",
    ]
    for path in candidates:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    raise FileNotFoundError("API fixture fixtures/sample/api_orders.json not found")


def _use_api_demo(config: dict[str, Any], demo_mode: bool) -> bool:
    if config.get("demo") is True:
        return True
    if config.get("demo") is False:
        return False
    url = str(config.get("url") or "")
    demo_env = demo_mode or os.environ.get("FORMULAETL_DEMO") == "1"
    return bool(demo_env and ("example.com" in url.lower() or not url))


def _discover_http_api(config: dict[str, Any], work_dir: Path, demo_mode: bool) -> SchemaResult:
    url = str(config.get("url") or "")
    json_path = config.get("json_path") or None
    if json_path == "":
        json_path = None

    if _use_api_demo(config, demo_mode):
        payload = _load_api_fixture(work_dir)
        rows = _extract_api_rows(payload, json_path)
        return _columns_from_rows(rows)

    import httpx

    method = str(config.get("method") or "GET").upper()
    headers: dict[str, str] = {}
    raw_headers = config.get("headers")
    if isinstance(raw_headers, dict):
        headers = {str(k): str(v) for k, v in raw_headers.items()}
    token = config.get("auth_bearer")
    if token:
        headers.setdefault("Authorization", f"Bearer {token}")
    timeout = float(config.get("timeout_sec") or 30)
    with httpx.Client() as client:
        resp = client.request(method, url, headers=headers or None, timeout=timeout)
        resp.raise_for_status()
        payload = resp.json()
    rows = _extract_api_rows(payload, json_path)
    return _columns_from_rows(rows)


def _sqlite_type_to_etl(decl: str | None) -> str:
    if not decl:
        return "string"
    d = decl.upper()
    if "INT" in d:
        return "int"
    if any(x in d for x in ("REAL", "FLOA", "DOUB", "NUM", "DEC")):
        return "float"
    if "BOOL" in d:
        return "boolean"
    if "DATE" in d or "TIME" in d:
        return "date"
    return "string"


def _discover_sqlite(config: dict[str, Any], work_dir: Path) -> SchemaResult:
    path = _resolve_path(work_dir, config.get("path") or "data/demo.db")
    if not path.exists():
        raise FileNotFoundError(f"SQLite database not found: {path}")
    query = str(config.get("query") or "").strip()
    table = config.get("table")
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        if table and not query:
            # Prefer PRAGMA for metadata
            cur = conn.execute(f"PRAGMA table_info({table})")
            pragma_rows = cur.fetchall()
            if pragma_rows:
                columns = [
                    SchemaColumn(
                        name=str(r["name"]),
                        type=_sqlite_type_to_etl(r["type"]),
                        nullable=not bool(r["notnull"]),
                    )
                    for r in pragma_rows
                ]
                sample_cur = conn.execute(f"SELECT * FROM {table} LIMIT 5")
                sample = [dict(r) for r in sample_cur.fetchall()]
                return SchemaResult(columns=columns, sample_rows=sample)
            query = f"SELECT * FROM {table} LIMIT 50"
        if not query:
            # Try common demo table
            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                ).fetchall()
            ]
            if "orders" in tables:
                query = "SELECT * FROM orders LIMIT 50"
            elif tables:
                query = f"SELECT * FROM {tables[0]} LIMIT 50"
            else:
                raise ValueError("SQLite database has no tables")
        # Limit discovery query if unbounded SELECT *
        q = query
        if "limit" not in q.lower():
            q = f"SELECT * FROM ({query}) AS _schema_q LIMIT 50"
        cur = conn.execute(q)
        rows = [dict(r) for r in cur.fetchall()]
        return _columns_from_rows(rows)
    finally:
        conn.close()


def _discover_postgres_or_mysql(
    component_type: str, config: dict[str, Any], work_dir: Path, demo_mode: bool
) -> SchemaResult:
    # Demo mode: use SQLite mirror or fixture CSV
    use_demo = demo_mode or os.environ.get("FORMULAETL_DEMO") == "1"
    host = str(config.get("host") or "").strip().lower()
    if use_demo or host in ("demo", "localhost-demo"):
        sqlite_path = config.get("demo_sqlite_path") or "data/demo.db"
        path = _resolve_path(work_dir, sqlite_path)
        if path.exists():
            return _discover_sqlite(
                {"path": _rel_str(work_dir, path), "query": config.get("query") or "SELECT * FROM orders LIMIT 50"},
                work_dir,
            )
        fixture = work_dir / "fixtures" / "sample" / "orders_17cols.csv"
        if fixture.exists():
            return _discover_csv_file(fixture)
        # Fall back to minimal demo order shape
        return _columns_from_rows(
            [
                {
                    "order_id": 1001,
                    "customer_id": 201,
                    "customer_name": "Customer 1",
                    "email": "customer1@example.com",
                    "product_sku": "SKU-0001",
                    "quantity": 1,
                    "unit_price": 10.99,
                    "order_date": "2024-01-16",
                    "status": "shipped",
                }
            ]
        )

    # Live: SELECT * LIMIT 1 (and infer from row) — optional information_schema later
    query = str(config.get("query") or "SELECT 1").strip()
    if "limit" not in query.lower():
        limited = f"SELECT * FROM ({query}) AS _schema_q LIMIT 5"
    else:
        limited = query

    if component_type == "postgres_source":
        import psycopg

        dsn = config.get("dsn")
        if not dsn:
            host = config.get("host") or "localhost"
            port = int(config.get("port") or 5432)
            db = config.get("database") or config.get("db") or "postgres"
            user = config.get("user") or config.get("username") or "postgres"
            password = config.get("password") or ""
            dsn = f"host={host} port={port} dbname={db} user={user} password={password}"
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(limited)
                cols = [d.name for d in cur.description] if cur.description else []
                fetched = cur.fetchall()
                rows = [dict(zip(cols, row)) for row in fetched]
        return _columns_from_rows(rows)

    # mysql
    import pymysql

    conn = pymysql.connect(
        host=config.get("host") or "localhost",
        port=int(config.get("port") or 3306),
        user=config.get("user") or config.get("username") or "root",
        password=config.get("password") or "",
        database=config.get("database") or config.get("db") or None,
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(limited)
            rows = list(cur.fetchall())[:50]
    finally:
        conn.close()
    return _columns_from_rows(rows)


def _discover_s3(config: dict[str, Any], work_dir: Path, demo_mode: bool) -> SchemaResult:
    """Demo: resolve local mock object; prefer CSV/JSON fixtures for schema."""
    # Prefer explicit schema fixture path if provided
    if config.get("schema_path"):
        return _discover_local_file({"path": config["schema_path"], "format": "auto"}, work_dir)

    key = str(config.get("key") or "")
    bucket = str(config.get("bucket") or "demo")
    candidates = [
        work_dir / "data" / "s3" / bucket / key,
        work_dir / "data" / "s3" / key,
        work_dir / "fixtures" / "sample" / "orders_17cols.csv",
        work_dir / "fixtures" / "sample" / "customers.csv",
    ]
    # If key looks like encrypted pgp, use the 17-col CSV fixture for schema demo
    if key.endswith(".pgp") or key.endswith(".gpg"):
        fixture = work_dir / "fixtures" / "sample" / "orders_17cols.csv"
        if fixture.exists():
            return _discover_csv_file(fixture)

    for path in candidates:
        if path.exists() and path.is_file():
            suffix = path.suffix.lower()
            if suffix == ".csv":
                return _discover_csv_file(path)
            if suffix == ".json":
                return _discover_json_file(path)
            if suffix in (".xlsx", ".xls"):
                return _discover_excel({"path": str(path), "has_header": True}, work_dir)
    # Last resort: orders fixture
    fixture = work_dir / "fixtures" / "sample" / "orders_17cols.csv"
    if fixture.exists():
        return _discover_csv_file(fixture)
    raise FileNotFoundError(
        f"S3 schema demo: no local fixture for s3://{bucket}/{key}"
    )


def _discover_kafka(
    config: dict[str, Any], work_dir: Path, demo_mode: bool
) -> SchemaResult:
    """Demo: infer columns from kafka_orders fixture (JSONL)."""
    custom = config.get("fixture_path")
    candidates = []
    if custom:
        candidates.append(_resolve_path(work_dir, str(custom)))
    candidates.extend(
        [
            work_dir / "fixtures" / "sample" / "kafka_orders.jsonl",
            work_dir / "fixtures" / "sample" / "kafka_orders.json",
        ]
    )
    path = next((p for p in candidates if p.exists()), None)
    if path is None:
        raise FileNotFoundError("Kafka schema demo: fixtures/sample/kafka_orders.jsonl missing")
    rows: list[dict[str, Any]] = []
    if path.suffix.lower() == ".jsonl":
        for ln in path.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            rows.append(json.loads(ln))
            if len(rows) >= 20:
                break
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            rows = [r for r in data if isinstance(r, dict)][:20]
        elif isinstance(data, dict):
            rows = [data]
    return _columns_from_rows(rows)


def discover(
    component_type: str,
    config: dict[str, Any] | None = None,
    *,
    work_dir: Path | str | None = None,
    demo_mode: bool | None = None,
) -> dict[str, Any]:
    """Discover schema for a source-like component.

    Returns ``{ columns: [{name, type, nullable}], sample_rows?: [...] }``.
    """
    config = dict(config or {})
    ctype = (component_type or "").strip().lower()
    ctype = _SOURCE_ALIASES.get(ctype, ctype)
    wd = _resolve_work_dir(work_dir)
    if demo_mode is None:
        demo_mode = os.environ.get("FORMULAETL_DEMO", "1") == "1"

    if ctype in ("excel_source",):
        result = _discover_excel(config, wd)
    elif ctype in ("local_file_source", "csv_parser"):
        # csv_parser often has no path — if path missing try content or fail clearly
        if ctype == "csv_parser" and not config.get("path"):
            # Treat as needing upstream; allow delimiter-only configs with sample_text
            if config.get("sample_text"):
                reader = csv.DictReader(io.StringIO(str(config["sample_text"])))
                rows = [dict(r) for i, r in enumerate(reader) if i < 50]
                result = _columns_from_rows(rows)
            else:
                raise ValueError(
                    "csv_parser schema discover requires config.path or sample_text"
                )
        else:
            result = _discover_local_file(config, wd)
    elif ctype in ("http_api_source",):
        result = _discover_http_api(config, wd, demo_mode)
    elif ctype in ("kafka_source",):
        result = _discover_kafka(config, wd, demo_mode)
    elif ctype in ("sqlite_source",):
        result = _discover_sqlite(config, wd)
    elif ctype in ("postgres_source", "mysql_source"):
        result = _discover_postgres_or_mysql(ctype, config, wd, demo_mode)
    elif ctype in ("s3_source",):
        result = _discover_s3(config, wd, demo_mode)
    else:
        raise ValueError(
            f"Schema discovery not supported for component_type={component_type!r}"
        )

    return result.to_dict()


__all__ = ["SchemaColumn", "SchemaResult", "discover"]
