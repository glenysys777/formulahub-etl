"""Unit tests for Job Contexts / ${…} variable resolution + Databricks SQL."""

from __future__ import annotations

import json
from pathlib import Path

from formulaetl.components.databricks_job import DatabricksJob
from formulaetl.components.databricks_sql import DatabricksSQL
from formulaetl.sdk.context import RunContext
from formulaetl.sdk.registry import list_components
from formulaetl.sdk.vars import (
    build_scope,
    find_refs,
    parse_contexts,
    preview_refs,
    resolve_map_values,
    resolve_string,
)


def ctx(work: Path, **kwargs) -> RunContext:
    base = dict(
        run_id="test-run",
        pipeline_id="test-pipe",
        demo_mode=True,
        work_dir=work,
        data_dir=work / "data",
        log=lambda m: None,
    )
    base.update(kwargs)
    return RunContext(**base)


def test_find_refs_and_namespaces():
    text = "SELECT '${run_date}', '${context.env}', '${env.HOME}', '${upstream.x}', '${plain}'"
    assert find_refs(text) == [
        "run_date",
        "context.env",
        "env.HOME",
        "upstream.x",
        "plain",
    ]


def test_resolve_string_context_run_upstream_env(monkeypatch):
    monkeypatch.setenv("FORMULAETL_UNIT_FLAG", "from-env")
    scope = build_scope(
        run_id="r1",
        pipeline_id="p1",
        metadata={
            "run_params": {"run_date": "2026-09-14"},
            "contexts": {
                "active": "DEV",
                "sets": {
                    "DEV": {"env": "dev", "catalog": "sandbox"},
                    "PROD": {"env": "prod", "catalog": "main"},
                },
            },
        },
        upstream_row={"channel": "api", "order_id": 7},
        env={"FORMULAETL_UNIT_FLAG": "from-env"},
    )
    sql = (
        "INSERT INTO ${context.catalog}.t "
        "SELECT ${upstream.order_id} WHERE d='${run_date}' "
        "AND e='${context.env}' AND f='${env.FORMULAETL_UNIT_FLAG}' AND c='${upstream.channel}'"
    )
    out = resolve_string(sql, scope)
    assert "sandbox.t" in out
    assert "2026-09-14" in out
    assert "env='dev'" in out or "e='dev'" in out
    assert "from-env" in out
    assert "api" in out
    assert "7" in out


def test_plain_key_does_not_read_bare_env(monkeypatch):
    monkeypatch.setenv("SECRET_LEAK", "nope")
    scope = build_scope(
        run_id="r1",
        pipeline_id="p1",
        metadata={"contexts": {"active": "DEV", "sets": {"DEV": {"env": "dev"}}}},
        env={"SECRET_LEAK": "nope"},
    )
    # Bare ${SECRET_LEAK} must NOT pull from env
    assert resolve_string("x=${SECRET_LEAK}", scope) == "x=${SECRET_LEAK}"
    assert resolve_string("x=${env.SECRET_LEAK}", scope) == "x=nope"


def test_formulahub_context_env_override(monkeypatch):
    monkeypatch.setenv("FORMULAETL_CONTEXT", "PROD")
    active, sets = parse_contexts(
        {
            "contexts": {
                "active": "DEV",
                "sets": {
                    "DEV": {"env": "dev"},
                    "PROD": {"env": "prod"},
                },
            }
        }
    )
    assert active == "PROD"
    scope = build_scope(
        run_id="r",
        pipeline_id="p",
        metadata={
            "contexts": {
                "active": "DEV",
                "sets": {"DEV": {"env": "dev"}, "PROD": {"env": "prod"}},
            }
        },
    )
    assert scope.active_context == "PROD"
    assert resolve_string("${context.env}", scope) == "prod"


def test_preview_refs_table():
    scope = build_scope(
        run_id="r",
        pipeline_id="p",
        metadata={
            "run_params": {"run_date": "2026-01-02"},
            "contexts": {"active": "QA", "sets": {"QA": {"env": "qa"}}},
        },
    )
    rows = preview_refs("dt=${run_date} e=${context.env} missing=${nope}", scope)
    by = {r["key"]: r for r in rows}
    assert by["run_date"]["value"] == "2026-01-02"
    assert by["run_date"]["source"] == "params" or by["run_date"]["source"] == "run"
    assert by["context.env"]["value"] == "qa"
    assert by["nope"]["source"] == "unresolved"


