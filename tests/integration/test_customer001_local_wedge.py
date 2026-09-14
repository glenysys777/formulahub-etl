"""Customer001 LOCAL wedge — reconciliation + optional local Postgres.

Classification:
  * Always-on path: LOCAL/DEMO (demo postgres mirror)
  * Optional path: LOCAL_PROVEN when LOCAL_POSTGRES_DSN reachable
  * Never LIVE_EXTERNAL
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts.customer001_local_wedge import (
    check_only,
    load_expected,
    postgres_env_ready,
    prepare_fixtures,
    reconcile,
    run_wedge,
)

ROOT = Path(__file__).resolve().parents[2]


def test_expected_counts_math():
    exp = load_expected()
    n, r, d, l = int(exp["N"]), int(exp["R"]), int(exp["D"]), int(exp["L"])
    ok, eq = reconcile(n, r, d, l)
    assert ok, eq
    assert (n, r, d, l) == (12, 2, 2, 8)


def test_pipeline_json_shape():
    pipe = json.loads(
        (ROOT / "demos" / "customer001-local-wedge" / "pipeline.json").read_text(
            encoding="utf-8"
        )
    )
    types = [n["type"] for n in pipe["nodes"]]
    assert types == [
        "local_file_source",
        "pgp_decrypt",
        "csv_parser",
        "schema_validate",
        "tmap",
        "lookup_join",
        "dedupe",
        "tmap",  # project → customers_wedge columns
        "logger_metrics",
        "postgres_destination",
        "local_file_destination",
        "archive_files",
    ]
    dest = next(n for n in pipe["nodes"] if n["id"] == "dest")
    assert dest["config"].get("database") == "formulahub_wedge"
    assert dest["config"].get("table") == "customers_wedge"
    assert pipe["metadata"].get("live_wedge") is not True
    assert pipe["metadata"]["classification"] in ("LOCAL_ONLY", "LOCAL/DEMO", "LOCAL_PROVEN")
    assert pipe["metadata"]["classification"] != "LIVE_EXTERNAL"


def test_check_only_never_live_external():
    report = check_only()
    assert report["classification"] == "LOCAL_ONLY"
    assert "SFTP" in report["honesty"] or "Snowflake" in report["honesty"]


def test_customer001_local_demo_reconcile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Always-on LOCAL/DEMO correctness — CI-safe."""
    monkeypatch.setenv("FORMULAETL_DEMO", "1")
    monkeypatch.setenv("FORMULAETL_WORK_DIR", str(tmp_path))
    prepare_fixtures(tmp_path)
    report = run_wedge(mode="demo", work_dir=tmp_path)
    assert report.status == "success", report.error
    assert report.classification == "LOCAL/DEMO"
    assert report.evidence == "PROVEN"
    assert report.reconcile_ok, report.reconcile_equation
    assert report.input_n == 12
    assert report.rejected_r == 2
    assert report.deduped_d == 2
    assert report.loaded_l == 8
    assert report.files_archived == 1
    assert report.bytes_in > 0
    assert (tmp_path / "data" / "rejects" / "customer001" / "orders_rejects.csv").exists()
    assert report.peak_rss_mb is not None and report.peak_rss_mb > 0
    assert report.node_timings_ms


def test_customer001_local_postgres_optional(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """LOCAL_PROVEN when Postgres is up; otherwise skip with LOCAL_ONLY marker."""
    ok, reason, _cfg = postgres_env_ready()
    if not ok:
        pytest.skip(f"LOCAL_ONLY — Postgres not available ({reason})")

    monkeypatch.setenv("FORMULAETL_DEMO", "0")
    monkeypatch.setenv("FORMULAETL_WORK_DIR", str(tmp_path))
    prepare_fixtures(tmp_path)
    report = run_wedge(mode="postgres", work_dir=tmp_path)
    assert report.status == "success", report.error
    assert report.classification == "LOCAL_PROVEN"
    assert report.evidence == "PROVEN"
    assert report.reconcile_ok, report.reconcile_equation
    assert report.loaded_l == 8
    assert any("postgres_count=8" in n for n in report.notes)
    # Honesty: never label as LIVE
    assert "LIVE" not in report.classification


def test_customer001_postgres_skip_marker(monkeypatch: pytest.MonkeyPatch):
    """Without DSN, postgres mode returns skipped LOCAL_ONLY — not a fake LIVE pass."""
    monkeypatch.delenv("LOCAL_POSTGRES_DSN", raising=False)
    monkeypatch.delenv("LIVE_POSTGRES_DSN", raising=False)
    monkeypatch.delenv("LOCAL_POSTGRES_HOST", raising=False)
    monkeypatch.delenv("PGHOST", raising=False)
    monkeypatch.setenv("FORMULAETL_DEMO", "0")
    report = run_wedge(mode="postgres", work_dir=ROOT)
    assert report.status == "skipped"
    assert report.classification == "LOCAL_ONLY"
    assert report.evidence == "UNPROVEN"
