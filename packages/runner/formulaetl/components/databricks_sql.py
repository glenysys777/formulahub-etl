"""Databricks SQL — run statements against a SQL Warehouse (Statement Execution API).

Demo mode writes a sidecar JSON with the *resolved* SQL under
``data/out/databricks_sql_demo/`` — no real workspace call.

LIVE Databricks SQL remains UNPROVEN until workspace credentials are provided.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.io_util import redact_secrets
from formulaetl.sdk.registry import register
from formulaetl.sdk.vars import find_refs, resolve_string, scope_from_context


@register
class DatabricksSQL(BaseComponent):
    """Execute SQL on a Databricks SQL Warehouse.

    Supports ``${context.*}``, ``${run.*}``, ``${env.*}``, ``${upstream.*}``,
    and plain ``${key}`` in the SQL text (resolved before submit).
    """

    component_type = "databricks_sql"
    display_name = "Databricks SQL"
    category = "orch"
    config_schema = {
        "type": "object",
        "required": ["workspace_host", "sql"],
        "properties": {
            "workspace_host": {
                "type": "string",
                "description": "Workspace host, e.g. https://dbc-xxxx.cloud.databricks.com",
            },
            "token": {"type": "string", "description": "Personal access token (live mode)"},
            "warehouse_id": {
                "type": "string",
                "description": "SQL Warehouse id (Statement Execution API)",
            },
            "http_path": {
                "type": "string",
                "description": "Optional SQL warehouse HTTP path (informational / connector)",
            },
            "sql": {
                "type": "string",
                "description": "SQL text; ${…} variables resolved before submit",
            },
            "catalog": {"type": "string"},
            "schema": {"type": "string"},
            "wait_for_completion": {"type": "boolean", "default": True},
            "poll_interval_sec": {"type": "number", "default": 2},
            "wait_timeout": {
                "type": "string",
                "default": "30s",
                "description": "Statement API wait_timeout (e.g. 30s)",
            },
            "demo": {"type": "boolean", "default": False},
            "demo_output_dir": {
                "type": "string",
                "default": "data/out/databricks_sql_demo",
            },
        },
    }
    parameters = [
        {
            "key": "workspace_host",
            "label": "Workspace host",
            "type": "string",
            "required": True,
            "help": "Databricks workspace URL (use demo for fixture mode)",
            "placeholder": "https://dbc-xxxx.cloud.databricks.com",
        },
        {
            "key": "token",
            "label": "Access token",
            "type": "secret",
            "required": False,
            "help": "PAT for live Statement Execution API (not needed in demo)",
        },
        {
            "key": "warehouse_id",
            "label": "Warehouse ID",
            "type": "string",
            "required": False,
            "help": "SQL Warehouse id — required for live mode",
            "placeholder": "abc123def456",
        },
        {
            "key": "http_path",
            "label": "HTTP path",
            "type": "string",
            "required": False,
            "help": "Optional warehouse HTTP path (stored for connector flip)",
            "placeholder": "/sql/1.0/warehouses/…",
        },
        {
            "key": "sql",
            "label": "SQL",
            "type": "string",
            "required": True,
            "help": "SQL with ${run_date}, ${context.env}, ${upstream.field}, …",
            "placeholder": "SELECT * FROM orders WHERE dt = '${run_date}' AND env = '${context.env}'",
        },
        {
            "key": "catalog",
            "label": "Catalog",
            "type": "string",
            "required": False,
            "help": "Optional Unity Catalog name",
        },
        {
            "key": "schema",
            "label": "Schema",
            "type": "string",
            "required": False,
            "help": "Optional schema / database",
        },
        {
            "key": "wait_for_completion",
            "label": "Wait for completion",
            "type": "boolean",
            "required": False,
            "default": True,
            "help": "Poll statement until SUCCEEDED / FAILED",
        },
        {
            "key": "poll_interval_sec",
            "label": "Poll interval (sec)",
            "type": "number",
            "required": False,
            "default": 2,
            "help": "Seconds between status polls",
        },
        {
            "key": "wait_timeout",
            "label": "Wait timeout",
            "type": "string",
            "required": False,
            "default": "30s",
            "help": "Initial Statement API wait_timeout",
        },
        {
            "key": "demo",
            "label": "Demo mode",
            "type": "boolean",
            "required": False,
            "default": False,
            "help": "Write local sidecar with resolved SQL instead of calling Databricks",
        },
        {
            "key": "demo_output_dir",
            "label": "Demo output dir",
            "type": "string",
            "required": False,
            "default": "data/out/databricks_sql_demo",
            "help": "Where to write demo statement sidecars",
        },
    ]

    def _use_demo(self, ctx: RunContext) -> bool:
        if self.config.get("demo") is True:
            return True
        host = str(self.config.get("workspace_host") or "").strip().lower()
        demo_env = ctx.demo_mode or os.environ.get("FORMULAETL_DEMO") == "1"
        if host in ("demo", "http://demo", "https://demo", "fixture"):
            return True
        if not self.config.get("token") and demo_env:
            return True
        return demo_env and ("example.com" in host or host.endswith("/demo"))

    def _resolved_sql(self, ctx: RunContext, rows: list[dict[str, Any]]) -> str:
        raw = str(self.config.get("sql") or "")
        # Runner already resolves config strings; re-resolve so standalone
        # component.run() still expands ${…} when used in unit tests.
        scope = scope_from_context(ctx, upstream_rows=rows)
        return resolve_string(raw, scope)

    def _run_demo(
        self,
        ctx: RunContext,
        rows: list[dict[str, Any]],
        sql_resolved: str,
        sql_template: str,
    ) -> dict[str, Any]:
        out_dir = ctx.resolve(
            self.config.get("demo_output_dir") or "data/out/databricks_sql_demo"
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        statement_id = f"demo-stmt-{uuid.uuid4().hex[:10]}"
        host = str(self.config.get("workspace_host") or "demo")
        warehouse_id = str(self.config.get("warehouse_id") or "demo-warehouse")
        refs = find_refs(sql_template)
        # Shape mirrors Statement Execution API GET /api/2.0/sql/statements/{id}
        payload = {
            "mode": "demo",
            "workspace_host": host,
            "warehouse_id": warehouse_id,
            "http_path": self.config.get("http_path") or "",
            "statement_id": statement_id,
            "status": {
                "state": "SUCCEEDED",
            },
            "state": "SUCCEEDED",
            "sql_template": sql_template,
            "sql_resolved": sql_resolved,
            "variable_refs": refs,
            "catalog": self.config.get("catalog") or "",
            "schema": self.config.get("schema") or "",
            "rows_in": len(rows),
            "active_context": ctx.variables.get("_contexts_active") or "",
            "start_time": ts,
            "note": (
                "DEMO mode — Statement Execution–shaped sidecar (no real warehouse call). "
                "LIVE Databricks SQL is UNPROVEN until workspace_host + token + warehouse_id "
                "are set and FORMULAETL_DEMO=0. Resolved SQL is logged with secrets redacted."
            ),
        }
        out_path = out_dir / f"stmt_{warehouse_id}_{ts}_{statement_id}.json"
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        ctx.emit(
            redact_secrets(
                f"DatabricksSQL [demo]: warehouse={warehouse_id} "
                f"statement_id={statement_id} → SUCCEEDED "
                f"(sidecar={out_path.name}, refs={refs})"
            )
        )
        ctx.emit(redact_secrets(f"DatabricksSQL [demo] resolved SQL:\n{sql_resolved}"))
        return {
            "mode": "demo",
            "statement_id": statement_id,
            "warehouse_id": warehouse_id,
            "state": "SUCCEEDED",
            "sql_resolved": sql_resolved,
            "sql_template": sql_template,
            "variable_refs": refs,
            "sidecar": str(out_path),
            "rows_in": len(rows),
            "metrics": {
                "warehouse_id": warehouse_id,
                "statement_id": statement_id,
                "state": "SUCCEEDED",
                "refs": len(refs),
            },
        }

    def _run_live(self, ctx: RunContext, sql_resolved: str) -> dict[str, Any]:
        import httpx

        host = str(self.config["workspace_host"]).rstrip("/")
        token = str(self.config.get("token") or "")
        warehouse_id = str(self.config.get("warehouse_id") or "").strip()
        if not token:
            raise ValueError("databricks_sql: token is required for live mode")
        if not warehouse_id:
            raise ValueError("databricks_sql: warehouse_id is required for live mode")

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "warehouse_id": warehouse_id,
            "statement": sql_resolved,
            "wait_timeout": str(self.config.get("wait_timeout") or "30s"),
        }
        catalog = self.config.get("catalog")
        schema = self.config.get("schema")
        if catalog:
            body["catalog"] = catalog
        if schema:
            body["schema"] = schema

        ctx.emit(redact_secrets(f"DatabricksSQL: submitting SQL:\n{sql_resolved}"))

        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                f"{host}/api/2.0/sql/statements", headers=headers, json=body
            )
            resp.raise_for_status()
            data = resp.json()
            statement_id = data.get("statement_id")
            state = ((data.get("status") or {}).get("state")) or data.get("state")
            ctx.emit(
                f"DatabricksSQL: statement_id={statement_id} state={state}"
            )

            wait = self.config.get("wait_for_completion", True)
            if wait in (False, "false", "0", 0):
                return {
                    "mode": "databricks",
                    "statement_id": statement_id,
                    "warehouse_id": warehouse_id,
                    "state": state or "PENDING",
                    "sql_resolved": sql_resolved,
                }

            if state in ("SUCCEEDED", "FAILED", "CANCELED", "CLOSED"):
                if state != "SUCCEEDED":
                    raise RuntimeError(
                        f"Databricks SQL failed: statement_id={statement_id} state={state}"
                    )
                return {
                    "mode": "databricks",
                    "statement_id": statement_id,
                    "warehouse_id": warehouse_id,
                    "state": state,
                    "sql_resolved": sql_resolved,
                }

            poll = float(self.config.get("poll_interval_sec") or 2)
            max_polls = 120
            for _ in range(max_polls):
                time.sleep(max(poll, 0.5))
                st = client.get(
                    f"{host}/api/2.0/sql/statements/{statement_id}",
                    headers=headers,
                )
                st.raise_for_status()
                info = st.json()
                state = ((info.get("status") or {}).get("state")) or info.get("state")
                if state in ("SUCCEEDED", "FAILED", "CANCELED", "CLOSED"):
                    break
            ctx.emit(
                f"DatabricksSQL: statement_id={statement_id} final_state={state}"
            )
            if state != "SUCCEEDED":
                raise RuntimeError(
                    f"Databricks SQL failed: statement_id={statement_id} state={state}"
                )
            return {
                "mode": "databricks",
                "statement_id": statement_id,
                "warehouse_id": warehouse_id,
                "state": state,
                "sql_resolved": sql_resolved,
            }

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            rows = rows or []
            templates = self.config.get("_var_templates")
            sql_template = ""
            if isinstance(templates, dict) and templates.get("sql") is not None:
                sql_template = str(templates.get("sql"))
            else:
                sql_template = str(self.config.get("sql") or "")
            sql_resolved = self._resolved_sql(ctx, rows)

            if self._use_demo(ctx):
                side = self._run_demo(ctx, rows, sql_resolved, sql_template)
            else:
                side = self._run_live(ctx, sql_resolved)

            metrics.rows_in = len(rows)
            metrics.rows_out = len(rows)
            metrics.extras["sql_refs"] = len(
                side.get("variable_refs") or find_refs(sql_template)
            )

        return ComponentResult(
            rows=rows,
            metrics=metrics,
            side_effects=side,
            artifacts={"databricks_sql": side},
        )
