"""Integration test: full S3→PGP→Parse→Validate→Transform→Snowflake→Archive."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from formulaetl.engine.runner import PipelineRunner
from formulaetl.models.pipeline import PipelineDefinition


def test_full_demo_pipeline(work_dir: Path, demo_pipeline_dict: dict):
    # Point archive/snowflake/rejects at work_dir-relative paths (already in config)
    pipeline = PipelineDefinition.model_validate(demo_pipeline_dict)

    # Ensure encrypted object present
    enc = work_dir / "data/s3/demo/orders_encrypted.csv.pgp"
    assert enc.exists()

    runner = PipelineRunner(work_dir=work_dir, demo_mode=True)
    result = runner.run(pipeline)

    assert result.status == "success", result.error
    assert result.error is None

    # Node-level assertions
    nm = result.node_metrics
    assert "validate" in nm
    assert nm["validate"]["rows_in"] == 13
    assert nm["validate"]["rows_out"] == 10
    assert nm["validate"]["rows_rejected"] == 3

    assert nm["transform"]["rows_out"] == 10
    assert nm["snowflake"]["rows_out"] == 10
    assert nm["rejects"]["rows_out"] == 3

    # Good rows written to snowflake demo output
    out_dir = work_dir / "data/out/snowflake"
    csv_files = list(out_dir.glob("orders_*.csv"))
    assert len(csv_files) >= 1
    with csv_files[0].open() as f:
        loaded = list(csv.DictReader(f))
    assert len(loaded) == 10
    assert "order_id" in loaded[0]
    assert loaded[0].get("loaded_by") == "formulaetl"
    # Dates normalized
    for row in loaded:
        assert len(row["order_date"]) == 10
        assert row["order_date"][4] == "-"

    # Load log sidecar
    logs = list(out_dir.glob("*.load.json"))
    assert logs
    meta = json.loads(logs[0].read_text())
    assert meta["rows_loaded"] == 10
    assert meta["mode"] == "demo"

    # Bad rows in rejects
    rejects_path = work_dir / "data/rejects/orders_rejects.csv"
    assert rejects_path.exists()
    with rejects_path.open() as f:
        rejects = list(csv.DictReader(f))
    assert len(rejects) == 3
    assert any("reject" in (r.get("_reject_reason") or "").lower() or r.get("_reject_reason") for r in rejects)

    # Archive moved the encrypted source
    assert not enc.exists(), "source should be moved by ArchiveFiles"
    archived = list((work_dir / "data/archive").glob("*.pgp"))
    assert len(archived) == 1

    # Metrics totals present
    assert result.metrics["rows_rejected"] >= 3
    assert result.duration_ms > 0
