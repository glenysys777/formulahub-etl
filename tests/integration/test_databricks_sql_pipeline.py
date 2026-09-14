"""Integration: API → Databricks SQL with Job Contexts / ${…}."""

from __future__ import annotations

import json
from pathlib import Path

from formulaetl.engine.runner import PipelineRunner
from formulaetl.models.pipeline import PipelineDefinition


def test_api_databricks_sql_demo_pipeline(work_dir: Path):
    root = Path(__file__).resolve().parents[2]
    data = json.loads(
        (root / "demos" / "api-databricks-sql" / "pipeline.json").read_text(
            encoding="utf-8"
        )
    )
    for node in data["nodes"]:
        if node["type"] == "databricks_sql":
            node["config"]["demo_output_dir"] = "data/out/databricks_sql_demo"
    pipeline = PipelineDefinition.model_validate(data)

    runner = PipelineRunner(work_dir=work_dir, demo_mode=True)
    result = runner.run(pipeline)

    assert result.status == "success", result.error
    assert result.node_metrics["api"]["rows_out"] >= 1
    assert result.node_metrics["sql"]["rows_out"] >= 1
    assert any("context=DEV" in line for line in result.logs)

    out_dir = work_dir / "data" / "out" / "databricks_sql_demo"
    sidecars = list(out_dir.glob("stmt_*.json"))
    assert sidecars, "expected Databricks SQL demo sidecar"
    meta = json.loads(sidecars[0].read_text(encoding="utf-8"))
    assert meta["mode"] == "demo"
    assert meta["status"]["state"] == "SUCCEEDED"
    assert "context.catalog" in meta["variable_refs"]
    assert "run_date" in meta["variable_refs"]
    resolved = meta["sql_resolved"]
    assert "sandbox.orders_staging" in resolved
    assert "2026-09-14" in resolved
    assert "env = 'dev'" in resolved
    # upstream.channel from first API fixture row
    assert "channel = 'api'" in resolved
    assert "${" not in resolved
    assert "${" in meta["sql_template"]
    assert any("DatabricksSQL" in line for line in result.logs)


def test_api_databricks_sql_context_override(work_dir: Path, monkeypatch):
    monkeypatch.setenv("FORMULAETL_CONTEXT", "PROD")
    root = Path(__file__).resolve().parents[2]
    data = json.loads(
        (root / "demos" / "api-databricks-sql" / "pipeline.json").read_text(
            encoding="utf-8"
        )
    )
    pipeline = PipelineDefinition.model_validate(data)
    result = PipelineRunner(work_dir=work_dir, demo_mode=True).run(pipeline)
    assert result.status == "success", result.error
    assert any("context=PROD" in line for line in result.logs)
    sidecar = next(
        (work_dir / "data" / "out" / "databricks_sql_demo").glob("stmt_*.json")
    )
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    assert "main.orders_staging" in meta["sql_resolved"]
    assert "env = 'prod'" in meta["sql_resolved"]
