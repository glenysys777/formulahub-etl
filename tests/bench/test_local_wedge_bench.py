"""LOCAL/DEMO wedge bench — correctness always; scale gated by RUN_BENCH=1.

Heavy scales (10K / 100K / 1M) are marked ``bench`` so default CI stays fast.
Never claims LIVE_CLOUD.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.local_wedge_bench import (
    build_pipeline,
    plan_counts,
    reconcile,
    run_one,
    run_scales,
)

ROOT = Path(__file__).resolve().parents[2]


def test_plan_counts_reconcile():
    for n in (10, 100, 1_000, 10_000, 100_000, 1_000_000):
        plan = plan_counts(n)
        assert plan.n == plan.rejects + plan.dups + plan.loaded
        ok, _ = reconcile(
            n=plan.n, r=plan.rejects, d=plan.dups, l=plan.loaded
        )
        assert ok


def test_build_pipeline_shape_includes_dedupe():
    pipe = build_pipeline(
        source="s3",
        dest="snowflake",
        encrypted_rel="data/s3/demo/wedge_bench_100.csv.pgp",
        reject_rel="data/rejects/bench_rejects.csv",
        load_rel="data/out/bench_sf",
        archive_rel="data/archive/bench/",
    )
    types = [n["type"] for n in pipe["nodes"]]
    assert types == [
        "s3_source",
        "pgp_decrypt",
        "csv_parser",
        "schema_validate",
        "column_map",
        "dedupe",
        "snowflake_destination",
        "local_file_destination",
        "archive_files",
    ]
    assert pipe["metadata"]["classification"] == "LOCAL/DEMO"
    assert pipe["metadata"]["demo"] is True
    assert pipe["metadata"].get("live_wedge") is not True


def test_local_wedge_correctness_small(tmp_path: Path):
    """Always-on LOCAL/DEMO correctness (small N) — CI-safe."""
    # Copy keys into tmp work dir
    keys = ROOT / "fixtures" / "keys"
    dst = tmp_path / "fixtures" / "keys"
    dst.mkdir(parents=True)
    for name in ("demo_private.asc", "demo_public.asc"):
        (dst / name).write_bytes((keys / name).read_bytes())

    result = run_one(work_dir=tmp_path, n=200, source="s3", dest="snowflake")
    assert result.classification == "LOCAL/DEMO"
    assert result.status == "success", result.error
    assert result.reconcile_ok, result.reconcile_equation
    assert result.input_n == 200
    assert result.input_n == result.rejected_r + result.deduped_d + result.loaded_l
    assert result.evidence == "PROVEN"


def test_local_wedge_file_to_file_small(tmp_path: Path):
    keys = ROOT / "fixtures" / "keys"
    dst = tmp_path / "fixtures" / "keys"
    dst.mkdir(parents=True)
    for name in ("demo_private.asc", "demo_public.asc"):
        (dst / name).write_bytes((keys / name).read_bytes())

    result = run_one(work_dir=tmp_path, n=50, source="file", dest="file")
    assert result.status == "success", result.error
    assert result.reconcile_ok, result.reconcile_equation
    loaded = tmp_path / "data" / "out" / "bench_50_file" / "loaded.csv"
    assert loaded.exists()


def _bench_enabled() -> bool:
    return os.environ.get("RUN_BENCH") == "1"


def _prepare_keys(tmp_path: Path) -> None:
    keys = ROOT / "fixtures" / "keys"
    dst = tmp_path / "fixtures" / "keys"
    dst.mkdir(parents=True)
    for name in ("demo_private.asc", "demo_public.asc"):
        (dst / name).write_bytes((keys / name).read_bytes())


@pytest.mark.bench
@pytest.mark.parametrize("n", [10_000, 100_000, 1_000_000])
def test_local_wedge_scale_bench(tmp_path: Path, n: int):
    """Heavy LOCAL/DEMO scales — skipped unless RUN_BENCH=1."""
    if not _bench_enabled():
        pytest.skip("set RUN_BENCH=1 to run LOCAL/DEMO wedge scale benches")
    _prepare_keys(tmp_path)
    # Soft timeboxes (wall) — CI machines vary; fail loudly if absurdly slow.
    timebox = {10_000: 120.0, 100_000: 600.0, 1_000_000: 1800.0}[n]
    result = run_one(
        work_dir=tmp_path,
        n=n,
        source="s3",
        dest="snowflake",
        timebox_s=timebox,
    )
    assert result.status == "success", (
        f"scale={n} error={result.error} eq={result.reconcile_equation}"
    )
    assert result.reconcile_ok, result.reconcile_equation
    assert result.input_n == n
    assert result.peak_rss_mb is not None and result.peak_rss_mb > 0
    assert result.rows_per_sec > 0
    # Emit one-line summary for evidence collectors / pytest -s
    print(
        f"\nLOCAL/DEMO bench n={n} elapsed_s={result.elapsed_s} "
        f"rows_per_sec={result.rows_per_sec} peak_rss_mb={result.peak_rss_mb} "
        f"{result.reconcile_equation}",
        flush=True,
    )


@pytest.mark.bench
def test_local_wedge_10m_optional(tmp_path: Path):
    """Optional 10M — requires RUN_BENCH=1 and BENCH_INCLUDE_10M=1."""
    if not _bench_enabled():
        pytest.skip("set RUN_BENCH=1 to run LOCAL/DEMO wedge scale benches")
    if os.environ.get("BENCH_INCLUDE_10M") != "1":
        pytest.skip("set BENCH_INCLUDE_10M=1 for optional 10M (memory/time)")
    _prepare_keys(tmp_path)
    result = run_one(
        work_dir=tmp_path,
        n=10_000_000,
        source="s3",
        dest="snowflake",
        timebox_s=3600.0,
    )
    assert result.status == "success", result.error
    assert result.reconcile_ok, result.reconcile_equation


@pytest.mark.bench
def test_run_scales_helper_gated():
    """Ensure run_scales path stays LOCAL/DEMO labeled."""
    if not _bench_enabled():
        pytest.skip("set RUN_BENCH=1")
    # Tiny multi-scale via helper (still gated) — uses repo ROOT work dir subfolder
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        keys = ROOT / "fixtures" / "keys"
        dst = work / "fixtures" / "keys"
        dst.mkdir(parents=True)
        for name in ("demo_private.asc", "demo_public.asc"):
            (dst / name).write_bytes((keys / name).read_bytes())
        payload = run_scales([100], work_dir=work, source="s3", dest="snowflake")
        assert payload["classification"] == "LOCAL/DEMO"
        assert payload["evidence"] == "PROVEN"
