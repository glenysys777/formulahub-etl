"""Integration: Excel → tMap → Filter → Sort → Aggregate → File."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from formulaetl.engine.runner import PipelineRunner
from formulaetl.models.pipeline import PipelineDefinition

ROOT = Path(__file__).resolve().parents[2]


def test_talend_core_path_pipeline(work_dir: Path):
    # Ensure excel fixture is present in isolated work_dir
    xlsx_src = ROOT / "fixtures/sample/orders.xlsx"
    xlsx_dst = work_dir / "fixtures/sample/orders.xlsx"
    xlsx_dst.parent.mkdir(parents=True, exist_ok=True)
    if not xlsx_dst.exists():
        xlsx_dst.write_bytes(xlsx_src.read_bytes())

    pipeline_path = ROOT / "demos" / "talend-core-path" / "pipeline.json"
    data = json.loads(pipeline_path.read_text(encoding="utf-8"))
    pipeline = PipelineDefinition.model_validate(data)

    runner = PipelineRunner(work_dir=work_dir, demo_mode=True)
    result = runner.run(pipeline)

    assert result.status == "success", result.error
    nm = result.node_metrics
    assert nm["excel"]["rows_out"] == 8
    assert nm["field_mapper"]["rows_out"] == 8
    assert nm["filter"]["rows_out"] == 5
    assert nm["sort"]["rows_out"] == 5
    assert nm["agg"]["rows_out"] == 1
    assert nm["dest"]["rows_out"] == 1

    out = work_dir / "data/out/core_agg.csv"
    assert out.exists()
    with out.open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["status"] == "shipped"
    assert float(rows[0]["sum_amount"]) > 0
    assert int(float(rows[0]["count"])) == 5


def test_python_row_flex_pipeline(work_dir: Path):
    pipeline_path = ROOT / "demos" / "python-row-flex" / "pipeline.json"
    data = json.loads(pipeline_path.read_text(encoding="utf-8"))
    pipeline = PipelineDefinition.model_validate(data)
    runner = PipelineRunner(work_dir=work_dir, demo_mode=True)
    result = runner.run(pipeline)
    assert result.status == "success", result.error
    assert result.node_metrics["py"]["rows_out"] == 12
    out = work_dir / "data/out/python_row_flex.csv"
    assert out.exists()
    with out.open() as f:
        rows = list(csv.DictReader(f))
    assert "line_total" in rows[0]
    assert "tax" in rows[0]
