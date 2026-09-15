"""Lookup Join stress + Job Context ${…} Soft-PASS harness tests.

Always-on: small N correctness + DEV/QA/PROD path substitution.
Heavy 100k Soft-PASS: marked ``bench`` (RUN_BENCH=1).
Never claims LIVE_EXTERNAL.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts.lookup_join_stress import (
    build_pipeline,
    prove_context_switch,
    run_one,
)

ROOT = Path(__file__).resolve().parents[2]


def test_build_pipeline_has_job_contexts_and_templates():
    pipe = build_pipeline(active="QA")
    assert pipe["metadata"]["contexts"]["active"] == "QA"
    sets = pipe["metadata"]["contexts"]["sets"]
    assert set(sets) == {"DEV", "QA", "PROD"}
    for name, vals in sets.items():
        assert "${" not in vals["orders_path"]
        assert vals["join_key"] == "customer_id"
        assert name.lower() in vals["orders_path"]
    orders = next(n for n in pipe["nodes"] if n["id"] == "orders")
    join = next(n for n in pipe["nodes"] if n["id"] == "join")
    dest = next(n for n in pipe["nodes"] if n["id"] == "dest")
    assert orders["config"]["path"] == "${context.orders_path}"
    assert dest["config"]["path"] == "${context.out_path}"
    assert join["config"]["left_keys"] == ["${context.join_key}"]
    assert pipe["metadata"]["classification"] == "LOCAL/DEMO Soft-PASS"
    assert pipe["metadata"].get("live_wedge") is not True


def test_demo_pipeline_json_matches_builder_shape():
    path = ROOT / "demos" / "lookup-join-contexts" / "pipeline.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "contexts" in data["metadata"]
    assert set(data["metadata"]["contexts"]["sets"]) == {"DEV", "QA", "PROD"}
    types = [n["type"] for n in data["nodes"]]
    assert types == [
        "local_file_source",
        "local_file_source",
        "lookup_join",
        "column_map",
        "local_file_destination",
    ]


def test_lookup_join_stress_small(tmp_path: Path):
    """CI-safe Soft-PASS smoke — 2k left / 100 lookup."""
    report = run_one(
        work_dir=tmp_path,
        n_left=2_000,
        n_lookup=100,
        context="DEV",
        how="left",
        match="first",
        timebox_s=120.0,
    )
    assert report.status == "success", report.error
    assert report.evidence.startswith("PROVEN Soft-PASS")
    assert report.rows_join_out == 2_000
    assert report.rows_dest_out == 2_000
    assert report.peak_rss_mb is not None and report.peak_rss_mb > 0
    out = tmp_path / "data/out/lookup_join_stress/dev/joined.csv"
    assert out.exists()
    assert report.join_key_resolved == "customer_id"
    assert "qa" not in report.out_path_resolved  # stayed on DEV


def test_job_context_path_substitution_dev_qa_prod(tmp_path: Path):
    result = prove_context_switch(tmp_path, n_left=400, n_lookup=40)
    assert result["ok"], result
    for name in ("DEV", "QA", "PROD"):
        block = result["contexts"][name]
        assert block["status"] == "success"
        assert block["out_exists"] is True
        assert block["rows_join_out"] == 400
        assert name.lower() in block["out_path"]


def _bench_enabled() -> bool:
    return os.environ.get("RUN_BENCH") == "1"


@pytest.mark.bench
def test_lookup_join_stress_100k_softpass(tmp_path: Path):
    """Heavy Soft-PASS scale — skipped unless RUN_BENCH=1."""
    if not _bench_enabled():
        pytest.skip("set RUN_BENCH=1 for Lookup Join 100k Soft-PASS")
    report = run_one(
        work_dir=tmp_path,
        n_left=100_000,
        n_lookup=5_000,
        context="QA",
        how="left",
        match="first",
        timebox_s=600.0,
    )
    assert report.status == "success", report.error
    assert report.rows_join_out == 100_000
    assert report.peak_rss_mb is not None and report.peak_rss_mb > 0
    print(
        f"\nLookupJoin Soft-PASS n_left=100000 n_lookup=5000 "
        f"elapsed_s={report.elapsed_s} peak_rss_mb={report.peak_rss_mb} "
        f"join_out={report.rows_join_out}",
        flush=True,
    )
