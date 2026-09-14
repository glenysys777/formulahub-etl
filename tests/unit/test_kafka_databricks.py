"""Unit tests for Kafka Source and Databricks Job (demo mode)."""

from __future__ import annotations

import json
from pathlib import Path

from formulaetl.components.kafka_source import KafkaSource
from formulaetl.components.databricks_job import DatabricksJob
from formulaetl.sdk.context import RunContext
from formulaetl.sdk.registry import list_components


def ctx(work: Path) -> RunContext:
    return RunContext(
        run_id="test",
        pipeline_id="test",
        demo_mode=True,
        work_dir=work,
        data_dir=work / "data",
        log=lambda m: None,
    )


def test_kafka_and_databricks_registered():
    types = {c["type"] for c in list_components()}
    assert "kafka_source" in types
    assert "databricks_job" in types
    by = {c["type"]: c for c in list_components()}
    kkeys = {p["key"] for p in by["kafka_source"]["parameters"]}
    assert {"brokers", "topic", "group_id", "format", "security"}.issubset(kkeys)
    dkeys = {p["key"] for p in by["databricks_job"]["parameters"]}
    assert {"workspace_host", "job_id", "token", "wait_for_completion"}.issubset(dkeys)


def test_kafka_source_demo_fixture(work_dir: Path):
    c = KafkaSource(
        {
            "brokers": "demo",
            "topic": "orders",
            "group_id": "formulaetl",
            "max_messages": 50,
            "format": "json",
            "security": "plain",
            "demo": True,
        }
    )
    result = c.run(ctx(work_dir))
    assert result.side_effects["mode"] == "demo"
    assert result.metrics.rows_out == 8
    assert result.rows[0]["order_id"] == 3001
    assert result.rows[0]["channel"] == "kafka"


def test_kafka_source_demo_via_env(work_dir: Path, monkeypatch):
    monkeypatch.setenv("FORMULAETL_DEMO", "1")
    c = KafkaSource(
        {
            "brokers": "localhost:9092",
            "topic": "orders",
            "max_messages": 3,
            "format": "json",
        }
    )
    result = c.run(ctx(work_dir))
    assert result.metrics.rows_out == 3
    assert result.side_effects["mode"] == "demo"


def test_databricks_job_demo(work_dir: Path):
    rows = [{"order_id": 1, "amount": 10.5}, {"order_id": 2, "amount": 3}]
    c = DatabricksJob(
        {
            "workspace_host": "demo",
            "job_id": "1001",
            "notebook_params": ["source=test", "env=demo"],
            "wait_for_completion": True,
            "demo": True,
            "demo_output_dir": "data/out/databricks_demo",
        }
    )
    result = c.run(ctx(work_dir), rows)
    assert result.side_effects["mode"] == "demo"
    assert result.side_effects["state"] == "SUCCESS"
    assert result.side_effects["rows_passed"] == 2
    sidecar = Path(result.side_effects["sidecar"])
    assert sidecar.exists()
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    assert meta["job_id"] == "1001"
    assert meta["result_state"] == "SUCCESS"
    assert isinstance(meta["state"], dict)
    assert meta["state"]["life_cycle_state"] == "TERMINATED"
    assert meta["state"]["result_state"] == "SUCCESS"
    assert meta["run_id"]
    assert meta["notebook_params"]["source"] == "test"
    assert meta["notebook_params"]["row_count"] == "2"
    assert result.side_effects["life_cycle_state"] == "TERMINATED"
    assert result.side_effects["result_state"] == "SUCCESS"


def test_databricks_job_demo_without_token(work_dir: Path):
    c = DatabricksJob(
        {
            "workspace_host": "https://example.com/demo",
            "job_id": "42",
            "demo_output_dir": "data/out/databricks_demo",
        }
    )
    result = c.run(ctx(work_dir), [])
    assert result.side_effects["mode"] == "demo"
