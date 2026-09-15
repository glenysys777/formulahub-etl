"""Always-on integration: Job Context ${…} paths through Lookup Join (small N)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from formulaetl.engine.runner import PipelineRunner
from formulaetl.models.pipeline import PipelineDefinition

from scripts.lookup_join_stress import build_pipeline, generate_csvs

ROOT = Path(__file__).resolve().parents[2]


def test_lookup_join_contexts_demo_pipeline(work_dir: Path, monkeypatch):
    generate_csvs(work_dir, n_left=300, n_lookup=30)
    data = json.loads(
        (ROOT / "demos" / "lookup-join-contexts" / "pipeline.json").read_text(
            encoding="utf-8"
        )
    )
    # Force QA via env (Studio active-context override path)
    monkeypatch.setenv("FORMULAETL_CONTEXT", "QA")
    data["metadata"]["contexts"]["active"] = "DEV"  # env must win
    pipeline = PipelineDefinition.model_validate(data)

    runner = PipelineRunner(work_dir=work_dir, demo_mode=True)
    result = runner.run(pipeline)
    assert result.status == "success", result.error

    nm = result.node_metrics
    assert nm["join"]["rows_out"] == 300
    assert nm["dest"]["rows_out"] == 300

    qa_out = work_dir / "data/out/lookup_join_stress/qa/joined.csv"
    dev_out = work_dir / "data/out/lookup_join_stress/dev/joined.csv"
    assert qa_out.exists()
    assert not dev_out.exists()

    with qa_out.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 300
    assert "segment" in rows[0]
    assert "region" in rows[0]


def test_builder_pipeline_prod_context(work_dir: Path, monkeypatch):
    generate_csvs(work_dir, n_left=150, n_lookup=25)
    monkeypatch.setenv("FORMULAETL_CONTEXT", "PROD")
    pipe = build_pipeline(active="DEV")
    pipeline = PipelineDefinition.model_validate(pipe)
    result = PipelineRunner(work_dir=work_dir, demo_mode=True).run(pipeline)
    assert result.status == "success", result.error
    assert (work_dir / "data/out/lookup_join_stress/prod/joined.csv").exists()
