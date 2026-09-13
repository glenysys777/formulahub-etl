"""MySQL Destination — insert rows; demo writes SQLite + CSV under data/out/mysql_demo/."""

from __future__ import annotations

import csv
import os
import sqlite3
from pathlib import Path
from typing import Any

from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.registry import register


def _sql_type(v: Any) -> str:
    if isinstance(v, bool):
        return "INTEGER"
    if isinstance(v, int):
        return "INTEGER"
    if isinstance(v, float):
        return "REAL"
    return "TEXT"


def _clean_row(r: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in r.items() if not k.startswith("_")}


def _demo_active(ctx: RunContext, config: dict[str, Any]) -> bool:
    if ctx.demo_mode or os.environ.get("FORMULAETL_DEMO") == "1":
        return True
    host = str(config.get("host") or "").strip().lower()
    dsn = str(config.get("dsn") or "").strip().lower()
    return host in ("demo", "localhost-demo") or dsn.startswith("demo:")


def _has_real_dsn(config: dict[str, Any]) -> bool:
    if config.get("dsn") and not str(config["dsn"]).lower().startswith("demo:"):
        return True
    if config.get("host") and str(config.get("host")).lower() not in (
        "demo",
        "localhost-demo",
        "",
    ):
        return True
    return False


def _build_dsn(config: dict[str, Any]) -> str:
    if config.get("dsn"):
        return str(config["dsn"])
    host = config.get("host") or "localhost"
    port = int(config.get("port") or 3306)
    db = config.get("database") or config.get("db") or "mysql"
    user = config.get("user") or config.get("username") or "root"
    password = config.get("password") or ""
    return f"host={host} port={port} dbname={db} user={user} password={password}"


def _write_sqlite(path: Path, table: str, clean: list[dict[str, Any]], if_exists: str) -> None:
    if not table.replace("_", "").isalnum():
        raise ValueError(f"MySQLDestination: invalid table name {table!r}")
    path.parent.mkdir(parents=True, exist_ok=True)
    cols: list[str] = []
    if clean:
        cols = list(clean[0].keys())
        for r in clean[1:]:
            for k in r:
                if k not in cols:
                    cols.append(k)
    conn = sqlite3.connect(str(path))
    try:
        cur = conn.cursor()
        exists = cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        if exists and if_exists == "fail":
            raise ValueError(f"MySQLDestination: table {table!r} already exists")
        if exists and if_exists == "replace":
            cur.execute(f'DROP TABLE "{table}"')
            exists = None
        if not exists:
            if not cols:
                cols = ["_id"]
                type_map = {"_id": "INTEGER"}
            else:
                sample = clean[0] if clean else {}
                type_map = {c: _sql_type(sample.get(c)) for c in cols}
            col_defs = ", ".join(f'"{c}" {type_map[c]}' for c in cols)
            cur.execute(f'CREATE TABLE "{table}" ({col_defs})')
        if clean and cols:
            placeholders = ", ".join("?" for _ in cols)
            col_list = ", ".join(f'"{c}"' for c in cols)
            cur.executemany(
                f'INSERT INTO "{table}" ({col_list}) VALUES ({placeholders})',
                [tuple(r.get(c) for c in cols) for r in clean],
            )
        conn.commit()
    finally:
        conn.close()


