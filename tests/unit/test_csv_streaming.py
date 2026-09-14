"""Phase C — serious CSV streaming / malformed / Unicode / scale tests."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from formulaetl.components.csv_parser import CSVParser
from formulaetl.sdk.context import RunContext
from formulaetl.sdk.data import CsvReadOptions, DatasetHandle, iter_csv_batches


def _ctx(work: Path, batch_size: int = 256) -> RunContext:
    return RunContext(
        run_id="csv-test",
        pipeline_id="csv-test",
        demo_mode=True,
        work_dir=work,
        data_dir=work / "data",
        batch_size=batch_size,
        log=lambda m: None,
    )


def test_csv_empty_file(tmp_path: Path):
    p = tmp_path / "empty.csv"
    p.write_text("a,b,c\n", encoding="utf-8")
    rejects: list = []
    ds = DatasetHandle.from_csv_path(p, batch_size=10, rejects_out=rejects)
    rows = ds.materialize()
    assert rows == []
    assert rejects == []


def test_csv_one_row(tmp_path: Path):
    p = tmp_path / "one.csv"
    p.write_text("id,name\n1,alpha\n", encoding="utf-8")
    rows = DatasetHandle.from_csv_path(p, add_row_numbers=True).materialize()
    assert len(rows) == 1
    assert rows[0]["name"] == "alpha"
    assert rows[0]["_row_number"] == 1


def test_csv_quoted_commas_and_multiline(tmp_path: Path):
    text = (
        "id,note\n"
        '1,"hello, world"\n'
        '2,"line1\nline2"\n'
        '3,"he said ""hi"""\n'
    )
    p = tmp_path / "quotes.csv"
    p.write_text(text, encoding="utf-8")
    rows = DatasetHandle.from_csv_path(p).materialize()
    assert len(rows) == 3
    assert rows[0]["note"] == "hello, world"
    assert "line1" in rows[1]["note"] and "line2" in rows[1]["note"]
    assert rows[2]["note"] == 'he said "hi"'


def test_csv_unicode(tmp_path: Path):
    p = tmp_path / "uni.csv"
    p.write_text("id,name\n1,日本語\n2,café\n3,emoji😀\n", encoding="utf-8")
    rows = DatasetHandle.from_csv_path(p).materialize()
    assert rows[0]["name"] == "日本語"
    assert rows[1]["name"] == "café"
    assert "😀" in rows[2]["name"]


def test_csv_nulls_and_empty_as_null(tmp_path: Path):
    p = tmp_path / "nulls.csv"
    p.write_text("id,name,flag\n1,,yes\n2,NULL,no\n3,ok,\n", encoding="utf-8")
    rows = DatasetHandle.from_csv_path(p, empty_as_null=True).materialize()
    assert rows[0]["name"] is None
    assert rows[1]["name"] is None
    assert rows[2]["flag"] is None
    assert rows[2]["name"] == "ok"


def test_csv_extra_and_missing_columns(tmp_path: Path):
    p = tmp_path / "cols.csv"
    p.write_text("a,b\n1,2,3\n4\n", encoding="utf-8")
    rejects: list = []
    # keep extras
    rows = DatasetHandle.from_csv_path(
        p, extra_columns="keep", missing_columns="fill", rejects_out=rejects
    ).materialize()
    assert len(rows) == 2
    assert rows[0].get("_extra_0") == "3"
    assert rows[1]["b"] is None

    rejects2: list = []
    rows2 = DatasetHandle.from_csv_path(
        p,
        extra_columns="reject",
        missing_columns="reject",
        malformed_policy="reject",
        rejects_out=rejects2,
    ).materialize()
    # first row extra → reject; second missing → reject
    assert rows2 == []
    assert len(rejects2) == 2


def test_csv_malformed_policy_fail(tmp_path: Path):
    p = tmp_path / "bad.csv"
    p.write_text("a,b\n1,2,3\n", encoding="utf-8")
    with pytest.raises(ValueError, match="malformed|extra"):
        DatasetHandle.from_csv_path(
            p, extra_columns="reject", malformed_policy="fail"
        ).materialize()


