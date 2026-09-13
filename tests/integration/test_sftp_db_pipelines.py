"""Integration: SFTP and Postgres demo pipelines."""

from __future__ import annotations

import json
from pathlib import Path

from formulaetl.engine.runner import PipelineRunner
from formulaetl.models.pipeline import PipelineDefinition

ROOT = Path(__file__).resolve().parents[2]


def test_sftp_excel_to_file_pipeline(work_dir: Path):
    pipeline_path = ROOT / "demos" / "sftp-excel-to-file" / "pipeline.json"
    data = json.loads(pipeline_path.read_text(encoding="utf-8"))
    pipeline = PipelineDefinition.model_validate(data)
    runner = PipelineRunner(work_dir=work_dir, demo_mode=True)
    result = runner.run(pipeline)
    assert result.status == "success", result.error
    nm = result.node_metrics
    assert nm["sftp"]["rows_out"] == 1
    assert nm["excel"]["rows_out"] == 8
    assert nm["dest"]["rows_out"] == 8
    assert (work_dir / "data/out/sftp_excel_orders.csv").exists()
    mock = work_dir / "data/out/sftp_mock/outgoing/sftp_excel_orders.csv"
    assert mock.exists()


def test_db_to_file_pipeline(work_dir: Path):
    pipeline_path = ROOT / "demos" / "db-to-file" / "pipeline.json"
    data = json.loads(pipeline_path.read_text(encoding="utf-8"))
    pipeline = PipelineDefinition.model_validate(data)
    runner = PipelineRunner(work_dir=work_dir, demo_mode=True)
    result = runner.run(pipeline)
    assert result.status == "success", result.error
    nm = result.node_metrics
    assert nm["pg"]["rows_out"] >= 10
    assert nm["dest"]["rows_out"] >= 10
    assert (work_dir / "data/out/db_orders.csv").exists()
    assert (work_dir / "data/out/postgres_demo/demo.db").exists()
    assert (work_dir / "data/out/postgres_demo/orders_loaded.csv").exists()
