"""SQLite Source — query a local SQLite DB (demo stand-in for JDBC/DB)."""

from __future__ import annotations

import sqlite3
from typing import Any

from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.registry import register


@register
class SQLiteSource(BaseComponent):
    component_type = "sqlite_source"
    display_name = "SQLite Source"
    category = "source"
    config_schema = {
        "type": "object",
        "required": ["path", "query"],
        "properties": {
            "path": {"type": "string", "description": "SQLite database file path"},
            "query": {"type": "string", "description": "SQL SELECT query"},
        },
    }
    parameters = [
        {
            "key": "path",
            "label": "Database path",
            "type": "string",
            "required": True,
            "help": "Path to .db / .sqlite file (e.g. data/demo.db)",
            "default": "data/demo.db",
        },
        {
            "key": "query",
            "label": "SQL query",
            "type": "string",
            "required": True,
            "help": "SELECT statement to pull rows",
            "default": "SELECT * FROM orders",
        },
    ]

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            path = ctx.resolve(self.config["path"])
            query = self.config["query"]
            if not path.exists():
                raise FileNotFoundError(
                    f"SQLiteSource: database not found: {path} "
                    "(seed with scripts or sqlite_destination first)"
                )
            conn = sqlite3.connect(str(path))
            conn.row_factory = sqlite3.Row
            try:
                cur = conn.execute(query)
                out_rows = [dict(r) for r in cur.fetchall()]
            finally:
                conn.close()

            metrics.rows_in = 0
            metrics.rows_out = len(out_rows)
            ctx.emit(f"SQLiteSource: {path.name} → {len(out_rows)} rows")

        return ComponentResult(
            rows=out_rows,
            metrics=metrics,
            artifacts={"path": str(path), "query": query},
            side_effects={"path": str(path), "rows": len(out_rows)},
        )