def test_csv_parser_rejects_stream(tmp_path: Path):
    p = tmp_path / "parse.csv"
    p.write_text("a,b\n1,2,3\nok,yes\n", encoding="utf-8")
    ctx = _ctx(tmp_path)
    result = CSVParser(
        {
            "path": str(p),
            "extra_columns": "reject",
            "malformed_policy": "reject",
            "add_row_numbers": True,
        }
    ).run(ctx)
    assert result.metrics.rows_out == 1
    assert result.metrics.rows_rejected == 1
    assert result.rows[0]["a"] == "ok"
    assert result.rejects[0]["_reject_reason"]
    assert result.rejects[0]["_row_number"] == 1


def test_csv_10k_chunked(tmp_path: Path):
    p = tmp_path / "10k.csv"
    with p.open("w", encoding="utf-8", newline="") as fh:
        fh.write("id,value\n")
        for i in range(10_000):
            fh.write(f"{i},v{i}\n")
    rejects: list = []
    ds = DatasetHandle.from_csv_path(p, batch_size=500, rejects_out=rejects)
    batches = list(ds.iter_batches())
    assert sum(len(b) for b in batches) == 10_000
    assert batches[-1].eof is True
    assert max(len(b) for b in batches) <= 500
    assert rejects == []
    # Rematerialize via fresh handle (iter_batches caches)
    assert len(ds.materialize()) == 10_000


def test_csv_10k_parser_component(tmp_path: Path):
    p = tmp_path / "10k_comp.csv"
    with p.open("w", encoding="utf-8", newline="") as fh:
        fh.write("id,value\n")
        for i in range(10_000):
            fh.write(f"{i},v{i}\n")
    ctx = _ctx(tmp_path, batch_size=1024)
    t0 = time.perf_counter()
    result = CSVParser({"path": str(p), "add_row_numbers": False}).run(ctx)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert result.metrics.rows_out == 10_000
    assert result.rows[0]["id"] == "0"
    assert result.rows[-1]["id"] == "9999"
    # Soft budget — CI machines vary; record in evidence separately.
    assert elapsed_ms < 30_000


@pytest.mark.slow
def test_csv_1m_benchmark(tmp_path: Path):
    """Optional 1M-row soak — skipped unless RUN_CSV_1M=1 (memory/time)."""
    import os

    if os.environ.get("RUN_CSV_1M") != "1":
        pytest.skip("set RUN_CSV_1M=1 to run 1M-row CSV benchmark")
    p = tmp_path / "1m.csv"
    n = 1_000_000
    with p.open("w", encoding="utf-8", newline="") as fh:
        fh.write("id,value\n")
        for i in range(n):
            fh.write(f"{i},v{i}\n")
    t0 = time.perf_counter()
    count = 0
    peak_batch = 0
    for batch in iter_csv_batches(
        p, batch_size=5000, options=CsvReadOptions(add_row_numbers=False)
    ):
        count += len(batch.rows)
        peak_batch = max(peak_batch, len(batch.rows))
        # Drop batch promptly — do not accumulate
    elapsed = time.perf_counter() - t0
    assert count == n
    assert peak_batch <= 5000
    # Write a small artifact for evidence collectors
    evidence = tmp_path / "csv_1m_bench.txt"
    evidence.write_text(
        f"rows={count} elapsed_s={elapsed:.3f} peak_batch={peak_batch}\n",
        encoding="utf-8",
    )


def test_csv_delimiter_tab(tmp_path: Path):
    p = tmp_path / "tsv.csv"
    p.write_text("a\tb\n1\t2\n", encoding="utf-8")
    rows = DatasetHandle.from_csv_path(p, delimiter="\t").materialize()
    assert rows[0] == {"a": "1", "b": "2"}


def test_csv_no_header_fieldnames(tmp_path: Path):
    p = tmp_path / "nh.csv"
    p.write_text("1,alpha\n2,beta\n", encoding="utf-8")
    rows = DatasetHandle.from_csv_path(
        p, has_header=False, fieldnames=["id", "name"]
    ).materialize()
    assert rows[0]["name"] == "alpha"
