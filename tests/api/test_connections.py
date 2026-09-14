"""Phase F — Connections + SecretProvider + optional API key."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.api_helpers import boot_api, wait_run

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def api(monkeypatch, tmp_path):
    db = tmp_path / "phasef.db"
    mod = boot_api(monkeypatch, work_dir=ROOT, db_path=db, embedded_worker=True)
    with TestClient(mod.app) as client:
        yield client, mod


def test_connection_crud_masks_secrets(api):
    client, _mod = api
    r = client.post(
        "/api/connections",
        json={
            "name": "Partner SFTP",
            "kind": "sftp",
            "config": {"host": "demo", "port": 22, "username": "etl"},
            "secrets": {"password": "super-secret-password"},
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    cid = body["id"]
    assert body["kind"] == "sftp"
    assert body["config"]["host"] == "demo"
    # Raw password must never appear
    assert "super-secret-password" not in r.text
    assert body["secrets"]["password"].startswith("secret:") or body["secrets"]["password"] == "***"

    g = client.get(f"/api/connections/{cid}")
    assert g.status_code == 200
    assert "super-secret-password" not in g.text
    assert g.json()["has_secrets"] == ["password"]

    listed = client.get("/api/connections").json()
    assert any(c["id"] == cid for c in listed)
    assert all("super-secret-password" not in str(c) for c in listed)

    # Update with *** keeps previous secret
    u = client.put(
        f"/api/connections/{cid}",
        json={"config": {"host": "demo", "port": 22, "username": "etl", "password": "***"}},
    )
    assert u.status_code == 200
    assert "super-secret-password" not in u.text

    d = client.delete(f"/api/connections/{cid}")
    assert d.status_code == 200
    assert client.get(f"/api/connections/{cid}").status_code == 404


def test_test_connection_demo(api):
    client, _mod = api
    r = client.post(
        "/api/connections",
        json={
            "name": "Demo SFTP",
            "kind": "sftp",
            "config": {"host": "demo", "username": "demo"},
            "secrets": {"password": "x"},
        },
    )
    cid = r.json()["id"]
    t = client.post(f"/api/connections/{cid}/test")
    assert t.status_code == 200
    body = t.json()
    assert body["ok"] is True
    assert body["mode"] == "demo"
    assert "x" not in t.text


def test_pipeline_run_with_connection_id(api):
    """Node references connection_id; DEMO inline host still works via merged config."""
    client, mod = api
    cr = client.post(
        "/api/connections",
        json={
            "name": "Demo HTTP",
            "kind": "http",
            "config": {"base_url": "https://example.com/orders", "demo": True},
            "secrets": {"auth_bearer": "tok-should-not-leak"},
        },
    )
    assert cr.status_code == 201, cr.text
    cid = cr.json()["id"]

    pipe = {
        "name": "conn-http-demo",
        "nodes": [
            {
                "id": "src",
                "type": "http_api_source",
                "label": "API",
                "config": {"connection_id": cid, "json_path": "data.items"},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "dst",
                "type": "local_file_destination",
                "label": "Out",
                "config": {"path": "data/out/conn_http_demo.json", "format": "json"},
                "position": {"x": 200, "y": 0},
            },
        ],
        "edges": [{"id": "e1", "source": "src", "target": "dst"}],
    }
    created = client.post("/api/pipelines", json=pipe)
    assert created.status_code == 201, created.text
    pid = created.json()["id"]
    # GET must not leak bearer
    got = client.get(f"/api/pipelines/{pid}")
    assert "tok-should-not-leak" not in got.text

    run = client.post(f"/api/pipelines/{pid}/run")
    assert run.status_code == 202, run.text
    detail = wait_run(client, run.json()["run_id"], formulaetl_api=mod)
    assert detail["status"] == "success", detail.get("error") or detail.get("logs")


def test_inline_demo_pipeline_still_works(api):
    """Existing demos without connection_id keep working (DEMO=1)."""
    client, mod = api
    run = client.post("/api/pipelines/demo-s3-pgp-snowflake/run")
    assert run.status_code == 202, run.text
    detail = wait_run(client, run.json()["run_id"], formulaetl_api=mod, timeout_sec=90)
    assert detail["status"] == "success", detail.get("error")


def test_api_key_gate(monkeypatch, tmp_path):
    monkeypatch.setenv("FORMULAETL_API_KEY", "test-key-phase-f")
    db = tmp_path / "auth.db"
    mod = boot_api(monkeypatch, work_dir=ROOT, db_path=db, embedded_worker=False)
    # boot_api may clear env — re-set after reload
    monkeypatch.setenv("FORMULAETL_API_KEY", "test-key-phase-f")
    with TestClient(mod.app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/health").json()["auth"] == "api_key"
        assert client.get("/api/connections").status_code == 401
        ok = client.get("/api/connections", headers={"X-API-Key": "test-key-phase-f"})
        assert ok.status_code == 200
        bearer = client.get(
            "/api/connections",
            headers={"Authorization": "Bearer test-key-phase-f"},
        )
        assert bearer.status_code == 200


def test_health_open_when_no_api_key(api):
    client, _mod = api
    h = client.get("/health").json()
    assert h["auth"] == "none"
    assert h["secrets"] == "env_and_local_encrypted"


def test_env_secret_ref_on_connection(api, monkeypatch):
    client, _mod = api
    monkeypatch.setenv("FORMULAETL_SFTP_PASSWORD", "from-env-value")
    r = client.post(
        "/api/connections",
        json={
            "name": "Env SFTP",
            "kind": "sftp",
            "config": {"host": "demo", "username": "u"},
            "secrets": {"password": "env:FORMULAETL_SFTP_PASSWORD"},
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["secrets"]["password"] == "env:FORMULAETL_SFTP_PASSWORD"
    assert "from-env-value" not in r.text
    t = client.post(f"/api/connections/{body['id']}/test")
    assert t.status_code == 200
    assert t.json()["ok"] is True
    assert "from-env-value" not in t.text


def test_unsupported_kind_rejected(api):
    client, _mod = api
    r = client.post(
        "/api/connections",
        json={"name": "x", "kind": "oracle", "config": {}},
    )
    assert r.status_code == 400
