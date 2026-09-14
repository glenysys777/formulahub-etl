"""Pipeline mirror JSON, export, and import."""

from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.api_helpers import boot_api


@pytest.fixture
def client(work_dir: Path, monkeypatch, tmp_path: Path):
    formulaetl_api = boot_api(
        monkeypatch,
        work_dir=work_dir,
        db_path=tmp_path / "mirror.db",
        embedded_worker=False,
        scheduler=False,
    )
    with TestClient(formulaetl_api.app) as c:
        yield c, work_dir, formulaetl_api


def _tiny_payload():
    return {
        "name": "Mirror Me",
        "description": "disk mirror test",
        "nodes": [
            {
                "id": "src",
                "type": "local_file_source",
                "label": "Src",
                "config": {"path": "fixtures/sample/orders_17cols.csv", "format": "csv"},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "dst",
                "type": "local_file_destination",
                "label": "Dst",
                "config": {"path": "data/out/mirror.csv", "format": "csv"},
                "position": {"x": 200, "y": 0},
            },
        ],
        "edges": [{"id": "e1", "source": "src", "target": "dst"}],
    }


def test_create_and_update_write_mirror_json(client):
    c, work_dir, _api = client
    created = c.post("/api/pipelines", json=_tiny_payload())
    assert created.status_code == 201
    body = created.json()
    pid = body["id"]
    saved = Path(body["saved_path"])
    assert saved.is_file()
    assert saved == (work_dir / "pipelines" / f"{pid}.json").resolve()
    disk = json.loads(saved.read_text(encoding="utf-8"))
    assert disk["name"] == "Mirror Me"
    assert disk["id"] == pid

    updated = c.put(
        f"/api/pipelines/{pid}",
        json={**_tiny_payload(), "name": "Mirror Updated"},
    )
    assert updated.status_code == 200
    assert updated.json()["saved_path"] == str(saved)
    assert json.loads(saved.read_text(encoding="utf-8"))["name"] == "Mirror Updated"


def test_export_json_and_zip(client):
    c, _work_dir, _api = client
    pid = c.post("/api/pipelines", json=_tiny_payload()).json()["id"]

    r = c.get(f"/api/pipelines/{pid}/export")
    assert r.status_code == 200
    assert "attachment" in r.headers.get("content-disposition", "").lower()
    assert "application/json" in r.headers.get("content-type", "")
    data = r.json()
    assert data["id"] == pid
    assert data["name"] == "Mirror Me"

    z = c.get(f"/api/pipelines/{pid}/export?format=zip")
    assert z.status_code == 200
    assert "application/zip" in z.headers.get("content-type", "")
    assert z.headers.get("content-disposition", "").endswith('.zip"')
    with zipfile.ZipFile(BytesIO(z.content)) as zf:
        names = set(zf.namelist())
        assert "README.md" in names
        json_names = [n for n in names if n.endswith(".json")]
        assert len(json_names) == 1
        exported = json.loads(zf.read(json_names[0]))
        assert exported["id"] == pid


def test_import_pipeline_from_json(client):
    c, work_dir, _api = client
    payload = {**_tiny_payload(), "id": "import-me-please"}
    r = c.post("/api/pipelines/import", json=payload)
    assert r.status_code == 201
    body = r.json()
    assert body["id"] == "import-me-please"
    assert body["metadata"].get("imported") is True
    mirror = work_dir / "pipelines" / "import-me-please.json"
    assert mirror.is_file()

    # Second import with same id gets a fresh id (no clobber)
    r2 = c.post("/api/pipelines/import", json=payload)
    assert r2.status_code == 201
    assert r2.json()["id"] != "import-me-please"
