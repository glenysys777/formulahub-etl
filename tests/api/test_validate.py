"""Phase G — pipeline validate API + run summary observability."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.api_helpers import boot_api, wait_run

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def api(monkeypatch, tmp_path):
    db = tmp_path / "phaseg.db"
    mod = boot_api(monkeypatch, work_dir=ROOT, db_path=db, embedded_worker=True)
    with TestClient(mod.app) as client:
        yield client, mod


def test_validate_demo_pipeline_ok(api):
    client, _mod = api
    r = client.post("/api/pipelines/demo-api-map-transform/validate")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "ok" in body
    assert "checks" in body
    assert "summary" in body
    assert isinstance(body["checks"], list)
    assert body["summary"]["errors"] >= 0
    # Flagship API-map demo should pass preflight under DEMO fixtures
    assert body["ok"] is True, body
    codes = {c["code"] for c in body["checks"]}
    assert "graph_acyclic" in codes


def test_validate_detects_cycle(api):
    client, _mod = api
    created = client.post(
        "/api/pipelines",
        json={
            "name": "Cycle graph",
            "nodes": [
                {"id": "a", "type": "logger_metrics", "config": {}, "position": {"x": 0, "y": 0}},
                {"id": "b", "type": "logger_metrics", "config": {}, "position": {"x": 1, "y": 0}},
            ],
            "edges": [
                {"id": "e1", "source": "a", "target": "b"},
                {"id": "e2", "source": "b", "target": "a"},
            ],
        },
    )
    assert created.status_code == 201, created.text
    pid = created.json()["id"]
    r = client.post(f"/api/pipelines/{pid}/validate")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert any(c["code"] == "cycle" and c["severity"] == "error" for c in body["checks"])
    assert all(c.get("symbol") in ("✓", "⚠", "✗", "?") for c in body["checks"])


def test_validate_missing_required_and_mapping(api):
    client, _mod = api
    created = client.post(
        "/api/pipelines",
        json={
            "name": "Empty map",
            "nodes": [
                {
                    "id": "map1",
                    "type": "column_map",
                    "config": {"mappings": []},
                    "position": {"x": 0, "y": 0},
                }
            ],
            "edges": [],
        },
    )
    pid = created.json()["id"]
    r = client.post(f"/api/pipelines/{pid}/validate")
    body = r.json()
    assert body["ok"] is False
    codes = {c["code"] for c in body["checks"] if c["severity"] == "error"}
    assert "missing_required" in codes or "mapping_missing" in codes


def test_validate_body_unsaved_canvas(api):
    """Validate current canvas JSON without relying on stored graph."""
    client, _mod = api
    # Ensure pipeline id exists
    created = client.post(
        "/api/pipelines",
        json={"name": "Scratch", "nodes": [], "edges": []},
    )
    pid = created.json()["id"]
    r = client.post(
        f"/api/pipelines/{pid}/validate",
        json={
            "name": "Scratch",
            "nodes": [
                {
                    "id": "src",
                    "type": "http_api_source",
                    "config": {"url": "https://example.com/orders.json"},
                    "position": {"x": 0, "y": 0},
                },
                {
                    "id": "map",
                    "type": "column_map",
                    "config": {"mappings": ["id:order_id"]},
                    "position": {"x": 100, "y": 0},
                },
            ],
            "edges": [{"id": "e1", "source": "src", "target": "map"}],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True, body
    assert any(c["code"] == "mapping_present" for c in body["checks"])


def test_validate_unknown_type_and_dangling_edge(api):
    client, _mod = api
    created = client.post(
        "/api/pipelines",
        json={
            "name": "Broken",
            "nodes": [
                {"id": "a", "type": "not_a_real_component", "config": {}, "position": {"x": 0, "y": 0}},
            ],
            "edges": [{"id": "e1", "source": "a", "target": "missing"}],
        },
    )
    # PipelineCreate may still save — pydantic nodes are dicts
    assert created.status_code == 201
    pid = created.json()["id"]
    r = client.post(f"/api/pipelines/{pid}/validate")
    body = r.json()
    assert body["ok"] is False
    codes = {c["code"] for c in body["checks"]}
    assert "unknown_type" in codes
    assert "dangling_edge" in codes or "graph_invalid" in codes


def test_validate_connection_id_resolves(api):
    client, _mod = api
    conn = client.post(
        "/api/connections",
        json={
            "name": "Val SFTP",
            "kind": "sftp",
            "config": {"host": "demo", "username": "demo"},
            "secrets": {"password": "x"},
        },
    )
    assert conn.status_code == 201
    cid = conn.json()["id"]
    created = client.post(
        "/api/pipelines",
        json={
            "name": "With connection",
            "nodes": [
                {
                    "id": "src",
                    "type": "sftp_source",
                    "config": {
                        "connection_id": cid,
                        "host": "demo",
                        "remote_path": "/in/orders.xlsx",
                        "local_staging_path": "data/staging/orders.xlsx",
                    },
                    "position": {"x": 0, "y": 0},
                }
            ],
            "edges": [],
        },
    )
    pid = created.json()["id"]
    r = client.post(f"/api/pipelines/{pid}/validate")
    body = r.json()
    assert any(c["code"] == "connection_resolves" for c in body["checks"]), body
    # Missing connection
    bad = client.post(
        f"/api/pipelines/{pid}/validate",
        json={
            "nodes": [
                {
                    "id": "src",
                    "type": "sftp_source",
                    "config": {
                        "connection_id": "does-not-exist",
                        "host": "demo",
                        "remote_path": "/in/orders.xlsx",
                        "local_staging_path": "data/staging/orders.xlsx",
                    },
                    "position": {"x": 0, "y": 0},
                }
            ],
            "edges": [],
        },
    )
    assert bad.json()["ok"] is False
    assert any(c["code"] == "connection_missing" for c in bad.json()["checks"])


def test_validate_secret_ref_without_leaking_value(api, monkeypatch):
    client, mod = api
    monkeypatch.setenv("FORMULAETL_TEST_SECRET_VAL", "hunter2-should-never-appear")
    created = client.post(
        "/api/pipelines",
        json={
            "name": "Secret ref",
            "nodes": [
                {
                    "id": "http",
                    "type": "http_api_source",
                    "config": {
                        "url": "https://example.com/x",
                        "auth_bearer": "env:FORMULAETL_TEST_SECRET_VAL",
                    },
                    "position": {"x": 0, "y": 0},
                }
            ],
            "edges": [],
        },
    )
    pid = created.json()["id"]
    r = client.post(f"/api/pipelines/{pid}/validate")
    assert "hunter2-should-never-appear" not in r.text
    body = r.json()
    assert any(c["code"] == "secret_resolves" for c in body["checks"]), body

    # Unresolved env ref
    bad = client.post(
        f"/api/pipelines/{pid}/validate",
        json={
            "nodes": [
                {
                    "id": "http",
                    "type": "http_api_source",
                    "config": {
                        "url": "https://example.com/x",
                        "auth_bearer": "env:FORMULAETL_MISSING_SECRET_XYZ",
                    },
                    "position": {"x": 0, "y": 0},
                }
            ],
            "edges": [],
        },
    )
    assert "hunter2" not in bad.text
    assert any(c["code"] == "secret_unresolved" for c in bad.json()["checks"])


def test_get_run_exposes_summary_node_runs_events(api):
    client, _mod = api
    run = client.post("/api/pipelines/demo-api-map-transform/run")
    assert run.status_code == 202, run.text
    run_id = run.json()["run_id"]
    detail = wait_run(client, run_id)
    assert detail["status"] == "success"
    assert "summary" in detail
    s = detail["summary"]
    assert s["status"] == "success"
    assert "rows_in" in s and "rows_out" in s and "rows_rejected" in s
    assert "duration_ms" in s
    assert "nodes_total" in s
    assert "event_count" in s
    assert isinstance(detail.get("node_runs"), list)
    assert len(detail["node_runs"]) >= 1
    nr = detail["node_runs"][0]
    for key in ("node_id", "component_type", "status", "rows_in", "rows_out", "rows_rejected", "duration_ms"):
        assert key in nr, key
    assert isinstance(detail.get("events"), list)
    assert len(detail["events"]) >= 1
    assert detail["metrics"].get("rows_in") is not None or s["rows_in"] is not None
