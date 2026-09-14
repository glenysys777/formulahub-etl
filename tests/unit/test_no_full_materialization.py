"""Regression: large intermediates must not force full list[dict] materialization."""

from __future__ import annotations

from pathlib import Path

import pytest

from formulaetl.sdk.adapter import run_batched
from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.capabilities import ROWWISE
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext
from formulaetl.sdk.data import DatasetHandle
from formulaetl.sdk.spill import SPILL_THRESHOLD


class _Identity(BaseComponent):
    component_type = "identity_mat_guard"
    capabilities = ROWWISE

    def run(self, ctx, rows=None):
        rows = rows or []
        return ComponentResult(
            rows=list(rows),
            metrics=Metrics(rows_in=len(rows), rows_out=len(rows)),
        )


def test_run_batched_does_not_materialize_large_output(tmp_path: Path, monkeypatch):
    """Guardrail: lazy/spill path keeps ComponentResult.rows empty above threshold."""
    monkeypatch.setenv("FORMULAETL_STREAM_SPILL", "1")
    monkeypatch.setenv("FORMULAETL_SPILL_THRESHOLD", "100")
    import formulaetl.sdk.spill as spill_mod
    import formulaetl.sdk.adapter as adapter_mod

    monkeypatch.setattr(spill_mod, "SPILL_THRESHOLD", 100)
    monkeypatch.setattr(adapter_mod, "SPILL_THRESHOLD", 100)

    n = 500
    rows = [{"id": str(i), "v": i} for i in range(n)]
    ds = DatasetHandle.from_rows(rows, batch_size=50)
    ctx = RunContext(
        run_id="mat-guard",
        pipeline_id="mat-guard",
        demo_mode=True,
        work_dir=tmp_path,
        data_dir=tmp_path / "data",
        log=lambda m: None,
        batch_size=50,
    )
    result = run_batched(_Identity({}), ctx, ds, batch_size=50)
    assert result.dataset is not None
    # Must not hold the full working set on the result adapter list.
    assert len(result.rows) == 0
    # Pull the lazy chain — completeness without materializing onto result.rows.
    assert sum(len(b) for b in result.dataset.iter_batches(50)) == n
    from formulaetl.sdk.adapter import harvest_lazy_metrics

    harvest_lazy_metrics(result)
    assert result.metrics.rows_out == n
    assert result.metrics.extras.get("lazy") is True or result.metrics.extras.get("spill") is True
    assert len(result.rows) == 0


def test_dataset_iter_batches_does_not_auto_cache(tmp_path: Path):
    csv_path = tmp_path / "x.csv"
    csv_path.write_text("id\n1\n2\n3\n", encoding="utf-8")
    ds = DatasetHandle.from_csv_path(csv_path, batch_size=2)
    first = list(ds.iter_batches())
    assert sum(len(b) for b in first) == 3
    assert ds.is_materialized is False
    second = list(ds.iter_batches())
    assert sum(len(b) for b in second) == 3


def test_spill_threshold_env_is_positive():
    assert SPILL_THRESHOLD > 0


@pytest.mark.parametrize("n", [10, 200])
def test_csv_parser_large_keeps_rows_bounded(tmp_path: Path, monkeypatch, n: int):
    monkeypatch.setenv("FORMULAETL_SPILL_THRESHOLD", "50")
    import formulaetl.sdk.spill as spill_mod
    from formulaetl.components.csv_parser import CSVParser

    monkeypatch.setattr(spill_mod, "SPILL_THRESHOLD", 50)
    # Also patch the name imported into csv_parser
    import formulaetl.components.csv_parser as csv_mod

    monkeypatch.setattr(csv_mod, "SPILL_THRESHOLD", 50)

    p = tmp_path / "rows.csv"
    with p.open("w", encoding="utf-8") as fh:
        fh.write("id,name\n")
        for i in range(n):
            fh.write(f"{i},n{i}\n")
    ctx = RunContext(
        run_id="csv-bound",
        pipeline_id="csv-bound",
        demo_mode=True,
        work_dir=tmp_path,
        data_dir=tmp_path / "data",
        log=lambda m: None,
        batch_size=25,
    )
    result = CSVParser({"path": str(p)}).run(ctx)
    assert result.metrics.rows_out == n
    if n > 50:
        assert len(result.rows) <= 5
        assert result.dataset is not None
        assert sum(len(b) for b in result.dataset.iter_batches(25)) == n
    else:
        assert len(result.rows) == n
