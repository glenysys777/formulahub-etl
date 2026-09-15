"""Palette contract: /api/components must expose the non-AI build catalog."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def client(monkeypatch):
    from scripts.seed_demo import main

    main()
    monkeypatch.setenv("FORMULAETL_WORK_DIR", str(ROOT))
    monkeypatch.setenv("FORMULAETL_DEMO", "1")
    monkeypatch.setenv("FORMULAETL_SCHEDULER", "0")

    import importlib
    import formulaetl_api

    importlib.reload(formulaetl_api)
    formulaetl_api.WORK_DIR = ROOT
    formulaetl_api.DEMO_MODE = True
    formulaetl_api._scheduler = None

    with TestClient(formulaetl_api.app) as c:
        yield c

    main()


def test_components_endpoint_has_palette_essentials(client: TestClient):
    r = client.get("/api/components")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list) and len(body) >= 10
    by_type = {c["type"]: c for c in body}

    # Non-AI path essentials for company jobs (palette must stand alone)
    for required in (
        "http_api_source",
        "kafka_source",
        "s3_source",
        "column_map",
        "tmap",
        "transform",
        "databricks_job",
        "databricks_sql",
        "run_pipeline",
        "local_file_destination",
    ):
        assert required in by_type, f"missing palette component {required}"

    for c in body:
        assert c.get("display_name"), c
        assert c.get("category"), c
        assert "parameters" in c
        name = (c["display_name"] or "").lower()
        assert "talend" not in name

    assert by_type["kafka_source"]["display_name"] == "Kafka Source"
    assert by_type["databricks_job"]["display_name"] == "Databricks Job"
    assert by_type["databricks_sql"]["display_name"] == "Databricks SQL"
    assert by_type["run_pipeline"]["display_name"] == "Run Pipeline"
    assert by_type["run_pipeline"]["category"] == "orch"
    assert "talend" not in (by_type["run_pipeline"]["display_name"] or "").lower()
    assert by_type["tmap"]["display_name"] == "Field Mapper"
    assert by_type["s3_source"]["display_name"] == "S3 Source"


def test_create_blank_pipeline_for_palette_path(client: TestClient):
    r = client.post(
        "/api/pipelines",
        json={
            "name": "Untitled pipeline",
            "description": "Blank canvas from palette",
            "nodes": [],
            "edges": [],
            "metadata": {"created_via": "palette"},
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["id"]
    assert body["nodes"] == []
    assert body["name"] == "Untitled pipeline"