def _write_csv(path: Path, clean: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not clean:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = list(clean[0].keys())
    for r in clean[1:]:
        for k in r:
            if k not in fieldnames:
                fieldnames.append(k)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(clean)


@register
class MySQLDestination(BaseComponent):
    component_type = "mysql_destination"
    display_name = "MySQL Destination"
    category = "destination"
    config_schema = {
        "type": "object",
        "required": ["table"],
        "properties": {
            "dsn": {"type": "string"},
            "host": {"type": "string"},
            "port": {"type": "integer", "default": 3306},
            "database": {"type": "string"},
            "user": {"type": "string"},
            "password": {"type": "string"},
            "table": {"type": "string"},
            "if_exists": {
                "type": "string",
                "enum": ["replace", "append", "fail"],
                "default": "append",
            },
            "demo_output_dir": {"type": "string", "default": "data/out/mysql_demo"},
        },
    }
    parameters = [
        {
            "key": "dsn",
            "label": "DSN",
            "type": "string",
            "required": False,
            "help": "MySQL connection (demo mode ignores and writes local SQLite/CSV)",
        },
        {
            "key": "host",
            "label": "Host",
            "type": "string",
            "required": False,
            "default": "demo",
            "help": "MySQL host (demo → local mirror)",
        },
        {
            "key": "port",
            "label": "Port",
            "type": "number",
            "required": False,
            "default": 3306,
            "help": "MySQL port",
        },
        {
            "key": "database",
            "label": "Database",
            "type": "string",
            "required": False,
            "help": "Database name",
        },
        {
            "key": "user",
            "label": "User",
            "type": "string",
            "required": False,
            "help": "Database user",
        },
        {
            "key": "password",
            "label": "Password",
            "type": "secret",
            "required": False,
            "help": "Database password",
        },
        {
            "key": "table",
            "label": "Table",
            "type": "string",
            "required": True,
            "default": "orders",
            "help": "Destination table name",
        },
        {
            "key": "if_exists",
            "label": "If table exists",
            "type": "select",
            "required": False,
            "default": "append",
            "options": ["replace", "append", "fail"],
            "help": "replace / append / fail (demo SQLite + real insert behavior)",
        },
        {
            "key": "demo_output_dir",
            "label": "Demo output dir",
            "type": "string",
            "required": False,
            "default": "data/out/mysql_demo",
            "help": "Where demo mode writes SQLite + CSV mirrors",
        },
    ]

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            rows = rows or []
            clean = [_clean_row(r) for r in rows]
            table = str(self.config["table"])
            if_exists = (self.config.get("if_exists") or "append").lower()

            use_demo = True
            if os.environ.get("FORMULAETL_DEMO") == "0" and _has_real_dsn(self.config):
                use_demo = False
            elif not (ctx.demo_mode or os.environ.get("FORMULAETL_DEMO") == "1"):
                use_demo = _demo_active(ctx, self.config)

            if use_demo:
                out_dir = ctx.resolve(
                    str(self.config.get("demo_output_dir") or "data/out/mysql_demo")
                )
                out_dir.mkdir(parents=True, exist_ok=True)
                db_path = out_dir / "demo.db"
                csv_path = out_dir / f"{table}.csv"
                _write_sqlite(db_path, table, clean, if_exists)
                _write_csv(csv_path, clean)
                # Also refresh workspace data/demo.db for postgres_source demos
                main_db = ctx.resolve("data/demo.db")
                _write_sqlite(main_db, table, clean, if_exists)

                metrics.rows_in = len(rows)
                metrics.rows_out = len(rows)
                note = (
                    "Demo mock: wrote SQLite + CSV under data/out/mysql_demo/ "
                    "(not a live MySQL INSERT). Real load needs DSN + FORMULAETL_DEMO=0."
                )
                ctx.emit(
                    f"MySQLDestination [demo]: {len(clean)} rows → {db_path} [{table}] + {csv_path.name}"
                )
                return ComponentResult(
                    rows=rows,
                    metrics=metrics,
                    artifacts={"path": str(db_path), "csv_path": str(csv_path), "table": table},
                    side_effects={
                        "mode": "demo",
                        "written_path": str(db_path),
                        "csv_path": str(csv_path),
                        "table": table,
                        "rows_loaded": len(clean),
                        "note": note,
                    },
                )

            try:
                import pymysql
            except ImportError as exc:
                raise ImportError(
                    "MySQLDestination: install PyMySQL for live MySQL "
                    "(pip install PyMySQL). Demo mode needs FORMULAETL_DEMO=1."
                ) from exc

            if not clean:
                metrics.rows_in = 0
                metrics.rows_out = 0
                return ComponentResult(
                    rows=rows,
                    metrics=metrics,
                    side_effects={"mode": "mysql", "rows_loaded": 0, "table": table},
                )

            cols = list(clean[0].keys())
            for r in clean[1:]:
                for k in r:
                    if k not in cols:
                        cols.append(k)
            if not table.replace("_", "").isalnum():
                raise ValueError(f"MySQLDestination: invalid table name {table!r}")

            col_list = ", ".join(f"`{c}`" for c in cols)
            placeholders = ", ".join(["%s"] * len(cols))
            insert_sql = f"INSERT INTO `{table}` ({col_list}) VALUES ({placeholders})"

            host = self.config.get("host") or "localhost"
            port = int(self.config.get("port") or 3306)
            db = self.config.get("database") or self.config.get("db") or "mysql"
            user = self.config.get("user") or self.config.get("username") or "root"
            password = self.config.get("password") or ""
            conn = pymysql.connect(
                host=host, port=port, user=user, password=password, database=db
            )
            try:
                with conn.cursor() as cur:
                    if if_exists == "replace":
                        cur.execute(f"TRUNCATE TABLE `{table}`")
                    cur.executemany(
                        insert_sql,
                        [tuple(r.get(c) for c in cols) for r in clean],
                    )
                conn.commit()
            finally:
                conn.close()

            metrics.rows_in = len(rows)
            metrics.rows_out = len(rows)
            ctx.emit(f"MySQLDestination: inserted {len(clean)} rows → {table}")
            return ComponentResult(
                rows=rows,
                metrics=metrics,
                artifacts={"table": table},
                side_effects={
                    "mode": "mysql",
                    "table": table,
                    "rows_loaded": len(clean),
                    "if_exists": if_exists,
                },
            )
