"""Snowflake Destination — real connector or demo mode CSV under ./data/out/snowflake.

Demo path streams RowBatches to disk (``consume_dataset``) so the full load
set is never held as ``list[dict]`` in process RAM.
"""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone
from typing import Any

from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.capabilities import STREAMING_SINK
from formulaetl.sdk.connections import connection_id_param
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.data import DatasetHandle
from formulaetl.sdk.registry import register


def _clean_row(r: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in r.items() if not k.startswith("_")}


@register
class SnowflakeDestination(BaseComponent):
    component_type = "snowflake_destination"
    display_name = "Snowflake Destination"
    category = "destination"
    capabilities = STREAMING_SINK
    config_schema = {
        "type": "object",
        "properties": {
            "account": {"type": "string"},
            "user": {"type": "string"},
            "password": {"type": "string"},
            "warehouse": {"type": "string"},
            "database": {"type": "string"},
            "schema": {"type": "string", "default": "PUBLIC"},
            "table": {"type": "string", "default": "FORMULAETL_LOAD"},
            "demo_output_dir": {
                "type": "string",
                "default": "data/out/snowflake",
                "description": "Used when FORMULAETL_DEMO=1",
            },
        },
    }
    parameters = [
        connection_id_param(),
        {"key": "database", "label": "Database", "type": "string", "required": False, "help": "Snowflake database"},
        {"key": "schema", "label": "Schema", "type": "string", "required": False, "default": "PUBLIC", "help": "Snowflake schema"},
        {"key": "table", "label": "Table", "type": "string", "required": False, "default": "FORMULAETL_LOAD", "help": "Target table name"},
        {"key": "account", "label": "Account", "type": "string", "required": False, "help": "Snowflake account (live mode)"},
        {"key": "user", "label": "User", "type": "string", "required": False, "help": "Snowflake user (live mode)"},
        {"key": "password", "label": "Password", "type": "secret", "required": False, "help": "Snowflake password (live mode)"},
        {"key": "warehouse", "label": "Warehouse", "type": "string", "required": False, "help": "Snowflake warehouse (live mode)"},
        {"key": "demo_output_dir", "label": "Demo output dir", "type": "string", "required": False, "default": "data/out/snowflake", "help": "CSV output path in demo mode"},
    ]

    def _demo_stream_write(
        self,
        ctx: RunContext,
        dataset: DatasetHandle,
        *,
        table: str,
        database: str,
        schema: str,
    ) -> tuple[ComponentResult, Metrics]:
        metrics = Metrics()
        out_dir = ctx.resolve(self.config.get("demo_output_dir", "data/out/snowflake"))
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = out_dir / f"{table.lower()}_{ts}.csv"

        fieldnames: list[str] | None = None
        n_in = 0
        n_out = 0
        n_batches = 0
        with out_path.open("w", newline="", encoding="utf-8") as f:
            writer: csv.DictWriter | None = None
            for batch in dataset.iter_batches(getattr(ctx, "batch_size", None)):
                n_batches += 1
                clean = [_clean_row(r) for r in batch.rows]
                n_in += len(batch.rows)
                if not clean:
                    continue
                if writer is None:
                    fieldnames = list(clean[0].keys())
                    for r in clean[1:]:
                        for k in r:
                            if k not in fieldnames:
                                fieldnames.append(k)
                    writer = csv.DictWriter(
                        f, fieldnames=fieldnames, extrasaction="ignore"
                    )
                    writer.writeheader()
                writer.writerows(clean)
                n_out += len(clean)

        log_path = out_path.with_suffix(".load.json")
        load_meta = {
            "mode": "demo",
            "target": f"{database}.{schema}.{table}",
            "rows_loaded": n_out,
            "file": str(out_path),
            "timestamp": ts,
            "note": (
                "Demo mode — wrote CSV with same schema as a Snowflake load. "
                "Set FORMULAETL_DEMO=0 and provide account/user/password for real loads."
            ),
        }
        log_path.write_text(json.dumps(load_meta, indent=2), encoding="utf-8")
        ctx.emit(
            f"SnowflakeDestination [demo]: loaded {n_out} rows → "
            f"{database}.{schema}.{table} (file={out_path})"
        )
        metrics.rows_in = n_in
        metrics.rows_out = n_out
        metrics.extras["feed"] = "batches"
        metrics.extras["batches"] = n_batches
        metrics.extras["spill"] = True
        return (
            ComponentResult(
                rows=[],
                metrics=metrics,
                side_effects={
                    "mode": "demo",
                    "target": f"{database}.{schema}.{table}",
                    "written_path": str(out_path),
                    "load_log": str(log_path),
                    "rows_loaded": n_out,
                },
                artifacts={"path": str(out_path)},
            ),
            metrics,
        )

    def consume_dataset(self, ctx: RunContext, dataset: DatasetHandle) -> ComponentResult:
        """Stream batches to demo CSV (or fall back to legacy materialize for live)."""
        table = self.config.get("table", "FORMULAETL_LOAD")
        database = self.config.get("database", "DEMO_DB")
        schema = self.config.get("schema", "PUBLIC")
        use_demo = ctx.demo_mode or os.environ.get("FORMULAETL_DEMO") == "1"
        if not use_demo and not self.config.get("account"):
            use_demo = True
            ctx.emit("SnowflakeDestination: no account configured — using demo mode")

        if not use_demo:
            return self.run(ctx, dataset.materialize())

        metrics = Metrics()
        with timed(metrics):
            cres, _ = self._demo_stream_write(
                ctx, dataset, table=table, database=database, schema=schema
            )
        cres.metrics.duration_ms = metrics.duration_ms
        return cres

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            rows = rows or []
            clean = [_clean_row(r) for r in rows]
            table = self.config.get("table", "FORMULAETL_LOAD")
            database = self.config.get("database", "DEMO_DB")
            schema = self.config.get("schema", "PUBLIC")

            use_demo = ctx.demo_mode or os.environ.get("FORMULAETL_DEMO") == "1"
            if not use_demo and not self.config.get("account"):
                use_demo = True
                ctx.emit("SnowflakeDestination: no account configured — using demo mode")

            if use_demo:
                out_dir = ctx.resolve(self.config.get("demo_output_dir", "data/out/snowflake"))
                out_dir.mkdir(parents=True, exist_ok=True)
                ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                out_path = out_dir / f"{table.lower()}_{ts}.csv"
                fieldnames = list(clean[0].keys()) if clean else []
                for r in clean[1:]:
                    for k in r:
                        if k not in fieldnames:
                            fieldnames.append(k)
                with out_path.open("w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(clean)

                log_path = out_path.with_suffix(".load.json")
                load_meta = {
                    "mode": "demo",
                    "target": f"{database}.{schema}.{table}",
                    "rows_loaded": len(clean),
                    "file": str(out_path),
                    "timestamp": ts,
                    "note": (
                        "Demo mode — wrote CSV with same schema as a Snowflake load. "
                        "Set FORMULAETL_DEMO=0 and provide account/user/password for real loads."
                    ),
                }
                log_path.write_text(json.dumps(load_meta, indent=2), encoding="utf-8")
                ctx.emit(
                    f"SnowflakeDestination [demo]: loaded {len(clean)} rows → "
                    f"{database}.{schema}.{table} (file={out_path})"
                )
                metrics.rows_in = len(rows)
                metrics.rows_out = len(clean)
                return ComponentResult(
                    rows=[],
                    metrics=metrics,
                    side_effects={
                        "mode": "demo",
                        "target": f"{database}.{schema}.{table}",
                        "written_path": str(out_path),
                        "load_log": str(log_path),
                        "rows_loaded": len(clean),
                    },
                    artifacts={"path": str(out_path)},
                )

            try:
                import snowflake.connector
            except ImportError as exc:
                raise ImportError(
                    "snowflake-connector-python is required for real Snowflake loads. "
                    "Install with: pip install formulaetl[snowflake]"
                ) from exc

            conn = snowflake.connector.connect(
                account=self.config["account"],
                user=self.config["user"],
                password=self.config["password"],
                warehouse=self.config.get("warehouse"),
                database=database,
                schema=schema,
            )
            try:
                cur = conn.cursor()
                if clean:
                    cols = list(clean[0].keys())
                    placeholders = ", ".join(["%s"] * len(cols))
                    col_list = ", ".join(cols)
                    sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"
                    cur.executemany(sql, [tuple(r.get(c) for c in cols) for r in clean])
                conn.commit()
                ctx.emit(f"SnowflakeDestination: inserted {len(clean)} rows into {table}")
            finally:
                conn.close()

            metrics.rows_in = len(rows)
            metrics.rows_out = len(clean)
            return ComponentResult(
                rows=[],
                metrics=metrics,
                side_effects={
                    "mode": "snowflake",
                    "target": f"{database}.{schema}.{table}",
                    "rows_loaded": len(clean),
                },
            )
