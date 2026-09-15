"""Unit tests: Master / Child context merge, cycle/depth, ${child.*}."""

from __future__ import annotations

from pathlib import Path

import pytest

from formulaetl.engine.nesting import (
    PipelineNestingError,
    check_nesting,
    merge_child_metadata,
    max_pipeline_depth,
)
from formulaetl.engine.runner import PipelineRunner
from formulaetl.models.pipeline import PipelineDefinition
from formulaetl.sdk.vars import VarScope, resolve_string


def test_merge_inherit_uses_master_active_and_overlays_values():
    master = {
        "contexts": {
            "active": "QA",
            "sets": {
                "QA": {"env": "qa", "catalog": "qa_main", "shared": "from_master"},
                "DEV": {"env": "dev"},
            },
        },
        "run_params": {"run_date": "2026-09-14", "job_name": "master"},
    }
    child = {
        "contexts": {
            "active": "DEV",
            "sets": {
                "QA": {"env": "child_qa", "local_only": "child"},
                "DEV": {"env": "dev"},
            },
        },
        "run_params": {"job_name": "child_default"},
    }
    merged = merge_child_metadata(
        master_metadata=master,
        child_metadata=child,
        context_mode="inherit",
        run_params={"extra": "1"},
    )
    assert merged["contexts"]["active"] == "QA"
    qa = merged["contexts"]["sets"]["QA"]
    assert qa["env"] == "qa"  # master overlays child
    assert qa["catalog"] == "qa_main"
    assert qa["local_only"] == "child"
    assert qa["shared"] == "from_master"
    assert merged["run_params"]["run_date"] == "2026-09-14"
    assert merged["run_params"]["job_name"] == "master"  # master then node params
    assert merged["run_params"]["extra"] == "1"


def test_merge_child_active_keeps_child_set(monkeypatch):
    monkeypatch.delenv("FORMULAETL_CONTEXT", raising=False)
    master = {
        "contexts": {
            "active": "QA",
            "sets": {"QA": {"env": "qa"}, "DEV": {"env": "dev"}},
        }
    }
    child = {
        "contexts": {
            "active": "DEV",
            "sets": {"DEV": {"env": "dev", "catalog": "sandbox"}, "QA": {"env": "qa"}},
        }
    }
    merged = merge_child_metadata(
        master_metadata=master,
        child_metadata=child,
        context_mode="child_active",
    )
    assert merged["contexts"]["active"] == "DEV"
    assert merged["contexts"]["sets"]["DEV"]["catalog"] == "sandbox"


def test_merge_override_requires_name_and_merges():
    master = {
        "contexts": {
            "active": "DEV",
            "sets": {"PROD": {"env": "prod", "catalog": "main"}, "DEV": {"env": "dev"}},
        }
    }
    child = {
        "contexts": {
            "active": "DEV",
            "sets": {"PROD": {"env": "child_prod"}, "DEV": {"env": "dev"}},
        }
    }
    with pytest.raises(PipelineNestingError, match="context_name"):
        merge_child_metadata(
            master_metadata=master,
            child_metadata=child,
            context_mode="override",
            context_name="",
        )
    merged = merge_child_metadata(
        master_metadata=master,
        child_metadata=child,
        context_mode="override",
        context_name="PROD",
    )
    assert merged["contexts"]["active"] == "PROD"
    assert merged["contexts"]["sets"]["PROD"]["env"] == "prod"
    assert merged["contexts"]["sets"]["PROD"]["catalog"] == "main"


