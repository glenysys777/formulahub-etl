"""Integration: DEMO master with two Run Pipeline children + QA context inherit."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from formulaetl.engine.runner import PipelineRunner
from formulaetl.models.pipeline import PipelineDefinition

ROOT = Path(__file__).resolve().parents[2]
MASTER = ROOT / "demos" / "master-file-to-databricks" / "pipeline.json"


@pytest.fixture
def work_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Copy fixtures + demo JSON into an isolated work dir."""
    import shutil

    fixtures = ROOT / "fixtures"
    if fixtures.exists():
        shutil.copytree(fixtures, tmp_path / "fixtures")
    demo_src = ROOT / "demos" / "master-file-to-databricks"
    demo_dst = tmp_path / "demos" / "master-file-to-databricks"
    demo_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(demo_src, demo_dst)
    monkeypatch.setenv("FORMULAETL_DEMO", "1")
    monkeypatch.setenv("FORMULAETL_CONTEXT", "QA")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_master_demo_runs_two_children_with_qa_inherit(work_dir: Path):
    pipeline = PipelineDefinition.model_validate(
        json.loads((work_dir / "demos/master-file-to-databricks/pipeline.json").read_text())
    )
    runner = PipelineRunner(work_dir=work_dir, demo_mode=True)
    result = runner.run(pipeline)

    assert result.status == "success", result.error
    children = (result.metrics or {}).get("children") or {}
    assert set(children) >= {"ingest", "load"}
    assert children["ingest"]["status"] == "success"
    assert children["load"]["status"] == "success"
    assert children["ingest"]["context"] == "QA"
    assert children["load"]["context"] == "QA"
    assert children["ingest"]["env"] == "qa"
    assert children["load"]["catalog"] == "qa_main"
    assert int(children["ingest"]["rows_out"]) > 0

    # Child A wrote staging CSV
    staging = work_dir / "data/out/master_child/ingest_staging.csv"
    assert staging.exists()

    # Child B DEMO sidecar with resolved SQL reflecting QA context
    sql_dir = work_dir / "data/out/master_child/databricks_sql_demo"
    sidecars = list(sql_dir.glob("*.json"))
    assert sidecars, "expected Databricks SQL DEMO sidecar"
    payload = json.loads(sidecars[0].read_text())
    sql = payload.get("sql_resolved") or payload.get("sql") or ""
    assert "qa_main" in sql or "qa" in sql.lower()

    # Node metrics for both Run Pipeline steps
    assert "run_ingest" in result.node_metrics
    assert "run_load" in result.node_metrics
    assert result.node_metrics["run_ingest"].get("child_status") == "success"
    assert result.node_metrics["run_load"].get("publish_as") == "load"
