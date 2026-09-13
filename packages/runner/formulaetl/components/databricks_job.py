"""Databricks Job Trigger — orchestrate a Databricks Jobs API run (not a Spark engine)."""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.registry import register


def _parse_map(raw: Any) -> dict[str, str]:
    """Accept dict, JSON string, or list of key=value / key: value lines."""
    if not raw:
        return {}
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return {}
        if s.startswith("{"):
            data = json.loads(s)
            return {str(k): str(v) for k, v in data.items()}
        lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
        return _map_from_lines(lines)
    if isinstance(raw, list):
        return _map_from_lines([str(x).strip() for x in raw if str(x).strip()])
    return {}


def _map_from_lines(lines: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in lines:
        if "=" in line:
            k, v = line.split("=", 1)
        elif ":" in line:
            k, v = line.split(":", 1)
        else:
            continue
        out[k.strip()] = v.strip()
    return out


@register
class DatabricksJob(BaseComponent):
    """Trigger a Databricks workspace job via the Jobs API.

    Demo mode writes a sidecar JSON under data/out/databricks_demo/ — no real workspace.
    This is orchestration (“call their job / notebook”), not an embedded Spark runtime.
    """

    component_type = "databricks_job"
    display_name = "Databricks Job"
    category = "destination"
    config_schema = {
        "type": "object",
        "required": ["workspace_host", "job_id"],
        "properties": {
            "workspace_host": {
                "type": "string",
                "description": "Workspace host, e.g. https://dbc-xxxx.cloud.databricks.com",
            },
            "token": {"type": "string", "description": "Personal access token (live mode)"},
            "job_id": {"type": "string", "description": "Databricks job id"},
            "notebook_params": {
                "description": "Notebook parameters as map / JSON / key=value lines",
            },
            "python_params": {
                "description": "Python task parameters as map / JSON / key=value lines",
            },
            "wait_for_completion": {"type": "boolean", "default": True},
            "poll_interval_sec": {"type": "number", "default": 5},
            "demo": {"type": "boolean", "default": False},
            "demo_output_dir": {
                "type": "string",
                "default": "data/out/databricks_demo",
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
            "help": "PAT for live Jobs API (not needed in demo)",
        },
        {
            "key": "job_id",
            "label": "Job ID",
            "type": "string",
            "required": True,
            "help": "Numeric Databricks job id to trigger",
        },
        {
            "key": "notebook_params",
            "label": "Notebook params",
            "type": "string_list",
            "required": False,
            "help": "One key=value per line (passed as notebook_params)",
        },
        {
            "key": "python_params",
            "label": "Python params",
            "type": "string_list",
            "required": False,
            "help": "One key=value per line (passed as python_params)",
        },
        {
            "key": "wait_for_completion",
            "label": "Wait for completion",
            "type": "boolean",
            "required": False,
            "default": True,
            "help": "Poll run until TERMINATED / SUCCESS / FAILED",
        },
        {
            "key": "poll_interval_sec",
            "label": "Poll interval (sec)",
            "type": "number",
            "required": False,
            "default": 5,
            "help": "Seconds between Jobs API status polls",
        },
        {
            "key": "demo",
            "label": "Demo mode",
            "type": "boolean",
            "required": False,
            "default": False,
            "help": "Write local sidecar JSON instead of calling Databricks",
        },
        {
            "key": "demo_output_dir",
            "label": "Demo output dir",
            "type": "string",
            "required": False,
            "default": "data/out/databricks_demo",
            "help": "Where to write demo run sidecars",
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

    def _run_demo(
        self,
        ctx: RunContext,
        rows: list[dict[str, Any]],
        notebook_params: dict[str, str],
        python_params: dict[str, str],
    ) -> dict[str, Any]:
        out_dir = ctx.resolve(
            self.config.get("demo_output_dir") or "data/out/databricks_demo"
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_id = f"demo-{uuid.uuid4().hex[:10]}"
        job_id = str(self.config.get("job_id") or "0")
        host = str(self.config.get("workspace_host") or "demo")
        payload = {
            "mode": "demo",
            "workspace_host": host,
            "job_id": job_id,
            "run_id": run_id,
            "state": "SUCCESS",
            "life_cycle_state": "TERMINATED",
            "result_state": "SUCCESS",
            "notebook_params": notebook_params,
            "python_params": python_params,
            "rows_passed": len(rows),
            "triggered_at": ts,
            "note": (
                "Demo mode — simulated Databricks Jobs API run. "
                "Set FORMULAETL_DEMO=0 and provide workspace_host + token for live triggers."
            ),
        }
        out_path = out_dir / f"job_{job_id}_{ts}_{run_id}.json"
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        ctx.emit(
            f"DatabricksJob [demo]: job_id={job_id} → SUCCESS "
            f"(sidecar={out_path.name}, rows_in={len(rows)})"
        )
        return {
            "mode": "demo",
            "run_id": run_id,
            "job_id": job_id,
            "state": "SUCCESS",
            "sidecar": str(out_path),
            "rows_passed": len(rows),
        }

    def _run_live(
        self,
        ctx: RunContext,
        notebook_params: dict[str, str],
        python_params: dict[str, str],
    ) -> dict[str, Any]:
        import httpx

        host = str(self.config["workspace_host"]).rstrip("/")
        token = str(self.config.get("token") or "")
        if not token:
            raise ValueError("databricks_job: token is required for live mode")
        job_id = self.config["job_id"]
        try:
            job_id_num: int | str = int(job_id)
        except (TypeError, ValueError):
            job_id_num = job_id

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {"job_id": job_id_num}
        if notebook_params:
            body["notebook_params"] = notebook_params
        if python_params:
            # Jobs API accepts python_params as a list of strings for some task types;
            # also send as map under job_parameters when useful.
            body["python_params"] = [f"{k}={v}" for k, v in python_params.items()]

        with httpx.Client(timeout=60.0) as client:
            resp = client.post(f"{host}/api/2.1/jobs/run-now", headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
            run_id = data.get("run_id")
            ctx.emit(f"DatabricksJob: triggered job_id={job_id} run_id={run_id}")

            wait = self.config.get("wait_for_completion", True)
            if wait in (False, "false", "0", 0):
                return {
                    "mode": "databricks",
                    "run_id": run_id,
                    "job_id": str(job_id),
                    "state": "SUBMITTED",
                }

            poll = float(self.config.get("poll_interval_sec") or 5)
            # Cap polls for safety in CI / misconfig
            max_polls = 120
            state = "RUNNING"
            result_state = None
            for _ in range(max_polls):
                time.sleep(max(poll, 0.5))
                st = client.get(
                    f"{host}/api/2.1/jobs/runs/get",
                    headers=headers,
                    params={"run_id": run_id},
                )
                st.raise_for_status()
                info = st.json()
                life = (info.get("state") or {}).get("life_cycle_state") or ""
                result_state = (info.get("state") or {}).get("result_state")
                state = life
                if life in ("TERMINATED", "SKIPPED", "INTERNAL_ERROR"):
                    break
            ctx.emit(
                f"DatabricksJob: run_id={run_id} life={state} result={result_state}"
            )
            if result_state and result_state not in ("SUCCESS", "SUCCESS_WITH_FAILURES"):
                raise RuntimeError(
                    f"Databricks job run failed: run_id={run_id} result_state={result_state}"
                )
            return {
                "mode": "databricks",
                "run_id": run_id,
                "job_id": str(job_id),
                "state": result_state or state,
            }

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            rows = rows or []
            notebook_params = _parse_map(self.config.get("notebook_params"))
            python_params = _parse_map(self.config.get("python_params"))
            # Pass row count / sample hint into notebook params when not set
            if rows and "row_count" not in notebook_params:
                notebook_params = {**notebook_params, "row_count": str(len(rows))}

            if self._use_demo(ctx):
                side = self._run_demo(ctx, rows, notebook_params, python_params)
            else:
                side = self._run_live(ctx, notebook_params, python_params)

            metrics.rows_in = len(rows)
            metrics.rows_out = len(rows)

        return ComponentResult(
            rows=rows,
            metrics=metrics,
            side_effects=side,
            artifacts={"databricks_run": side},
        )