def test_resolve_map_values_for_notebook_params():
    scope = build_scope(
        run_id="r",
        pipeline_id="p",
        metadata={
            "contexts": {"active": "DEV", "sets": {"DEV": {"env": "dev"}}},
            "run_params": {"run_date": "2026-09-14"},
        },
    )
    out = resolve_map_values(
        {"source": "api", "env": "${context.env}", "dt": "${run_date}"},
        scope,
    )
    assert out == {"source": "api", "env": "dev", "dt": "2026-09-14"}


def test_databricks_sql_registered():
    by = {c["type"]: c for c in list_components()}
    assert "databricks_sql" in by
    keys = {p["key"] for p in by["databricks_sql"]["parameters"]}
    assert {"workspace_host", "warehouse_id", "sql", "token", "demo"}.issubset(keys)


def test_databricks_sql_demo_sidecar(work_dir: Path):
    from formulaetl.sdk.vars import bind_pipeline_variables
    from formulaetl.models.pipeline import PipelineDefinition

    pipeline = PipelineDefinition.model_validate(
        {
            "id": "t",
            "name": "t",
            "nodes": [],
            "edges": [],
            "metadata": {
                "run_params": {"run_date": "2026-09-14"},
                "contexts": {
                    "active": "DEV",
                    "sets": {"DEV": {"env": "dev", "catalog": "sandbox"}},
                },
            },
        }
    )
    cctx = ctx(work_dir)
    bind_pipeline_variables(cctx, pipeline)

    sql_tmpl = (
        "SELECT * FROM ${context.catalog}.orders "
        "WHERE dt='${run_date}' AND env='${context.env}' AND ch='${upstream.channel}'"
    )
    component = DatabricksSQL(
        {
            "workspace_host": "demo",
            "warehouse_id": "wh-1",
            "sql": sql_tmpl,
            "demo": True,
            "demo_output_dir": "data/out/databricks_sql_demo",
        }
    )
    rows = [{"channel": "web", "order_id": 1}]
    result = component.run(cctx, rows)
    assert result.side_effects["mode"] == "demo"
    assert result.side_effects["state"] == "SUCCEEDED"
    resolved = result.side_effects["sql_resolved"]
    assert "sandbox.orders" in resolved
    assert "2026-09-14" in resolved
    assert "env='dev'" in resolved
    assert "ch='web'" in resolved
    sidecar = Path(result.side_effects["sidecar"])
    assert sidecar.exists()
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    assert meta["mode"] == "demo"
    assert meta["sql_resolved"] == resolved
    assert "DEMO" in meta["note"] or "demo" in meta["note"].lower()
    assert "UNPROVEN" in meta["note"]


def test_databricks_job_resolves_notebook_params(work_dir: Path):
    from formulaetl.sdk.vars import bind_pipeline_variables
    from formulaetl.models.pipeline import PipelineDefinition

    pipeline = PipelineDefinition.model_validate(
        {
            "id": "t",
            "name": "t",
            "nodes": [],
            "edges": [],
            "metadata": {
                "contexts": {
                    "active": "QA",
                    "sets": {"QA": {"env": "qa"}},
                },
                "run_params": {"run_date": "2026-09-01"},
            },
        }
    )
    cctx = ctx(work_dir)
    bind_pipeline_variables(cctx, pipeline)
    component = DatabricksJob(
        {
            "workspace_host": "demo",
            "job_id": "55",
            "notebook_params": [
                "source=test",
                "env=${context.env}",
                "dt=${run_date}",
            ],
            "demo": True,
            "demo_output_dir": "data/out/databricks_demo",
        }
    )
    result = component.run(cctx, [{"x": 1}])
    meta = json.loads(Path(result.side_effects["sidecar"]).read_text(encoding="utf-8"))
    assert meta["notebook_params"]["env"] == "qa"
    assert meta["notebook_params"]["dt"] == "2026-09-01"
