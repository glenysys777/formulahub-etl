"""Evidence: rows, logs, Jobs-API–shaped sidecar, scheduler creates run history."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from formulaetl.components.databricks_job import DatabricksJob
from formulaetl.components.http_api_source import HttpApiSource
from formulaetl.components.kafka_source import KafkaSource
from formulaetl.components.source_s3 import S3Source
from formulaetl.engine.runner import PipelineRunner
from formulaetl.models.pipeline import PipelineDefinition
from formulaetl.sdk.context import RunContext

ROOT = Path(__file__).resolve().parents[2]


def _ctx(work: Path, logs: list[str]) -> RunContext:
    return RunContext(
        run_id="evidence",
        pipeline_id="evidence",
        demo_mode=True,
        work_dir=work,
        data_dir=work / "data",
        log=logs.append,
    )


def test_kafka_demo_emits_rows_and_logs(work_dir: Path):
    logs: list[str] = []
    result = KafkaSource(
        {
            "brokers": "demo",
            "topic": "orders",
            "group_id": "formulaetl-evidence",
            "max_messages": 50,
            "format": "json",
            "security": "plain",
            "demo": True,
        }
    ).run(_ctx(work_dir, logs))
    assert result.side_effects["mode"] == "demo"
    assert result.metrics.rows_out == 8
    assert len(result.rows) == 8
    assert result.rows[0]["order_id"] == 3001
    joined = "\n".join(logs)
    assert "KafkaSource" in joined
    assert "[demo]" in joined
    assert "orders" in joined
    assert "8 messages" in joined or "8" in joined


def test_databricks_demo_jobs_api_shaped_sidecar(work_dir: Path):
    logs: list[str] = []
    rows = [{"order_id": 1, "amount": 10.5}, {"order_id": 2, "amount": 3.0}]
    result = DatabricksJob(
        {
            "workspace_host": "demo",
            "job_id": "1001",
            "notebook_params": ["source=evidence", "env=ci"],
            "wait_for_completion": True,
            "demo": True,
            "demo_output_dir": "data/out/databricks_demo",
        }
    ).run(_ctx(work_dir, logs), rows)
    assert result.side_effects["mode"] == "demo"
    assert result.side_effects["result_state"] == "SUCCESS"
    assert result.side_effects["life_cycle_state"] == "TERMINATED"
    assert result.side_effects["rows_passed"] == 2
    assert result.metrics.rows_out == 2
    sidecar = Path(result.side_effects["sidecar"])
    assert sidecar.exists()
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    assert meta["run_id"]
    assert meta["job_id"] == "1001"
    assert isinstance(meta["state"], dict)
    assert meta["state"]["life_cycle_state"] == "TERMINATED"
    assert meta["state"]["result_state"] == "SUCCESS"
    assert meta["result_state"] == "SUCCESS"  # flat alias
    assert meta["notebook_params"]["source"] == "evidence"
    assert meta["rows_passed"] == 2
    joined = "\n".join(logs)
    assert "DatabricksJob" in joined
    assert "SUCCESS" in joined
    assert "1001" in joined


def test_kafka_databricks_pipeline_logs_and_metrics(work_dir: Path):
    data = json.loads(
        (ROOT / "demos" / "api-kafka-databricks" / "pipeline.json").read_text(
            encoding="utf-8"
        )
    )
    for node in data["nodes"]:
        if node["type"] == "databricks_job":
            node["config"]["demo_output_dir"] = "data/out/databricks_demo"
    pipeline = PipelineDefinition.model_validate(data)
    result = PipelineRunner(work_dir=work_dir, demo_mode=True).run(pipeline)
    assert result.status == "success", result.error
    assert result.node_metrics["kafka"]["rows_out"] == 8
    assert result.node_metrics["databricks"]["rows_out"] == 8
    log_text = "\n".join(result.logs)
    assert "KafkaSource" in log_text
    assert "DatabricksJob" in log_text
    sidecars = list((work_dir / "data" / "out" / "databricks_demo").glob("job_1001_*.json"))
    assert sidecars
    meta = json.loads(sidecars[0].read_text(encoding="utf-8"))
    assert meta["state"]["result_state"] == "SUCCESS"
    assert meta["rows_passed"] == 8


def test_http_api_and_s3_sources_still_green(work_dir: Path):
    logs: list[str] = []
    api_result = HttpApiSource(
        {
            "url": "https://api.example.com/v1/orders",
            "method": "GET",
            "json_path": "data.items",
            "demo": True,
        }
    ).run(_ctx(work_dir, logs))
    assert api_result.metrics.rows_out >= 1
    assert any("Http" in m or "API" in m or "demo" in m.lower() for m in logs)

    s3_logs: list[str] = []
    s3_result = S3Source({"bucket": "demo", "key": "demo/orders_encrypted.csv.pgp"}).run(
        _ctx(work_dir, s3_logs)
    )
    assert s3_result.metrics.rows_out >= 1
    assert any("S3" in m for m in s3_logs)


@pytest.fixture
def api_client(monkeypatch, tmp_path: Path):
    from tests.api_helpers import boot_api

    api = boot_api(
        monkeypatch,
        work_dir=ROOT,
        db_path=tmp_path / "evidence.db",
        embedded_worker=True,
        scheduler=False,
    )
    with TestClient(api.app) as c:
        yield c, api
    from scripts.seed_demo import main

    main()


def test_scheduler_tick_creates_run_history(api_client, tmp_path: Path):
    from tests.api_helpers import wait_run

    api_client_http, api = api_client

    assert (
        api_client_http.get("/api/pipelines/demo-api-kafka-databricks").status_code
        == 200
    )

    put = api_client_http.put(
        "/api/pipelines/demo-api-kafka-databricks/schedule",
        json={"enabled": True, "cron": "* * * * *", "timezone": "UTC"},
    )
    assert put.status_code == 200

    spec = api.schedules.get("demo-api-kafka-databricks")
    assert spec is not None
    spec.next_run_at = 1.0
    api.schedules.save(spec)

    tick = api_client_http.post("/api/scheduler/tick")
    assert tick.status_code == 200
    assert "demo-api-kafka-databricks" in tick.json()["fired"]

    after = api.schedules.get("demo-api-kafka-databricks")
    assert after is not None
    assert after.last_run_id, "scheduler must record a real run_id"
    assert after.last_status == "queued"

    body = wait_run(api_client_http, after.last_run_id, timeout_sec=60)
    assert body["status"] == "success"
    assert body["pipeline_id"] == "demo-api-kafka-databricks"
    assert body.get("logs"), "run history must include logs"
    assert body.get("node_metrics") or body.get("metrics")
