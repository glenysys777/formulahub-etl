"""Scheduler unit + API tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from formulaetl_api.scheduler import (
    PipelineScheduler,
    ScheduleStore,
    cron_matches,
    next_cron_fire,
)
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[2]


def test_cron_matches_every_minute():
    dt = datetime(2024, 6, 1, 12, 30, tzinfo=timezone.utc)
    assert cron_matches("* * * * *", dt)
    assert cron_matches("30 * * * *", dt)
    assert not cron_matches("0 * * * *", dt)


def test_next_cron_fire_every_minute():
    base = datetime(2024, 6, 1, 12, 0, 10, tzinfo=timezone.utc).timestamp()
    nxt = next_cron_fire("* * * * *", base, "UTC")
    # Should land on next whole minute after base
    assert nxt > base
    assert int(nxt) % 60 == 0


def test_scheduler_fires_with_fake_clock(tmp_path: Path):
    store = ScheduleStore(tmp_path / "schedules")
    fired: list[str] = []
    clock = {"t": 1_700_000_000.0}

    def run_cb(pid: str):
        fired.append(pid)
        return {"run_id": "r1", "status": "success"}

    sched = PipelineScheduler(
        store,
        run_cb,
        clock=lambda: clock["t"],
        poll_interval_sec=60,
    )
    # Force due immediately: next_run_at in the past
    spec = sched.upsert("pipe-a", enabled=True, cron="* * * * *", timezone="UTC")
    assert spec.next_run_at is not None
    # Move clock past next_run
    clock["t"] = float(spec.next_run_at) + 1
    got = sched.tick()
    assert got == ["pipe-a"]
    assert fired == ["pipe-a"]
    # Persisted
    saved = store.get("pipe-a")
    assert saved is not None
    assert saved.last_status == "success"
    assert saved.last_run_id == "r1"
    assert saved.next_run_at is not None
    assert saved.next_run_at > clock["t"] - 1

    # Survive "restart" — reload store
    store2 = ScheduleStore(tmp_path / "schedules")
    reloaded = store2.get("pipe-a")
    assert reloaded is not None
    assert reloaded.enabled is True
    assert reloaded.cron == "* * * * *"


@pytest.fixture
def client(work_dir: Path, monkeypatch):
    from scripts.seed_demo import main

    main()
    monkeypatch.setenv("FORMULAETL_WORK_DIR", str(ROOT))
    monkeypatch.setenv("FORMULAETL_DEMO", "1")
    monkeypatch.setenv("FORMULAETL_SCHEDULER", "0")  # no background thread in tests

    import importlib
    import formulaetl_api

    importlib.reload(formulaetl_api)
    formulaetl_api.WORK_DIR = ROOT
    formulaetl_api.DEMO_MODE = True
    formulaetl_api.pipelines = formulaetl_api.PipelineStore(ROOT / "data" / "pipelines")
    formulaetl_api.schedules = formulaetl_api.ScheduleStore(ROOT / "data" / "schedules")
    formulaetl_api._scheduler = None

    with TestClient(formulaetl_api.app) as c:
        yield c

    main()


def test_schedule_api_put_get_and_tick(client: TestClient, tmp_path: Path):
    import formulaetl_api
    from formulaetl_api.scheduler import ScheduleStore

    store = ScheduleStore(tmp_path / "schedules")
    formulaetl_api.schedules = store
    formulaetl_api._scheduler = None

    # Ensure demo pipeline exists
    r = client.get("/api/pipelines/demo-api-kafka-databricks")
    assert r.status_code == 200

    put = client.put(
        "/api/pipelines/demo-api-kafka-databricks/schedule",
        json={"enabled": True, "cron": "* * * * *", "timezone": "UTC"},
    )
    assert put.status_code == 200
    body = put.json()
    assert body["enabled"] is True
    assert body["cron"] == "* * * * *"
    assert body["next_run_at"] is not None
    assert isinstance(body["next_run_at"], (int, float))
    assert body["next_run_at"] > 0

    got = client.get("/api/pipelines/demo-api-kafka-databricks/schedule")
    assert got.status_code == 200
    got_body = got.json()
    assert got_body["enabled"] is True
    # Persisted + returned on GET (not compute-only ephemeral)
    assert got_body["next_run_at"] == body["next_run_at"]
    on_disk = store.get("demo-api-kafka-databricks")
    assert on_disk is not None
    assert on_disk.next_run_at == body["next_run_at"]

    # Force due: rewrite next_run_at into the past
    spec = store.get("demo-api-kafka-databricks")
    assert spec is not None
    spec.next_run_at = 1.0
    store.save(spec)

    tick = client.post("/api/scheduler/tick")
    assert tick.status_code == 200
    data = tick.json()
    assert "demo-api-kafka-databricks" in data["fired"]

    after = store.get("demo-api-kafka-databricks")
    assert after is not None
    assert after.last_run_id, "due schedule must fire a real run"
    assert after.last_status == "success"
    assert after.next_run_at and after.next_run_at > 1.0

    # Run history must be queryable (not a UI-only stub)
    run = client.get(f"/api/runs/{after.last_run_id}")
    assert run.status_code == 200
    body = run.json()
    assert body["status"] == "success"
    assert body["pipeline_id"] == "demo-api-kafka-databricks"
    assert body.get("logs")


def test_list_components_includes_kafka_databricks(client: TestClient):
    r = client.get("/api/components")
    types = {c["type"] for c in r.json()}
    assert "kafka_source" in types
    assert "databricks_job" in types
