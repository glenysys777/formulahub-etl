"""Phase D/E: async queue, worker, durable history, pipeline versions, concurrency."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from formulaetl.models.pipeline import PipelineDefinition
from formulaetl_api.db import Database
from formulaetl_api.store import PipelineStore, RunStore
from formulaetl_api.worker import RunWorker
from tests.api_helpers import boot_api, wait_run

ROOT = Path(__file__).resolve().parents[2]


def _tiny_pipeline(pid: str, out_name: str) -> dict:
    return {
        "id": pid,
        "name": f"Tiny {pid}",
        "description": "control-plane test",
        "nodes": [
            {
                "id": "src",
                "type": "local_file_source",
                "label": "Src",
                "config": {
                    "path": "fixtures/sample/orders_17cols.csv",
                    "format": "csv",
                },
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "dst",
                "type": "local_file_destination",
                "label": "Dst",
                "config": {"path": f"data/out/{out_name}.csv", "format": "csv"},
                "position": {"x": 200, "y": 0},
            },
        ],
        "edges": [{"id": "e1", "source": "src", "target": "dst"}],
    }


@pytest.fixture
def client(monkeypatch, tmp_path: Path):
    api = boot_api(
        monkeypatch,
        work_dir=ROOT,
        db_path=tmp_path / "phase_de.db",
        embedded_worker=True,
        scheduler=False,
    )
    with TestClient(api.app) as c:
        yield c, api
    from scripts.seed_demo import main

    main()


def test_queue_accepts_run_returns_202_queued(client):
    c, _api = client
    created = c.post("/api/pipelines", json=_tiny_pipeline("q-accept", "q_accept"))
    assert created.status_code == 201
    pid = created.json()["id"]

    run = c.post(f"/api/pipelines/{pid}/run")
    assert run.status_code == 202
    body = run.json()
    assert body["status"] == "queued"
    assert body["run_id"]
    assert body["pipeline_version_id"]

    # Immediately visible as queued or already claimed/running/success
    got = c.get(f"/api/runs/{body['run_id']}")
    assert got.status_code == 200
    assert got.json()["status"] in ("queued", "running", "success")


def test_worker_completes_queued_run(client):
    c, api = client
    # Disable embedded race: drain explicitly
    if api._worker:
        api._worker.stop()
        api._worker = None
    api.EMBEDDED_WORKER = False

    created = c.post("/api/pipelines", json=_tiny_pipeline("w-complete", "w_complete"))
    pid = created.json()["id"]
    run = c.post(f"/api/pipelines/{pid}/run")
    assert run.status_code == 202
    run_id = run.json()["run_id"]
    assert c.get(f"/api/runs/{run_id}").json()["status"] == "queued"

    worker = api.get_worker()
    assert worker.tick_once() is True
    body = wait_run(c, run_id, formulaetl_api=api, timeout_sec=30)
    assert body["status"] == "success", body.get("error")
    assert body["pipeline_version_id"]
    assert any(e["to_status"] == "queued" for e in body["events"])
    assert any(e["to_status"] == "running" for e in body["events"])
    assert any(e["to_status"] == "success" for e in body["events"])
    assert body["node_runs"]
    node_ids = {n["node_id"] for n in body["node_runs"]}
    assert "src" in node_ids and "dst" in node_ids
    for n in body["node_runs"]:
        assert n["component_type"]
        assert n["status"] == "success"
        assert "duration_ms" in n


def test_restart_persistence(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "persist.db"
    api = boot_api(
        monkeypatch,
        work_dir=ROOT,
        db_path=db_path,
        embedded_worker=False,
        scheduler=False,
    )
    with TestClient(api.app) as c:
        created = c.post(
            "/api/pipelines", json=_tiny_pipeline("persist-pipe", "persist_out")
        )
        assert created.status_code == 201
        pid = created.json()["id"]
        version_id = created.json()["pipeline_version_id"]
        run = c.post(f"/api/pipelines/{pid}/run")
        run_id = run.json()["run_id"]
        api.get_worker().drain(timeout_sec=30)
        body = c.get(f"/api/runs/{run_id}").json()
        assert body["status"] == "success"
        events_before = body["events"]

    # Simulate process restart — new Database handle on same file
    api.db.close()
    api2 = boot_api(
        monkeypatch,
        work_dir=ROOT,
        db_path=db_path,
        embedded_worker=False,
        scheduler=False,
    )
    with TestClient(api2.app) as c2:
        p = c2.get(f"/api/pipelines/{pid}")
        assert p.status_code == 200
        assert p.json()["pipeline_version_id"] == version_id
        versions = c2.get(f"/api/pipelines/{pid}/versions").json()
        assert any(v["id"] == version_id for v in versions)
        got = c2.get(f"/api/runs/{run_id}")
        assert got.status_code == 200
        body2 = got.json()
        assert body2["status"] == "success"
        assert body2["pipeline_version_id"] == version_id
        assert len(body2["events"]) == len(events_before)
        assert body2["node_runs"]
        schedules = c2.get("/api/schedules")
        assert schedules.status_code == 200


def test_version_pin_survives_edit(client):
    c, api = client
    if api._worker:
        api._worker.stop()
    api.EMBEDDED_WORKER = False
    api._worker = None

    payload = _tiny_pipeline("ver-pin", "ver_pin_a")
    created = c.post("/api/pipelines", json=payload)
    pid = created.json()["id"]
    v1 = created.json()["pipeline_version_id"]

    run = c.post(f"/api/pipelines/{pid}/run")
    run_id = run.json()["run_id"]
    assert run.json()["pipeline_version_id"] == v1
    api.get_worker().drain(timeout_sec=30)
    assert c.get(f"/api/runs/{run_id}").json()["status"] == "success"

    # Edit pipeline (new version)
    payload["name"] = "Tiny ver-pin EDITED"
    payload["nodes"][1]["config"]["path"] = "data/out/ver_pin_b.csv"
    updated = c.put(f"/api/pipelines/{pid}", json=payload)
    assert updated.status_code == 200
    v2 = updated.json()["pipeline_version_id"]
    assert v2 != v1

    # Yesterday's run still pinned to v1 snapshot
    historical = c.get(f"/api/runs/{run_id}").json()
    assert historical["pipeline_version_id"] == v1
    snap = c.get(f"/api/pipelines/{pid}/versions/{v1}").json()
    assert snap["definition"]["name"] == "Tiny ver-pin"
    assert "ver_pin_a.csv" in snap["definition"]["nodes"][1]["config"]["path"]

    head = c.get(f"/api/pipelines/{pid}").json()
    assert head["name"] == "Tiny ver-pin EDITED"
    assert head["pipeline_version_id"] == v2


def test_concurrent_runs_smoke(client):
    c, api = client
    # Ensure worker can run multiple at once
    if api._worker:
        api._worker.stop()
    api._worker = None
    api.EMBEDDED_WORKER = False

    ids = []
    for i in range(3):
        created = c.post(
            "/api/pipelines",
            json=_tiny_pipeline(f"conc-{i}", f"conc_{i}"),
        )
        assert created.status_code == 201
        ids.append(created.json()["id"])

    run_ids = []
    for pid in ids:
        r = c.post(f"/api/pipelines/{pid}/run")
        assert r.status_code == 202
        assert r.json()["status"] == "queued"
        run_ids.append(r.json()["run_id"])

    assert api.runs.queue_depth() == 3

    worker = RunWorker(
        api.runs,
        api.pipelines,
        work_dir=ROOT,
        demo_mode=True,
        max_concurrent=3,
        poll_interval_sec=0.05,
    )
    worker.start()
    try:
        deadline = time.time() + 60
        while time.time() < deadline:
            statuses = [c.get(f"/api/runs/{rid}").json()["status"] for rid in run_ids]
            if all(s == "success" for s in statuses):
                break
            time.sleep(0.05)
        else:
            statuses = [c.get(f"/api/runs/{rid}").json() for rid in run_ids]
            raise AssertionError(f"concurrent runs did not finish: {statuses}")
    finally:
        worker.stop()

    # No global lock serialization claim — all three succeeded independently
    for rid in run_ids:
        body = c.get(f"/api/runs/{rid}").json()
        assert body["status"] == "success"
        assert body["node_runs"]


def test_store_version_hash_stable(tmp_path: Path):
    db = Database(tmp_path / "hash.db")
    store = PipelineStore(db)
    store.ensure()
    p = PipelineDefinition.model_validate(_tiny_pipeline("hash-p", "hash_out"))
    v1 = store.save(p)
    v2 = store.save(p)  # identical content → same version
    assert v1.id == v2.id
    assert v1.version_num == 1
    p2 = p.model_copy(update={"name": "changed"})
    v3 = store.save(p2)
    assert v3.id != v1.id
    assert v3.version_num == 2
