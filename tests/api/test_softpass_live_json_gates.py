"""Focused Soft-PASS gates: live mid-run progress + JSON write / schema fixtures.

These tests intentionally fail if:
- a demo-shaped run never exposes updating ``node_runs`` while ``status=running``
- Soft-PASS fixtures for Schema from JSON / Write JSON are missing or broken
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from formulaetl.components.schema_from_json import SchemaFromJSON, load_schema_payload
from formulaetl.engine.runner import PipelineRunner
from formulaetl.models.pipeline import PipelineDefinition
from formulaetl.sdk.context import RunContext
from formulaetl.sdk.registry import list_components
from formulaetl_api.worker import RunWorker
from tests.api_helpers import boot_api, wait_run

ROOT = Path(__file__).resolve().parents[2]

SOFTPASS_SAMPLE = ROOT / "fixtures" / "sample" / "orders_target_sample.json"
SOFTPASS_SCHEMA = ROOT / "fixtures" / "sample" / "orders_target_schema.json"
SOFTPASS_DEMO = ROOT / "demos" / "api-json-write" / "pipeline.json"
SOFTPASS_API_FIXTURE = ROOT / "fixtures" / "sample" / "api_orders.json"


@pytest.fixture
def client(monkeypatch, tmp_path: Path):
    api = boot_api(
        monkeypatch,
        work_dir=ROOT,
        db_path=tmp_path / "softpass_gates.db",
        embedded_worker=False,
        scheduler=False,
    )
    with TestClient(api.app) as c:
        yield c, api


def test_softpass_fixtures_exist_for_schema_and_write_json():
    """Fail loud if founder Soft-PASS fixtures are missing from the tree."""
    missing = [
        str(p.relative_to(ROOT))
        for p in (SOFTPASS_SAMPLE, SOFTPASS_SCHEMA, SOFTPASS_DEMO, SOFTPASS_API_FIXTURE)
        if not p.exists()
    ]
    assert not missing, f"Soft-PASS fixtures missing: {missing}"

    sample = json.loads(SOFTPASS_SAMPLE.read_text(encoding="utf-8"))
    assert isinstance(sample, dict) and "order" in sample and "customer" in sample

    schema = json.loads(SOFTPASS_SCHEMA.read_text(encoding="utf-8"))
    assert isinstance(schema.get("properties"), dict)
    assert "order" in schema["properties"]

    demo = json.loads(SOFTPASS_DEMO.read_text(encoding="utf-8"))
    types = {n["type"] for n in demo["nodes"]}
    assert "schema_from_json" in types
    assert "write_json" in types
    assert "http_api_source" in types
    # FormulaHub display names only in labels (no competitor brands)
    blob = json.dumps(demo).lower()
    for banned in ("talend", "tmap", "twritejson", "informatica", "ssis"):
        assert banned not in blob, f"competitor string {banned!r} in demo pipeline"

    by_type = {c["type"]: c for c in list_components()}
    assert by_type["write_json"]["display_name"] == "Write JSON"
    assert by_type["schema_from_json"]["display_name"] == "Schema from JSON"
    for name in (by_type["write_json"]["display_name"], by_type["schema_from_json"]["display_name"]):
        assert "talend" not in name.lower()


def test_schema_from_target_fixtures_load_columns(work_dir: Path):
    """Schema from JSON must load Soft-PASS sample + JSON Schema fixtures."""
    cols_sample, meta_s = load_schema_payload(
        content=None,
        path=SOFTPASS_SAMPLE,
        source_kind="sample",
    )
    assert meta_s["source_kind"] == "sample"
    assert "order.id" in cols_sample or "product_sku" in cols_sample
    assert len(cols_sample) >= 5

    cols_schema, meta_j = load_schema_payload(
        content=None,
        path=SOFTPASS_SCHEMA,
        source_kind="json_schema",
    )
    assert meta_j["source_kind"] == "json_schema"
    assert len(cols_schema) >= 5

    ctx = RunContext(
        run_id="sfj-softpass",
        pipeline_id="p",
        demo_mode=True,
        work_dir=ROOT,
        data_dir=work_dir / "data",
    )
    # Copy fixtures into isolated work_dir and run relative paths (Studio shape).
    dest = work_dir / "fixtures" / "sample"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "orders_target_sample.json").write_text(
        SOFTPASS_SAMPLE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    ctx.work_dir = work_dir
    res = SchemaFromJSON(
        {
            "path": "fixtures/sample/orders_target_sample.json",
            "source_kind": "sample",
            "pass_rows": True,
        }
    ).run(ctx, [{"x": 1}])
    assert res.metrics.rows_out == 1
    assert ctx.variables.get("target_schema")
    assert res.artifacts.get("columns")


def test_demo_run_live_progress_must_update_during_run(client, monkeypatch):
    """Hard fail if demo Soft-PASS run never updates node_runs while running."""
    c, api = client
    monkeypatch.setenv("FORMULAETL_PROGRESS_TICK_MS", "200")

    # Ensure bundled demo is present in this API store.
    got = c.get("/api/pipelines/demo-api-json-write")
    if got.status_code != 200:
        data = json.loads(SOFTPASS_DEMO.read_text(encoding="utf-8"))
        data["id"] = "demo-api-json-write"
        assert c.post("/api/pipelines", json=data).status_code in (200, 201)

    run = c.post("/api/pipelines/demo-api-json-write/run")
    assert run.status_code == 202
    run_id = run.json()["run_id"]

    worker = RunWorker(
        api.runs,
        api.pipelines,
        work_dir=ROOT,
        demo_mode=True,
        poll_interval_sec=0.05,
        max_concurrent=1,
    )

    mid_snapshots: list[dict] = []

    def _drive() -> None:
        worker.tick_once()

    t = threading.Thread(target=_drive, daemon=True)
    t.start()

    deadline = time.time() + 30
    while time.time() < deadline:
        body = c.get(f"/api/runs/{run_id}").json()
        if body["status"] == "running" and body.get("node_runs"):
            snap = {
                "node_ids": sorted(
                    n["node_id"] for n in body["node_runs"] if n.get("node_id")
                ),
                "statuses": {
                    n["node_id"]: n.get("status") for n in body["node_runs"]
                },
                "rows_out": {
                    n["node_id"]: int(n.get("rows_out") or 0)
                    for n in body["node_runs"]
                },
            }
            mid_snapshots.append(snap)
            # Soft-PASS: progress must change across polls (new nodes / statuses / rows).
            distinct = {json.dumps(s, sort_keys=True) for s in mid_snapshots}
            multi_nodes = any(len(s["node_ids"]) > 1 for s in mid_snapshots)
            has_rows = any(
                any(v > 0 for v in s["rows_out"].values()) for s in mid_snapshots
            )
            if has_rows and (len(distinct) >= 2 or multi_nodes):
                break
        if body["status"] in ("success", "failed", "cancelled", "timed_out"):
            break
        time.sleep(0.05)

    t.join(timeout=30)
    final = wait_run(c, run_id, formulaetl_api=api, timeout_sec=45)
    assert final["status"] == "success", final.get("error")

    assert mid_snapshots, (
        "Soft-PASS FAIL: never saw node_runs while status=running — "
        "live canvas counters cannot tick for founders"
    )
    # At least one mid-run row counter must be non-zero (records moving).
    assert any(
        any(v > 0 for v in snap["rows_out"].values()) for snap in mid_snapshots
    ), f"Soft-PASS FAIL: mid-run node_runs never showed rows_out>0: {mid_snapshots[:3]}"

    # Progress must change across polls OR include >1 completed nodes mid-run.
    distinct = {json.dumps(s, sort_keys=True) for s in mid_snapshots}
    multi_nodes = any(len(s["node_ids"]) > 1 for s in mid_snapshots)
    assert len(distinct) >= 2 or multi_nodes, (
        "Soft-PASS FAIL: live progress never updated during demo run "
        f"(snapshots={len(mid_snapshots)}, distinct={len(distinct)}, "
        f"sample={mid_snapshots[:3]})"
    )

    dest = next(n for n in final["node_runs"] if n["node_id"] == "dest")
    assert dest["status"] == "success"
    assert int(dest["rows_out"]) == 12
    out = ROOT / "data" / "out" / "api_orders.json"
    assert out.exists(), "Write JSON Soft-PASS output missing after demo run"
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert isinstance(payload, list) and len(payload) == 12
    assert "order" in payload[0] and "customer" in payload[0]


def test_api_json_write_demo_pipeline_write_json_softpass(work_dir: Path):
    """Runner Soft-PASS: demo writes nested JSON using Schema from JSON + Write JSON."""
    assert SOFTPASS_DEMO.exists()
    data = json.loads(SOFTPASS_DEMO.read_text(encoding="utf-8"))
    pipeline = PipelineDefinition.model_validate(data)
    os.environ["FORMULAETL_PROGRESS_TICK_MS"] = "0"
    result = PipelineRunner(work_dir=work_dir, demo_mode=True).run(pipeline)
    assert result.status == "success", result.error
    assert result.node_metrics["schema"]["rows_out"] == 12
    assert result.node_metrics["dest"]["rows_out"] == 12
    out = work_dir / "data" / "out" / "api_orders.json"
    assert out.exists()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert len(payload) == 12
    assert payload[0]["order"]["order_id"] == 2001
    assert payload[0]["customer"]["customer_name"] == "Acme Corp"
