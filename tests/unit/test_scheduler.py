"""Scheduler unit + API tests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from formulaetl_api.db import Database
from formulaetl_api.scheduler import (
    PipelineScheduler,
    ScheduleStore,
    cron_matches,
    next_cron_fire,
)
from tests.api_helpers import boot_api, wait_run

ROOT = Path(__file__).resolve().parents[2]


def test_cron_matches_every_minute():
    dt = datetime(2024, 6, 1, 12, 30, tzinfo=timezone.utc)
    assert cron_matches("* * * * *", dt)
    assert cron_matches("30 * * * *", dt)
    assert not cron_matches("0 * * * *", dt)


def test_next_cron_fire_every_minute():
    base = datetime(2024, 6, 1, 12, 0, 10, tzinfo=timezone.utc).timestamp()
    nxt = next_cron_fire("* * * * *", base, "UTC")
    assert nxt > base
    assert int(nxt) % 60 == 0


def test_scheduler_fires_with_fake_clock(tmp_path: Path):
    store = ScheduleStore(Database(tmp_path / "sched.db"))
    fired: list[str] = []
    clock = {"t": 1_700_000_000.0}

    def run_cb(pid: str):
        fired.append(pid)
        return {"run_id": "r1", "status": "queued"}

    sched = PipelineScheduler(
        store,
        run_cb,
        clock=lambda: clock["t"],
        poll_interval_sec=60,
    )
    spec = sched.upsert("pipe-a", enabled=True, cron="* * * * *", timezone="UTC")
    assert spec.next_run_at is not None
    clock["t"] = float(spec.next_run_at) + 1
    got = sched.tick()
    assert got == ["pipe-a"]
    assert fired == ["pipe-a"]
    saved = store.get("pipe-a")
    assert saved is not None
    assert saved.last_status == "queued"
    assert saved.last_run_id == "r1"
    assert saved.next_run_at is not None
    assert saved.next_run_at > clock["t"] - 1

    # Survive "restart" — reload store on same DB file
    store2 = ScheduleStore(Database(tmp_path / "sched.db"))
    reloaded = store2.get("pipe-a")
    assert reloaded is not None
    assert reloaded.enabled is True
    assert reloaded.cron == "* * * * *"


@pytest.fixture
def client(monkeypatch, tmp_path: Path):
    api = boot_api(
        monkeypatch,
        work_dir=ROOT,
        db_path=tmp_path / "sched_api.db",
        embedded_worker=True,
        scheduler=False,
    )
    with TestClient(api.app) as c:
        yield c, api
    from scripts.seed_demo import main

    main()


def test_schedule_api_put_get_and_tick(client):
    c, api = client

    r = c.get("/api/pipelines/demo-api-kafka-databricks")
    assert r.status_code == 200

    put = c.put(
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

    got = c.get("/api/pipelines/demo-api-kafka-databricks/schedule")
    assert got.status_code == 200
    got_body = got.json()
    assert got_body["enabled"] is True
    assert got_body["next_run_at"] == body["next_run_at"]
    on_disk = api.schedules.get("demo-api-kafka-databricks")
    assert on_disk is not None
    assert on_disk.next_run_at == body["next_run_at"]

    # Force due: rewrite next_run_at into the past
    spec = api.schedules.get("demo-api-kafka-databricks")
    assert spec is not None
    spec.next_run_at = 1.0
    api.schedules.save(spec)

    tick = c.post("/api/scheduler/tick")
    assert tick.status_code == 200
    data = tick.json()
    assert "demo-api-kafka-databricks" in data["fired"]

    after = api.schedules.get("demo-api-kafka-databricks")
    assert after is not None
    assert after.last_run_id, "due schedule must enqueue a real run"
    assert after.last_status == "queued"
    assert after.next_run_at and after.next_run_at > 1.0

    # Worker completes the enqueued run
    body = wait_run(c, after.last_run_id, timeout_sec=60)
    assert body["status"] == "success"
    assert body["pipeline_id"] == "demo-api-kafka-databricks"
    assert body.get("logs")


def test_list_components_includes_kafka_databricks(client):
    c, _api = client
    r = c.get("/api/components")
    types = {c_["type"] for c_ in r.json()}
    assert "kafka_source" in types
    assert "databricks_job" in types