def test_secrets_keys_not_special_cased_in_merge_but_extract_skips():
    """Merge copies context values as-is; publish extraction strips secret-like keys."""
    from formulaetl.engine.nesting import extract_publish
    from formulaetl.models.pipeline import PipelineDefinition

    class FakeResult:
        status = "success"
        run_id = "r1"
        pipeline_id = "c1"
        error = None
        duration_ms = 1.0
        metrics = {"rows_in": 0, "rows_out": 2, "rows_rejected": 0}

    child = PipelineDefinition(id="c1", name="c", metadata={"publish": {"ok": True}})
    pub = extract_publish(
        child_pipeline=child,
        child_result=FakeResult(),
        publish_as="ingest",
        active_context="QA",
        context_values={"env": "qa", "token": "SECRET", "password": "x"},
    )
    assert pub["env"] == "qa"
    assert "token" not in pub
    assert "password" not in pub
    assert pub["ok"] is True


def test_cycle_detection():
    with pytest.raises(PipelineNestingError, match="cycle"):
        check_nesting(["master", "child-a"], "master")
    check_nesting(["master"], "child-a")  # ok


def test_depth_limit(monkeypatch):
    monkeypatch.setenv("FORMULAETL_PIPELINE_MAX_DEPTH", "2")
    assert max_pipeline_depth() == 2
    check_nesting(["master"], "child")  # depth 2 ok
    with pytest.raises(PipelineNestingError, match="depth"):
        check_nesting(["master", "child"], "grandchild")


def test_child_var_lookup():
    scope = VarScope(
        children={"ingest": {"rows_out": 17, "stage": "ingest"}},
    )
    assert resolve_string("rows=${child.ingest.rows_out}", scope) == "rows=17"
    assert resolve_string("${child.ingest.stage}", scope) == "ingest"
    assert resolve_string("${child.missing.x}", scope) == "${child.missing.x}"


def test_nested_run_pipeline_component(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FORMULAETL_DEMO", "1")
    monkeypatch.delenv("FORMULAETL_CONTEXT", raising=False)
    child = {
        "id": "unit-child",
        "name": "Unit Child",
        "nodes": [
            {
                "id": "log",
                "type": "logger_metrics",
                "label": "Log",
                "config": {"label": "child"},
            }
        ],
        "edges": [],
        "metadata": {
            "publish": {"stage": "unit"},
            "contexts": {
                "active": "DEV",
                "sets": {
                    "DEV": {"env": "dev"},
                    "QA": {"env": "qa", "flag": "from_child"},
                },
            },
        },
    }
    child_path = tmp_path / "child.json"
    import json

    child_path.write_text(json.dumps(child), encoding="utf-8")

    master = PipelineDefinition.model_validate(
        {
            "id": "unit-master",
            "name": "Unit Master",
            "nodes": [
                {
                    "id": "rp",
                    "type": "run_pipeline",
                    "label": "Run Pipeline",
                    "config": {
                        "pipeline_id": str(child_path),
                        "context_mode": "inherit",
                        "publish_as": "ingest",
                    },
                }
            ],
            "edges": [],
            "metadata": {
                "contexts": {
                    "active": "QA",
                    "sets": {"QA": {"env": "qa", "catalog": "qa_main"}},
                }
            },
        }
    )
    result = PipelineRunner(work_dir=tmp_path, demo_mode=True).run(master)
    assert result.status == "success", result.error
    children = (result.metrics or {}).get("children") or {}
    assert "ingest" in children
    assert children["ingest"]["status"] == "success"
    assert children["ingest"]["stage"] == "unit"
    assert children["ingest"]["env"] == "qa"
    assert children["ingest"]["catalog"] == "qa_main"


def test_self_cycle_via_run_pipeline(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FORMULAETL_DEMO", "1")
    import json

    # Pipeline that runs itself
    path = tmp_path / "loop.json"
    data = {
        "id": "loop-pipe",
        "name": "Loop",
        "nodes": [
            {
                "id": "rp",
                "type": "run_pipeline",
                "config": {"pipeline_id": str(path), "publish_as": "x"},
            }
        ],
        "edges": [],
        "metadata": {},
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    pipeline = PipelineDefinition.model_validate(data)
    result = PipelineRunner(work_dir=tmp_path, demo_mode=True).run(pipeline)
    assert result.status == "failed"
    assert result.error and "cycle" in result.error.lower()
