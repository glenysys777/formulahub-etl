"""Run Pipeline — invoke a Child pipeline from a Master pipeline.

Display name: **Run Pipeline**. UI must never use competitor product names.
See ``docs/architecture/MASTER_CHILD_PIPELINES.md``.
"""

from __future__ import annotations

import uuid
from typing import Any

from formulaetl.engine.nesting import (
    CONTEXT_MODES,
    ON_FAILURE_MODES,
    PipelineNestingError,
    check_nesting,
    extract_publish,
    load_child_pipeline,
    merge_child_metadata,
)
from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.capabilities import BLOCKING_ROWS
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.registry import register
from formulaetl.sdk.vars import parse_contexts


@register
class RunPipeline(BaseComponent):
    """Orchestrate a Child pipeline inside a Master pipeline DAG."""

    component_type = "run_pipeline"
    display_name = "Run Pipeline"
    category = "orch"
    capabilities = BLOCKING_ROWS
    config_schema = {
        "type": "object",
        "required": ["pipeline_id"],
        "properties": {
            "pipeline_id": {
                "type": "string",
                "description": "Child pipeline id or relative JSON path",
            },
            "context_mode": {
                "type": "string",
                "enum": ["inherit", "child_active", "override"],
                "default": "inherit",
            },
            "context_name": {
                "type": "string",
                "description": "Context set name when context_mode=override",
            },
            "run_params": {
                "type": "object",
                "description": "Extra run params for this child invocation",
            },
            "publish_as": {
                "type": "string",
                "description": "Key under master children[publish_as]",
            },
            "on_failure": {
                "type": "string",
                "enum": ["fail_master", "continue"],
                "default": "fail_master",
            },
            "pass_rows": {
                "type": "boolean",
                "default": False,
                "description": "Passthrough input rows as this node output after child succeeds",
            },
        },
    }
    parameters = [
        {
            "key": "pipeline_id",
            "label": "Child pipeline",
            "type": "string",
            "required": True,
            "help": "Pipeline id from the library, or a relative path to a pipeline JSON for CLI/demo",
            "placeholder": "child-ingest",
        },
        {
            "key": "context_mode",
            "label": "Context mode",
            "type": "select",
            "required": False,
            "default": "inherit",
            "options": ["inherit", "child_active", "override"],
            "help": "inherit = use Master active Job Context name and merge values; "
            "child_active = Child’s own active context; override = use Context name below. "
            "Secrets are never inherited.",
        },
        {
            "key": "context_name",
            "label": "Context name",
            "type": "string",
            "required": False,
            "default": "",
            "help": "Required when Context mode is override (e.g. QA)",
            "placeholder": "QA",
        },
        {
            "key": "run_params",
            "label": "Run params",
            "type": "string",
            "required": False,
            "default": {},
            "help": "JSON object of extra run params for this Child (merged over Master run_params)",
        },
        {
            "key": "publish_as",
            "label": "Publish as",
            "type": "string",
            "required": False,
            "default": "",
            "help": "Name for ${child.<publish_as>.…} references in later Master nodes",
            "placeholder": "ingest",
        },
        {
            "key": "on_failure",
            "label": "On failure",
            "type": "select",
            "required": False,
            "default": "fail_master",
            "options": ["fail_master", "continue"],
            "help": "fail_master stops the Master; continue logs the Child failure and proceeds",
        },
        {
            "key": "pass_rows",
            "label": "Pass rows",
            "type": "boolean",
            "required": False,
            "default": False,
            "help": "When enabled, input rows are passed through as this node’s output after the Child succeeds",
        },
    ]

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            pipeline_id = str(self.config.get("pipeline_id") or "").strip()
            context_mode = str(self.config.get("context_mode") or "inherit").strip() or "inherit"
            context_name = str(self.config.get("context_name") or "").strip()
            on_failure = str(self.config.get("on_failure") or "fail_master").strip() or "fail_master"
            pass_rows = bool(self.config.get("pass_rows"))
            publish_as = str(self.config.get("publish_as") or "").strip()
            raw_rp = self.config.get("run_params") or {}
            if isinstance(raw_rp, str):
                import json

                raw_rp = json.loads(raw_rp) if raw_rp.strip() else {}
            if not isinstance(raw_rp, dict):
                raise ValueError("run_pipeline: run_params must be a JSON object")

            if context_mode not in CONTEXT_MODES:
                raise ValueError(
                    f"run_pipeline: invalid context_mode '{context_mode}'"
                )
            if on_failure not in ON_FAILURE_MODES:
                raise ValueError(
                    f"run_pipeline: invalid on_failure '{on_failure}'"
                )

            stack = list(ctx.pipeline_stack or [ctx.pipeline_id])
            check_nesting(stack, pipeline_id)

            child_def = load_child_pipeline(
                pipeline_id,
                work_dir=ctx.work_dir,
                get_pipeline=ctx.get_pipeline,
            )
            # Also guard against cycles via resolved pipeline id (path ≠ id)
            if child_def.id != pipeline_id:
                check_nesting(stack, child_def.id)
            if not publish_as:
                publish_as = child_def.id or pipeline_id

            master_meta = ctx.variables.get("_pipeline_metadata") or {}
            if not isinstance(master_meta, dict):
                master_meta = {}
            children_so_far = ctx.variables.get("children") or {}
            if not isinstance(children_so_far, dict):
                children_so_far = {}

            child_meta = merge_child_metadata(
                master_metadata=master_meta,
                child_metadata=child_def.metadata,
                context_mode=context_mode,
                context_name=context_name,
                run_params=raw_rp,
                child_publishes=children_so_far,
            )
            # Pydantic model — copy with merged metadata
            child_def = child_def.model_copy(update={"metadata": child_meta})

            child_run_id = str(uuid.uuid4())
            master_node_id = str(ctx.variables.get("_current_node_id") or "")

            # Optional durable child run record
            if ctx.record_child_run is not None:
                try:
                    ctx.record_child_run(
                        run_id=child_run_id,
                        pipeline_id=child_def.id,
                        parent_run_id=ctx.run_id,
                        master_node_id=master_node_id or None,
                    )
                except Exception as exc:  # noqa: BLE001 — never block orchestration on ledger
                    ctx.emit(f"run_pipeline: child run ledger skipped: {exc}")

            from formulaetl.engine.runner import PipelineRunner

            nested = PipelineRunner(
                work_dir=ctx.work_dir,
                demo_mode=ctx.demo_mode,
                batch_size=ctx.batch_size,
                secret_provider=ctx.secret_provider,
                get_connection=ctx.get_connection,
            )
            ctx.emit(
                f"Run Pipeline → child '{child_def.name}' ({child_def.id}) "
                f"mode={context_mode} publish_as={publish_as}"
            )
            child_result = nested.run(
                child_def,
                run_id=child_run_id,
                pipeline_stack=[*stack, child_def.id],
                get_pipeline=ctx.get_pipeline,
                record_child_run=ctx.record_child_run,
                parent_run_id=ctx.run_id,
                master_node_id=master_node_id or None,
            )

            if ctx.complete_child_run is not None:
                try:
                    ctx.complete_child_run(child_result)
                except Exception as exc:  # noqa: BLE001
                    ctx.emit(f"run_pipeline: child run complete skipped: {exc}")

            active, _sets = parse_contexts(child_meta)
            ctx_vals = {}
            block = child_meta.get("contexts") if isinstance(child_meta.get("contexts"), dict) else {}
            sets = block.get("sets") if isinstance(block.get("sets"), dict) else {}
            if active and isinstance(sets.get(active), dict):
                ctx_vals = dict(sets[active])

            published = extract_publish(
                child_pipeline=child_def,
                child_result=child_result,
                publish_as=publish_as,
                active_context=active,
                context_values=ctx_vals,
            )
            children_map = dict(children_so_far)
            children_map[publish_as] = published
            ctx.variables["children"] = children_map
            # Refresh VarScope child table
            scope = ctx.variables.get("_var_scope")
            if scope is not None and hasattr(scope, "children"):
                scope.children = {
                    str(k): dict(v) for k, v in children_map.items() if isinstance(v, dict)
                }

            metrics.extras["child_run_id"] = child_result.run_id
            metrics.extras["child_pipeline_id"] = child_def.id
            metrics.extras["child_status"] = child_result.status
            metrics.extras["publish_as"] = publish_as
            metrics.extras["context_mode"] = context_mode
            metrics.extras["child_context"] = active
            metrics.rows_in = len(rows or [])
            if child_result.status == "success":
                metrics.rows_out = (
                    len(rows or [])
                    if pass_rows
                    else int((child_result.metrics or {}).get("rows_out") or 0)
                )
            else:
                metrics.rows_out = 0
                metrics.rows_rejected = metrics.rows_in

            side_effects = {
                "child_run_id": child_result.run_id,
                "child_pipeline_id": child_def.id,
                "child_status": child_result.status,
                "publish_as": publish_as,
                "published": published,
                "child_error": child_result.error,
            }

            if child_result.status != "success":
                msg = (
                    f"Child pipeline '{child_def.id}' failed: "
                    f"{child_result.error or child_result.status}"
                )
                ctx.emit(msg)
                if on_failure == "fail_master":
                    raise PipelineNestingError(msg)
                # continue — publish failure metrics, optionally still pass rows? No.
                return ComponentResult(
                    rows=list(rows or []) if pass_rows else [],
                    metrics=metrics,
                    side_effects=side_effects,
                )

            out_rows = list(rows or []) if pass_rows else []
            return ComponentResult(
                rows=out_rows,
                metrics=metrics,
                side_effects=side_effects,
            )
