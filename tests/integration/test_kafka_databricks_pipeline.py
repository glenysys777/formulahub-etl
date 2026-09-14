"""Integration: Kafka → map → Databricks demo pipeline."""

from __future__ import annotations

import json
from pathlib import Path

from formulaetl.engine.runner import PipelineRunner
from formulaetl.models.pipeline import PipelineDefinition


def test_kafka_databricks_demo_pipeline(work_dir: Path):
    root = Path(__file__).resolve().parents[2]
    data = json.loads(
        (root / "demos" / "api-kafka-databricks" / "pipeline.json").read_text(
            encoding="utf-8"
        )
    )
    # Point demo output into isolated work_dir
    for node in data["nodes"]:
        if node["type"] == "databricks_job":
            node["config"]["demo_output_dir"] = "data/out/databricks_demo"
    pipeline = PipelineDefinition.model_validate(data)

    runner = PipelineRunner(work_dir=work_dir, demo_mode=True)
    result = runner.run(pipeline)

    assert result.status == "success", result.error
    assert result.node_metrics["kafka"]["rows_out"] == 8
    assert result.node_metrics["map"]["rows_out"] == 8
    assert result.node_metrics["databricks"]["rows_out"] == 8

    out_dir = work_dir / "data" / "out" / "databricks_demo"
    sidecars = list(out_dir.glob("job_1001_*.json"))
    assert sidecars, "expected Databricks demo sidecar"
    meta = json.loads(sidecars[0].read_text(encoding="utf-8"))
    assert meta["mode"] == "demo"
    assert meta["state"]["result_state"] == "SUCCESS"
    assert meta["state"]["life_cycle_state"] == "TERMINATED"
    assert meta["rows_passed"] == 8
    assert any("KafkaSource" in line for line in result.logs)
    assert any("DatabricksJob" in line for line in result.logs)


def test_s3_databricks_demo_pipeline(work_dir: Path):
    root = Path(__file__).resolve().parents[2]
    data = json.loads(
        (root / "demos" / "s3-databricks" / "pipeline.json").read_text(encoding="utf-8")
    )
    for node in data["nodes"]:
        if node["type"] == "databricks_job":
            node["config"]["demo_output_dir"] = "data/out/databricks_demo"
    pipeline = PipelineDefinition.model_validate(data)
    runner = PipelineRunner(work_dir=work_dir, demo_mode=True)
    result = runner.run(pipeline)
    assert result.status == "success", result.error
    assert result.node_metrics["s3"]["rows_out"] == 1
    sidecars = list((work_dir / "data" / "out" / "databricks_demo").glob("job_2002_*.json"))
    assert sidecars
