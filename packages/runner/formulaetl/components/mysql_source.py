"""MySQL Source — param shape for sales; demo falls back to SQLite / fixture rows."""

from __future__ import annotations

import csv
import os
import sqlite3
from pathlib import Path
from typing import Any

from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.registry import register

_FIXTURE_ROWS = [
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
    },
    {
        "order_id": 1002,
        "customer_id": 202,
        "customer_name": "Customer 2",
        "email": "customer2@example.com",
        "product_sku": "SKU-0002",
        "quantity": 2,
        "unit_price": 11.99,
        "order_date": "2024-01-17",
        "status": "shipped",
    },
    {
        "order_id": 1003,
        "customer_id": 203,
        "customer_name": "Customer 3",
        "email": "customer3@example.com",
        "product_sku": "SKU-0003",
        "quantity": 3,
        "unit_price": 12.99,
        "order_date": "2024-01-18",
        "status": "pending",
    },
]


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


def _sqlite_query(path: Path, query: str) -> list[dict[str, Any]]:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(query)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _load_csv_fixture(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@register
class MySQLSource(BaseComponent):
    component_type = "mysql_source"
    display_name = "MySQL Source"
    category = "source"
    config_schema = {
        "type": "object",
        "required": ["query"],
        "properties": {
            "dsn": {"type": "string"},
            "host": {"type": "string"},
            "port": {"type": "integer", "default": 3306},
            "database": {"type": "string"},
            "db": {"type": "string"},
            "user": {"type": "string"},
            "username": {"type": "string"},
            "password": {"type": "string"},
            "query": {"type": "string"},
            "demo_sqlite_path": {"type": "string", "default": "data/demo.db"},
        },
    }
    parameters = [
        {
            "key": "dsn",
            "label": "DSN",
            "type": "string",
            "required": False,
            "help": "MySQL DSN / connection string (or host=demo for SQLite demo fallback)",
        },
        {
            "key": "host",
            "label": "Host",
            "type": "string",
            "required": False,
            "default": "demo",
            "help": "MySQL host (demo → local SQLite fallback)",
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
            "key": "query",
            "label": "SQL query",
            "type": "string",
            "required": True,
            "default": "SELECT * FROM orders",
            "help": "SELECT statement to pull rows",
        },
        {
            "key": "demo_sqlite_path",
            "label": "Demo SQLite path",
            "type": "string",
            "required": False,
            "default": "data/demo.db",
            "help": "Used only in demo mode when no real DSN is set",
        },
    ]

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            query = str(self.config["query"])
            use_demo = _demo_active(ctx, self.config) and not (
                _has_real_dsn(self.config) and os.environ.get("FORMULAETL_DEMO") == "0"
            )
            # Prefer demo whenever FORMULAETL_DEMO=1 unless explicitly forced real
            if ctx.demo_mode or os.environ.get("FORMULAETL_DEMO") == "1":
                use_demo = True
            if os.environ.get("FORMULAETL_DEMO") == "0" and _has_real_dsn(self.config):
                use_demo = False

            if use_demo:
                sqlite_rel = self.config.get("demo_sqlite_path") or "data/demo.db"
                sqlite_path = ctx.resolve(str(sqlite_rel))
                mode = "demo_sqlite"
                note = (
                    "Demo fallback: reading SQLite (not live MySQL). "
                    "Real MySQL needs host/credentials and FORMULAETL_DEMO=0."
                )
                try:
                    if sqlite_path.exists():
                        out_rows = _sqlite_query(sqlite_path, query)
                    else:
                        # Try seeding path under work_dir data/demo.db after common seed
                        csv_path = ctx.work_dir / "fixtures" / "sample" / "orders_17cols.csv"
                        if csv_path.exists() and "orders" in query.lower():
                            out_rows = _load_csv_fixture(csv_path)
                            mode = "demo_csv_fixture"
                            note = (
                                "Demo fallback: no data/demo.db — returned CSV fixture rows. "
                                "Seed with scripts/seed_demo.py or sqlite_destination first."
                            )
                        else:
                            out_rows = list(_FIXTURE_ROWS)
                            mode = "demo_inline_fixture"
                            note = (
                                "Demo fallback: inline fixture rows (no DSN / no demo.db). "
                                "Not a live MySQL connection."
                            )
                except sqlite3.Error:
                    out_rows = list(_FIXTURE_ROWS)
                    mode = "demo_inline_fixture"
                    note = (
                        "Demo fallback: SQLite query failed — returned inline fixture rows. "
                        "Not a live MySQL connection."
                    )

                metrics.rows_out = len(out_rows)
                ctx.emit(f"MySQLSource [{mode}]: → {len(out_rows)} rows ({note[:60]}…)")
                return ComponentResult(
                    rows=out_rows,
                    metrics=metrics,
                    artifacts={"query": query, "mode": mode},
                    side_effects={
                        "mode": mode,
                        "rows": len(out_rows),
                        "sqlite_path": str(sqlite_path) if mode == "demo_sqlite" else None,
                        "note": note,
                    },
                )

            # Real MySQL via PyMySQL (optional)
            try:
                import pymysql
                from pymysql.cursors import DictCursor
            except ImportError as exc:
                raise ImportError(
                    "MySQLSource: install PyMySQL for live MySQL "
                    "(pip install PyMySQL). Demo mode needs FORMULAETL_DEMO=1."
                ) from exc

            host = self.config.get("host") or "localhost"
            port = int(self.config.get("port") or 3306)
            db = self.config.get("database") or self.config.get("db") or "mysql"
            user = self.config.get("user") or self.config.get("username") or "root"
            password = self.config.get("password") or ""
            conn = pymysql.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                database=db,
                cursorclass=DictCursor,
            )
            try:
                with conn.cursor() as cur:
                    cur.execute(query)
                    out_rows = [dict(r) for r in cur.fetchall()]
            finally:
                conn.close()

            metrics.rows_out = len(out_rows)
            ctx.emit(f"MySQLSource: query → {len(out_rows)} rows")
            return ComponentResult(
                rows=out_rows,
                metrics=metrics,
                artifacts={"query": query},
                side_effects={"mode": "mysql", "rows": len(out_rows)},
            )
