"""Integration: two sources → Lookup Join → Field Mapper (Variables) → file."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from formulaetl.engine.runner import PipelineRunner
from formulaetl.models.pipeline import PipelineDefinition

ROOT = Path(__file__).resolve().parents[2]


def test_lookup_join_mapper_demo(work_dir: Path):
    pipe_path = ROOT / "demos" / "lookup-join-mapper" / "pipeline.json"
    data = json.loads(pipe_path.read_text(encoding="utf-8"))
    # Point destination under isolated work_dir
    for n in data["nodes"]:
        if n["id"] == "dest":
            n["config"]["path"] = "data/out/lookup_join_mapper.csv"
    pipeline = PipelineDefinition.model_validate(data)

    runner = PipelineRunner(work_dir=work_dir, demo_mode=True)
    result = runner.run(pipeline)
    assert result.status == "success", result.error

    nm = result.node_metrics
    assert nm["join"]["rows_out"] > 0
    assert nm["field_mapper"]["rows_out"] == nm["join"]["rows_out"]
    assert nm["dest"]["rows_out"] == nm["field_mapper"]["rows_out"]

    out = work_dir / "data/out/lookup_join_mapper.csv"
    assert out.exists()
    with out.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) >= 10
    assert "full_name" in rows[0]
    assert "segment" in rows[0]
    assert "total" in rows[0]
    # Variable upper(customer_name) should produce uppercase
    assert rows[0]["full_name"] == rows[0]["full_name"].upper()
