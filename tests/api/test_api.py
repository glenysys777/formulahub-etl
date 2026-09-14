"""API tests: create pipeline, AI build, run, poll status."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.api_helpers import boot_api, wait_run

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def client(work_dir: Path, monkeypatch, tmp_path: Path):
    formulaetl_api = boot_api(
        monkeypatch,
        work_dir=ROOT,
        db_path=tmp_path / "api.db",
        embedded_worker=True,
        scheduler=False,
    )
    with TestClient(formulaetl_api.app) as c:
        yield c
    from scripts.seed_demo import main

    main()


def test_health(client: TestClient):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["demo_mode"] is True
    assert body["run_store"] == "sqlite"


def test_list_components(client: TestClient):
    r = client.get("/api/components")
    assert r.status_code == 200
    body = r.json()
    types = {c["type"] for c in body}
    for required in (
        "s3_source",
        "pgp_decrypt",
        "csv_parser",
        "schema_validate",
        "transform",
        "snowflake_destination",
        "archive_files",
        "http_api_source",
        "column_map",
        "excel_source",
        "excel_destination",
        "json_parser",
        "dedupe",
        "sqlite_source",
        "sqlite_destination",
        "sftp_source",
        "sftp_destination",
        "postgres_source",
        "postgres_destination",
        "lookup_join",
        "sort",
        "tmap",
        "aggregate",
        "python_row",
        "pgp_encrypt",
        "xml_parser",
        "mysql_source",
        "mysql_destination",
        "kafka_source",
        "databricks_job",
    ):
        assert required in types
    by_type = {c["type"]: c for c in body}
    s3 = by_type["s3_source"]
    assert "parameters" in s3
    keys = {p["key"] for p in s3["parameters"]}
    assert {"bucket", "key"}.issubset(keys)
    for p in s3["parameters"]:
        assert "label" in p and "type" in p
        assert p["type"] in {"string", "number", "boolean", "secret", "select", "string_list"}
    pgp = by_type["pgp_decrypt"]
    passphrase = next(p for p in pgp["parameters"] if p["key"] == "passphrase")
    assert passphrase["type"] == "secret"


def test_ai_build_offline(client: TestClient):
    prompt = (
        "Read encrypted files from S3, decrypt using PGP, validate these 17 columns, "
        "reject invalid records, transform dates, load good records into Snowflake "
        "and archive processed files."
    )
    r = client.post("/api/ai/build", json={"description": prompt})
    assert r.status_code == 200
    body = r.json()
    assert body["nodes"]
    types = [n["type"] for n in body["nodes"]]
    assert "s3_source" in types
    assert "pgp_decrypt" in types
    assert "schema_validate" in types
    assert "transform" in types
    assert "snowflake_destination" in types
    assert "archive_files" in types
    assert body["edges"]
    from formulaetl.models.pipeline import PipelineDefinition

    PipelineDefinition.model_validate(body).topological_order()


def test_create_and_run_demo(client: TestClient):
    r = client.get("/api/pipelines/demo-s3-pgp-snowflake")
    assert r.status_code == 200

    run = client.post("/api/pipelines/demo-s3-pgp-snowflake/run")
    assert run.status_code == 202
    body = run.json()
    run_id = body["run_id"]
    assert body["status"] == "queued"
    assert body.get("pipeline_version_id")

    status = wait_run(client, run_id)
    assert status["status"] == "success", status.get("error")
    assert status["metrics"]["rows_rejected"] >= 3
    assert status["node_metrics"]["validate"]["rows_out"] == 10
    assert status["node_metrics"]["validate"]["rows_rejected"] == 3
    assert status["node_runs"]
    assert status["events"]


def test_create_pipeline_crud(client: TestClient):
    payload = {
        "name": "Tiny Pipeline",
        "description": "file to file",
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
                "config": {"path": "data/out/tiny.csv", "format": "csv"},
                "position": {"x": 200, "y": 0},
            },
        ],
        "edges": [{"id": "e1", "source": "src", "target": "dst"}],
    }
    created = client.post("/api/pipelines", json=payload)
    assert created.status_code == 201
    pid = created.json()["id"]
    assert created.json().get("pipeline_version_id")

    got = client.get(f"/api/pipelines/{pid}")
    assert got.status_code == 200
    assert got.json()["name"] == "Tiny Pipeline"

    listed = client.get("/api/pipelines")
    assert any(p["id"] == pid for p in listed.json())


def test_ai_build_api_flow(client: TestClient):
    prompt = (
        "Pull orders from a REST API endpoint, map columns from camelCase to snake_case, "
        "transform dates, validate schema, and write a local CSV file."
    )
    r = client.post("/api/ai/build", json={"description": prompt})
    assert r.status_code == 200
    body = r.json()
    types = [n["type"] for n in body["nodes"]]
    assert "http_api_source" in types
    assert "column_map" in types
    map_node = next(n for n in body["nodes"] if n["type"] == "column_map")
    mappings = map_node["config"].get("mappings") or []
    assert mappings, "AI Build should populate column_map mappings from schema discover"
    assert any("orderId" in m and "order_id" in m for m in mappings)
    api_src = next(n for n in body["nodes"] if n["type"] == "http_api_source")
    assert api_src["config"].get("discovered_schema", {}).get("columns")
    from formulaetl.models.pipeline import PipelineDefinition

    PipelineDefinition.model_validate(body).topological_order()


def test_ai_build_excel_flow(client: TestClient):
    prompt = (
        "Read orders from an Excel spreadsheet xlsx, map columns, "
        "transform dates, validate schema, and write a local CSV file."
    )
    r = client.post("/api/ai/build", json={"description": prompt})
    assert r.status_code == 200
    body = r.json()
    types = [n["type"] for n in body["nodes"]]
    assert "excel_source" in types
    assert "column_map" in types
    map_node = next(n for n in body["nodes"] if n["type"] == "column_map")
    mappings = map_node["config"].get("mappings") or []
    assert mappings, "AI Build should populate column_map mappings from schema discover"
    assert any("Order ID" in m and "order_id" in m for m in mappings)
    assert any("Customer Name" in m and "customer_name" in m for m in mappings)
    excel = next(n for n in body["nodes"] if n["type"] == "excel_source")
    assert excel["config"].get("discovered_schema", {}).get("columns")
    assert body.get("metadata", {}).get("schema_enriched") is True
    from formulaetl.models.pipeline import PipelineDefinition

    PipelineDefinition.model_validate(body).topological_order()


def test_run_excel_demo(client: TestClient):
    r = client.get("/api/pipelines/demo-excel-to-file")
    assert r.status_code == 200
    run = client.post("/api/pipelines/demo-excel-to-file/run")
    assert run.status_code == 202
    body = wait_run(client, run.json()["run_id"])
    assert body["status"] == "success", body.get("error")
    assert body["node_metrics"]["excel"]["rows_out"] == 8
    assert body["node_metrics"]["dest_csv"]["rows_out"] == 8


def test_ai_build_sftp_flow(client: TestClient):
    prompt = (
        "Download an Excel spreadsheet from SFTP, map columns, "
        "and write a local CSV file."
    )
    r = client.post("/api/ai/build", json={"description": prompt})
    assert r.status_code == 200
    body = r.json()
    types = [n["type"] for n in body["nodes"]]
    assert "sftp_source" in types
    assert "excel_source" in types
    from formulaetl.models.pipeline import PipelineDefinition

    PipelineDefinition.model_validate(body).topological_order()


def test_ai_build_postgres_flow(client: TestClient):
    prompt = (
        "Read orders from Postgres with a SQL query and write a local CSV file."
    )
    r = client.post("/api/ai/build", json={"description": prompt})
    assert r.status_code == 200
    body = r.json()
    types = [n["type"] for n in body["nodes"]]
    assert "postgres_source" in types
    from formulaetl.models.pipeline import PipelineDefinition

    PipelineDefinition.model_validate(body).topological_order()


def test_run_sftp_demo(client: TestClient):
    r = client.get("/api/pipelines/demo-sftp-excel-to-file")
    assert r.status_code == 200
    run = client.post("/api/pipelines/demo-sftp-excel-to-file/run")
    assert run.status_code == 202
    body = wait_run(client, run.json()["run_id"])
    assert body["status"] == "success", body.get("error")
    assert body["node_metrics"]["excel"]["rows_out"] == 8


def test_run_db_demo(client: TestClient):
    r = client.get("/api/pipelines/demo-db-to-file")
    assert r.status_code == 200
    run = client.post("/api/pipelines/demo-db-to-file/run")
    assert run.status_code == 202
    body = wait_run(client, run.json()["run_id"])
    assert body["status"] == "success", body.get("error")
    assert body["node_metrics"]["pg"]["rows_out"] >= 10


def test_schema_discover_excel(client: TestClient):
    r = client.post(
        "/api/schema/discover",
        json={
            "component_type": "excel_source",
            "config": {
                "path": "fixtures/sample/orders.xlsx",
                "sheet_name": "Orders",
                "has_header": True,
            },
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    names = [c["name"] for c in body["columns"]]
    assert "Order ID" in names
    assert "Qty" in names
    assert body.get("sample_rows")


def test_schema_discover_api_fixture(client: TestClient):
    r = client.post(
        "/api/schema/discover",
        json={
            "component_type": "http_api_source",
            "config": {
                "url": "https://api.example.com/v1/orders",
                "json_path": "data.items",
                "demo": True,
            },
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    names = [c["name"] for c in body["columns"]]
    assert "orderId" in names
