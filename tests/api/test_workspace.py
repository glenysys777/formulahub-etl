"""Studio Workspace folders API + metadata.workspace_folder."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.api_helpers import boot_api

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def client(monkeypatch, tmp_path: Path):
    formulaetl_api = boot_api(
        monkeypatch,
        work_dir=ROOT,
        db_path=tmp_path / "workspace.db",
        embedded_worker=False,
        scheduler=False,
    )
    with TestClient(formulaetl_api.app) as c:
        yield c, ROOT, formulaetl_api


def test_workspace_defaults_and_demo_folders(client):
    c, work_dir, _api = client
    r = c.get("/api/workspace")
    assert r.status_code == 200
    body = r.json()
    for folder in (
        "Pipelines/Demos",
        "Pipelines/My pipelines",
        "Masters",
        "Reusable",
    ):
        assert folder in body["folders"]
    assert body["pipelineFolders"]["demo-lookup-join-mapper"] == "Pipelines/Demos"
    assert body["pipelineFolders"]["demo-s3-databricks"] == "Pipelines/Demos"
    assert body["pipelineFolders"]["demo-s3-pgp-snowflake"] == "Pipelines/Demos"
    assert body["pipelineFolders"]["demo-master-file-to-databricks"] == "Masters"
    assert body["pipelineFolders"]["demo-master-child-ingest"] == "Reusable"
    ws_file = work_dir / "data" / "workspace.json"
    assert ws_file.is_file()
    disk = json.loads(ws_file.read_text(encoding="utf-8"))
    assert "Pipelines/Demos" in disk["folders"]


def test_create_blank_lands_in_my_pipelines_and_survives_save(client):
    c, _work_dir, _api = client
    created = c.post(
        "/api/pipelines",
        json={
            "name": "My blank",
            "description": "folder test",
            "nodes": [],
            "edges": [],
            "metadata": {
                "created_via": "blank",
                "workspace_folder": "Pipelines/My pipelines",
            },
        },
    )
    assert created.status_code == 201
    body = created.json()
    pid = body["id"]
    assert body["metadata"]["workspace_folder"] == "Pipelines/My pipelines"

    ws = c.get("/api/workspace").json()
    assert ws["pipelineFolders"][pid] == "Pipelines/My pipelines"

    # Save without workspace_folder in body — must preserve assignment
    saved = c.put(
        f"/api/pipelines/{pid}",
        json={
            "name": "My blank saved",
            "description": "folder test",
            "nodes": [],
            "edges": [],
            "metadata": {"created_via": "blank"},
        },
    )
    assert saved.status_code == 200
    assert saved.json()["metadata"]["workspace_folder"] == "Pipelines/My pipelines"

    got = c.get(f"/api/pipelines/{pid}").json()
    assert got["metadata"]["workspace_folder"] == "Pipelines/My pipelines"


def test_move_pipeline_updates_metadata_and_index(client):
    c, work_dir, _api = client
    created = c.post(
        "/api/pipelines",
        json={
            "name": "Movable",
            "description": "",
            "nodes": [],
            "edges": [],
            "metadata": {"workspace_folder": "Pipelines/My pipelines"},
        },
    ).json()
    pid = created["id"]
    moved = c.post(
        "/api/workspace/move",
        json={"pipeline_id": pid, "folder": "Masters"},
    )
    assert moved.status_code == 200
    assert moved.json()["folder"] == "Masters"
    assert moved.json()["pipeline"]["metadata"]["workspace_folder"] == "Masters"
    assert c.get("/api/workspace").json()["pipelineFolders"][pid] == "Masters"
    disk = json.loads((work_dir / "data" / "workspace.json").read_text(encoding="utf-8"))
    assert disk["pipelineFolders"][pid] == "Masters"


def test_demo_pipeline_metadata_has_workspace_folder(client):
    c, _work_dir, _api = client
    p = c.get("/api/pipelines/demo-lookup-join-mapper").json()
    assert p["metadata"]["workspace_folder"] == "Pipelines/Demos"
    master = c.get("/api/pipelines/demo-master-file-to-databricks").json()
    assert master["metadata"]["workspace_folder"] == "Masters"
