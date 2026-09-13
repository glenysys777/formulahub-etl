"""SQLite Destination — write rows into a local SQLite table (DB pattern demo)."""

from __future__ import annotations

import sqlite3
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


@register
class SQLiteDestination(BaseComponent):
    component_type = "sqlite_destination"
    display_name = "SQLite Destination"
    category = "destination"
    config_schema = {
        "type": "object",
        "required": ["path", "table"],
        "properties": {
            "path": {"type": "string", "default": "data/demo.db"},
            "table": {"type": "string"},
            "if_exists": {
                "type": "string",
                "enum": ["replace", "append", "fail"],
                "default": "replace",
            },
        },
    }
    parameters = [
        {
            "key": "path",
            "label": "Database path",
            "type": "string",
            "required": True,
            "default": "data/demo.db",
            "help": "SQLite file to create/update",
        },
        {
            "key": "table",
            "label": "Table name",
            "type": "string",
            "required": True,
            "help": "Destination table name",
            "default": "orders",
        },
        {
            "key": "if_exists",
            "label": "If table exists",
            "type": "select",
            "required": False,
            "default": "replace",
            "options": ["replace", "append", "fail"],
            "help": "replace drops+recreates; append inserts; fail errors",
        },
    ]

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            rows = rows or []
            path = ctx.resolve(self.config["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            table = str(self.config["table"])
            if not table.replace("_", "").isalnum():
                raise ValueError(f"SQLiteDestination: invalid table name {table!r}")
            if_exists = (self.config.get("if_exists") or "replace").lower()

            def _clean_row(r: dict[str, Any]) -> dict[str, Any]:
                return {k: v for k, v in r.items() if not k.startswith("_")}

            clean = [_clean_row(r) for r in rows]
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
                    raise ValueError(f"SQLiteDestination: table {table!r} already exists")
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

            metrics.rows_in = len(rows)
            metrics.rows_out = len(rows)
            ctx.emit(
                f"SQLiteDestination: wrote {len(clean)} rows → {path} [{table}]"
            )

        return ComponentResult(
            rows=rows,
            metrics=metrics,
            side_effects={
                "written_path": str(path),
                "table": table,
                "rows_loaded": len(clean),
                "if_exists": if_exists,
            },
            artifacts={"path": str(path), "table": table},
        )
