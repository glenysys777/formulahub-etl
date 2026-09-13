"""Integration test: Excel → Column Map → Transform → Validate → CSV + Excel."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from formulaetl.engine.runner import PipelineRunner
from formulaetl.models.pipeline import PipelineDefinition

ROOT = Path(__file__).resolve().parents[2]


def test_excel_to_file_pipeline(work_dir: Path):
    pipeline_path = ROOT / "demos" / "excel-to-file" / "pipeline.json"
    data = json.loads(pipeline_path.read_text(encoding="utf-8"))
    pipeline = PipelineDefinition.model_validate(data)

    runner = PipelineRunner(work_dir=work_dir, demo_mode=True)
    result = runner.run(pipeline)

    assert result.status == "success", result.error
    assert result.error is None

    nm = result.node_metrics
    assert nm["excel"]["rows_out"] == 8
    assert nm["map"]["rows_out"] == 8
    assert nm["transform"]["rows_out"] == 8
    assert nm["validate"]["rows_out"] == 8
    assert nm["validate"]["rows_rejected"] == 0
    assert nm["dest_csv"]["rows_out"] == 8
    assert nm["dest_xlsx"]["rows_out"] == 8

    out = work_dir / "data/out/excel_orders.csv"
    assert out.exists()
    with out.open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 8
    assert "order_id" in rows[0]
    assert "Order ID" not in rows[0]
    assert rows[0].get("loaded_by") == "formulaetl"
    for row in rows:
        assert len(row["order_date"]) == 10
        assert row["order_date"][4] == "-"

    xlsx = work_dir / "data/out/excel_orders.xlsx"
    assert xlsx.exists()
