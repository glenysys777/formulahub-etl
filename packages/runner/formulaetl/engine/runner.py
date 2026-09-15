"""DAG pipeline runner.

Honesty (not a production data plane): nodes still run sequentially in one
process. DatasetHandle / ArtifactHandle feed row-wise nodes bounded
``RowBatch``es; large intermediates spill to JSONL under the run temp dir.
Legacy ``run(ctx, list[dict])`` components keep working through the adapter.
Default ``FORMULAETL_DEMO=1`` is fixture/mock mode.
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from formulaetl.engine.planner import ExecutionPlan, NodePlan, plan_pipeline
from formulaetl.models.pipeline import PipelineDefinition
from formulaetl.sdk.adapter import (
    apply_upstream_to_component,
    artifact_from_result,
    run_batched,
    run_legacy,
)
from formulaetl.sdk.context import ComponentResult
from formulaetl.sdk.data import ArtifactHandle, DatasetHandle, DEFAULT_BATCH_SIZE
from formulaetl.sdk.registry import create_component


@dataclass
class RunResult:
    run_id: str
    pipeline_id: str
    status: str  # pending | running | success | failed
    metrics: dict[str, Any] = field(default_factory=dict)
    node_metrics: dict[str, dict[str, Any]] = field(default_factory=dict)
    logs: list[str] = field(default_factory=list)
    error: str | None = None
    outputs: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    plan: dict[str, Any] = field(default_factory=dict)


class PipelineRunner:
    """Execute a PipelineDefinition as a sequential DAG."""

    def __init__(
        self,
        work_dir: str | Path | None = None,
        demo_mode: bool | None = None,
        batch_size: int | None = None,
        *,
        secret_provider: Any | None = None,
        get_connection: Any | None = None,
    ):
        self.work_dir = Path(work_dir or os.getcwd()).resolve()
        if demo_mode is None:
            demo_mode = os.environ.get("FORMULAETL_DEMO", "1") == "1"
        self.demo_mode = demo_mode
        if batch_size is None:
            raw = os.environ.get("FORMULAETL_BATCH_SIZE") or str(DEFAULT_BATCH_SIZE)
            try:
                batch_size = int(raw)
            except ValueError:
                batch_size = DEFAULT_BATCH_SIZE
        self.batch_size = max(1, int(batch_size))
        self.secret_provider = secret_provider
        self.get_connection = get_connection

    def run(
        self,
        pipeline: PipelineDefinition,
        run_id: str | None = None,
        *,
        pipeline_stack: list[str] | None = None,
        get_pipeline: Any | None = None,
        record_child_run: Any | None = None,
        complete_child_run: Any | None = None,
        parent_run_id: str | None = None,
        master_node_id: str | None = None,
    ) -> RunResult:
        run_id = run_id or str(uuid.uuid4())
        logs: list[str] = []

        def _log(msg: str) -> None:
            from formulaetl.sdk.io_util import redact_secrets

            line = f"[{run_id[:8]}] {redact_secrets(msg)}"
            logs.append(line)

        # Default Community secret provider: env vars only (CLI without API store).
        secret_provider = self.secret_provider
        if secret_provider is None:
            from formulaetl.sdk.secrets import EnvSecretProvider

            secret_provider = EnvSecretProvider()

        from formulaetl.sdk.context import RunContext

        stack = list(pipeline_stack) if pipeline_stack else [pipeline.id]
        ctx = RunContext(
            run_id=run_id,
            pipeline_id=pipeline.id,
            demo_mode=self.demo_mode,
            work_dir=self.work_dir,
            data_dir=self.work_dir / "data",
            log=_log,
            batch_size=self.batch_size,
            secret_provider=secret_provider,
            get_connection=self.get_connection,
            pipeline_stack=stack,
            parent_run_id=parent_run_id,
            master_node_id=master_node_id,
            get_pipeline=get_pipeline,
            record_child_run=record_child_run,
            complete_child_run=complete_child_run,
        )

        from formulaetl.sdk.vars import bind_pipeline_variables

        scope = bind_pipeline_variables(ctx, pipeline)

        result = RunResult(
            run_id=run_id,
            pipeline_id=pipeline.id,
            status="running",
            logs=logs,
        )
        t0 = time.perf_counter()
        ctx_label = scope.active_context or "(none)"
        _log(
            f"Starting pipeline '{pipeline.name}' "
            f"(demo={self.demo_mode}, batch_size={self.batch_size}, "
            f"context={ctx_label})"
        )

        exec_plan: ExecutionPlan | None = None
        node_outputs: dict[str, ComponentResult] = {}
        temp_handles: list[ArtifactHandle] = []
        # Track remaining downstream consumers so we can free row lists early.
        remaining_consumers: dict[str, int] = {}

        try:
            order = pipeline.topological_order()
            node_map = pipeline.node_map()

            inbound: dict[str, list] = {n.id: [] for n in pipeline.nodes}
            for e in pipeline.edges:
                inbound[e.target].append(e)
                remaining_consumers[e.source] = remaining_consumers.get(e.source, 0) + 1

            exec_plan = plan_pipeline(pipeline, batch_size=self.batch_size)
            result.plan = exec_plan.to_dict()
            total_in = total_out = total_rej = 0

            for nid in order:
                node = node_map[nid]
                nplan = exec_plan.nodes[nid]
                ctx.variables["_current_node_id"] = nid
                _log(
                    f"→ Running node '{node.label or nid}' ({node.type}) "
                    f"feed={nplan.feed} ({nplan.reason})"
                )
                # Phase F: merge connection_id + secret refs (never persist merged secrets)
                resolved_cfg = ctx.resolve_config(node.config, component_type=node.type)

                dataset, input_rows, upstream_artifacts, upstream_handle = _gather_inputs(
                    nid, inbound, node_outputs, ctx, self.batch_size
                )

                # Resolve ${context.*} / ${run.*} / ${env.*} / ${upstream.*} / ${child.*} / ${key}
                # Keep original templates for components that log / sidecar them.
                from formulaetl.sdk.vars import resolve_config_vars, find_refs

                templates: dict[str, Any] = {}
                for key, val in (node.config or {}).items():
                    if isinstance(val, str) and find_refs(val):
                        templates[key] = val
                    elif isinstance(val, list) and any(
                        isinstance(x, str) and find_refs(x) for x in val
                    ):
                        templates[key] = val
                resolved_cfg = resolve_config_vars(
                    resolved_cfg, ctx, upstream_rows=input_rows
                )
                if templates:
                    resolved_cfg = {**resolved_cfg, "_var_templates": templates}
                component = create_component(node.type, resolved_cfg)
                component.validate_config()

                apply_upstream_to_component(
                    component,
                    ctx,
                    artifacts=upstream_artifacts,
                    handle=upstream_handle,
                    next_caps=nplan.capabilities,
                )

                cres = _invoke(component, ctx, nplan, dataset, input_rows)
                if cres.dataset is None and cres.rows is not None:
                    cres.dataset = DatasetHandle.from_rows(cres.rows, self.batch_size)
                if cres.artifact is None:
                    cres.artifact = artifact_from_result(cres)
                if "feed" not in cres.metrics.extras:
                    cres.metrics.extras["feed"] = nplan.feed

                if "component_type" not in cres.metrics.extras:
                    cres.metrics.extras["component_type"] = node.type
                node_outputs[nid] = cres
                ctx.record_metrics(nid, cres.metrics)
                if cres.artifact and cres.artifact.temp:
                    temp_handles.append(cres.artifact)

                _remember_source_path(ctx, node.type, cres)

                # Drop large in-RAM lists from upstream once all consumers finished.
                for e in inbound[nid]:
                    remaining_consumers[e.source] = remaining_consumers.get(e.source, 1) - 1
                    if remaining_consumers[e.source] <= 0:
                        _release_result_rows(node_outputs[e.source])
                        # After a sink pulls a lazy chain, harvest finalized metrics.
                        from formulaetl.sdk.adapter import harvest_lazy_metrics

                        harvest_lazy_metrics(node_outputs[e.source])
                        ctx.record_metrics(e.source, node_outputs[e.source].metrics)

                total_in += cres.metrics.rows_in
                total_out += cres.metrics.rows_out
                total_rej += cres.metrics.rows_rejected
                _log(
                    f"  ✓ {node.type}: in={cres.metrics.rows_in} "
                    f"out={cres.metrics.rows_out} rejected={cres.metrics.rows_rejected} "
                    f"feed={nplan.feed} ({cres.metrics.duration_ms:.1f}ms)"
                )

            # Final harvest for any lazy nodes still pending (e.g. last sink).
            from formulaetl.sdk.adapter import harvest_lazy_metrics

            for nid, o in node_outputs.items():
                harvest_lazy_metrics(o)
                ctx.record_metrics(nid, o.metrics)

            total_in = sum(o.metrics.rows_in for o in node_outputs.values())
            total_out = sum(o.metrics.rows_out for o in node_outputs.values())
            total_rej = sum(o.metrics.rows_rejected for o in node_outputs.values())

            result.status = "success"
            result.metrics = {
                "rows_in": total_in,
                "rows_out": total_out,
                "rows_rejected": total_rej,
                "batch_size": self.batch_size,
            }
            children = ctx.variables.get("children")
            if isinstance(children, dict) and children:
                result.metrics["children"] = {
                    str(k): dict(v) for k, v in children.items() if isinstance(v, dict)
                }
            result.outputs = {
                nid: {**_summarize_output(o), "component_type": node_map[nid].type}
                for nid, o in node_outputs.items()
            }
            _log("Pipeline completed successfully")

        except Exception as exc:
            result.status = "failed"
            result.error = str(exc)
            _log(f"Pipeline FAILED: {exc}")
            # Partial aggregates if some nodes finished
            if node_outputs:
                result.metrics = {
                    "rows_in": sum(o.metrics.rows_in for o in node_outputs.values()),
                    "rows_out": sum(o.metrics.rows_out for o in node_outputs.values()),
                    "rows_rejected": sum(
                        o.metrics.rows_rejected for o in node_outputs.values()
                    ),
                    "batch_size": self.batch_size,
                }
                children = ctx.variables.get("children")
                if isinstance(children, dict) and children:
                    result.metrics["children"] = {
                        str(k): dict(v) for k, v in children.items() if isinstance(v, dict)
                    }
                result.outputs = {
                    nid: {
                        **_summarize_output(o),
                        "component_type": pipeline.node_map()[nid].type
                        if nid in pipeline.node_map()
                        else "unknown",
                    }
                    for nid, o in node_outputs.items()
                }

        finally:
            # Always persist node metrics (including partial failure)
            result.node_metrics = ctx.all_metrics()
            _cleanup_temps(temp_handles, _log)

        result.duration_ms = (time.perf_counter() - t0) * 1000
        if "duration_ms" not in result.metrics:
            result.metrics = dict(result.metrics)
        result.metrics["duration_ms"] = round(result.duration_ms, 2)
        result.logs = logs
        if exec_plan is not None and "planner_nodes" not in result.metrics:
            result.metrics["planner_nodes"] = len(exec_plan.nodes)
        return result


def _release_result_rows(cres: ComponentResult) -> None:
    """Free list[dict] payloads when a spill/dataset remains for replay."""
    if cres.dataset is not None and not cres.rows:
        return
    if cres.dataset is not None or cres.stream_datasets:
        cres.rows = []
        cres.rejects = []
        cres.streams = {}
        if cres.dataset is not None:
            cres.dataset.release_materialized()


def _port_dataset(
    up: ComponentResult,
    handle: str,
    batch_size: int,
) -> tuple[DatasetHandle, list[dict[str, Any]] | None]:
    """Resolve a named output port to a DatasetHandle without forcing full lists."""
    if handle in up.stream_datasets:
        return up.stream_datasets[handle], None
    if handle == "rejects":
        if up.rejects:
            return DatasetHandle.from_rows(list(up.rejects), batch_size), list(up.rejects)
        if "rejects" in up.streams:
            chunk = list(up.streams["rejects"])
            return DatasetHandle.from_rows(chunk, batch_size), chunk
        return DatasetHandle.from_rows([], batch_size), []
    if handle == "out" or handle not in up.streams:
        if up.dataset is not None:
            return up.dataset, (list(up.rows) if up.rows else None)
        chunk = list(up.rows)
        return DatasetHandle.from_rows(chunk, batch_size), chunk
    chunk = list(up.streams[handle])
    return DatasetHandle.from_rows(chunk, batch_size), chunk


def _gather_inputs(
    nid: str,
    inbound: dict[str, list],
    node_outputs: dict[str, ComponentResult],
    ctx: Any,
    batch_size: int,
) -> tuple[DatasetHandle | None, list[dict[str, Any]] | None, dict[str, Any], ArtifactHandle | None]:
    edges_in = inbound[nid]
    if not edges_in:
        ctx.variables.pop("_input_streams", None)
        return None, None, {}, None

    input_rows: list[dict[str, Any]] | None = None
    input_streams: dict[str, list[dict[str, Any]]] = {}
    input_stream_datasets: dict[str, DatasetHandle] = {}
    upstream_artifacts: dict[str, Any] = {}
    upstream_handle: ArtifactHandle | None = None
    passthrough_dataset: DatasetHandle | None = None

    for e in edges_in:
        up = node_outputs[e.source]
        handle = e.sourceHandle or "out"
        chunk_ds, chunk_rows = _port_dataset(up, handle, batch_size)
        target_port = e.targetHandle or "in"
        input_stream_datasets[target_port] = chunk_ds
        if chunk_rows is not None:
            input_streams.setdefault(target_port, []).extend(chunk_rows)
        upstream_artifacts.update(up.artifacts)
        if up.artifact is not None:
            upstream_handle = up.artifact
        if len(edges_in) == 1 and handle not in ("rejects",) and handle not in up.streams:
            passthrough_dataset = chunk_ds
            input_rows = chunk_rows

    if any(p != "in" for p in input_stream_datasets) or len(input_stream_datasets) > 1:
        # Multi-port joins still need list adapters for legacy components.
        materialized_streams: dict[str, list[dict[str, Any]]] = {}
        for port, ds in input_stream_datasets.items():
            if port in input_streams:
                materialized_streams[port] = input_streams[port]
            else:
                materialized_streams[port] = ds.materialize()
        ctx.variables["_input_streams"] = materialized_streams
        for pref in ("left", "main", "in"):
            if pref in input_stream_datasets:
                passthrough_dataset = input_stream_datasets[pref]
                input_rows = materialized_streams.get(pref)
                break
    else:
        ctx.variables.pop("_input_streams", None)
        if passthrough_dataset is None and input_stream_datasets:
            passthrough_dataset = next(iter(input_stream_datasets.values()))

    if passthrough_dataset is None:
        passthrough_dataset = DatasetHandle.from_rows(input_rows or [], batch_size)
    return passthrough_dataset, input_rows, upstream_artifacts, upstream_handle


def _invoke(
    component: Any,
    ctx: Any,
    nplan: NodePlan,
    dataset: DatasetHandle | None,
    input_rows: list[dict[str, Any]] | None,
) -> ComponentResult:
    feed = nplan.feed
    if feed == "none":
        return component.run(ctx, None)
    if feed == "artifact":
        # File hop: path/handle is in config. Pass through rows if present
        # (archive echoes them) but parsers should prefer the artifact path.
        return component.run(ctx, input_rows)
    if feed == "batches":
        if dataset is None:
            dataset = DatasetHandle.from_rows(input_rows, nplan.batch_size)
        return run_batched(component, ctx, dataset, nplan.batch_size)
    # materialized_rows — legacy adapter
    if dataset is None:
        return component.run(ctx, input_rows)
    cres = run_legacy(component, ctx, dataset)
    if "feed" not in cres.metrics.extras:
        cres.metrics.extras["feed"] = "materialized_rows"
    return cres


def _remember_source_path(ctx: Any, node_type: str, cres: ComponentResult) -> None:
    path = None
    if cres.artifact is not None and cres.artifact.path:
        path = cres.artifact.path
    elif cres.artifacts.get("path"):
        path = str(cres.artifacts["path"])

    if node_type in ("s3_source", "local_file_source", "sftp_source") and path:
        ctx.variables["original_source_path"] = path
        ctx.variables["upstream_path"] = path
        if cres.artifact is not None:
            ctx.variables["upstream_artifact"] = cres.artifact.to_dict()
        ctx.variables.pop("upstream_bytes", None)
        return

    if cres.artifact is not None:
        ctx.variables["upstream_artifact"] = cres.artifact.to_dict()
        if cres.artifact.path:
            ctx.variables["upstream_path"] = cres.artifact.path
        ctx.variables.pop("upstream_bytes", None)
        ctx.variables.pop("upstream_content", None)
        return

    if cres.artifacts:
        for k, v in cres.artifacts.items():
            if k in ("bytes", "content"):
                continue
            ctx.variables[f"upstream_{k}"] = v


def _summarize_output(o: ComponentResult) -> dict[str, Any]:
    n_rows = o.metrics.rows_out if o.metrics.rows_out else len(o.rows)
    artifact_meta = None
    if o.artifact is not None:
        artifact_meta = o.artifact.to_dict()
    return {
        "rows": n_rows,
        "rejects": o.metrics.rows_rejected if o.metrics.rows_rejected else len(o.rejects),
        "side_effects": o.side_effects,
        "artifacts": {
            k: (str(v) if isinstance(v, (Path, bytes)) else v)
            for k, v in o.artifacts.items()
            if k not in ("bytes", "content")
        },
        "artifact": artifact_meta,
        "feed": o.metrics.extras.get("feed"),
    }


def _cleanup_temps(handles: list[ArtifactHandle], log) -> None:
    for handle in handles:
        if not handle.temp or not handle.path:
            continue
        try:
            Path(handle.path).unlink(missing_ok=True)
        except OSError as exc:
            log(f"temp cleanup skipped {handle.path}: {exc}")
