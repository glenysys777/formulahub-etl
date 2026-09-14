"""DAG pipeline runner.

Honesty (not a production data plane): nodes still run sequentially in one
process. Phase B adds DatasetHandle / ArtifactHandle and a planner that feeds
row-wise nodes bounded ``RowBatch``es and file hops via on-disk handles.
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
from formulaetl.sdk.context import ComponentResult, RunContext
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

    def run(self, pipeline: PipelineDefinition, run_id: str | None = None) -> RunResult:
        run_id = run_id or str(uuid.uuid4())
        logs: list[str] = []

        def _log(msg: str) -> None:
            line = f"[{run_id[:8]}] {msg}"
            logs.append(line)

        ctx = RunContext(
            run_id=run_id,
            pipeline_id=pipeline.id,
            demo_mode=self.demo_mode,
            work_dir=self.work_dir,
            data_dir=self.work_dir / "data",
            log=_log,
            batch_size=self.batch_size,
        )

        result = RunResult(
            run_id=run_id,
            pipeline_id=pipeline.id,
            status="running",
            logs=logs,
        )
        t0 = time.perf_counter()
        _log(
            f"Starting pipeline '{pipeline.name}' "
            f"(demo={self.demo_mode}, batch_size={self.batch_size})"
        )

        exec_plan: ExecutionPlan | None = None
        node_outputs: dict[str, ComponentResult] = {}
        temp_handles: list[ArtifactHandle] = []

        try:
            order = pipeline.topological_order()
            node_map = pipeline.node_map()

            inbound: dict[str, list] = {n.id: [] for n in pipeline.nodes}
            for e in pipeline.edges:
                inbound[e.target].append(e)

            exec_plan = plan_pipeline(pipeline, batch_size=self.batch_size)
            result.plan = exec_plan.to_dict()
            total_in = total_out = total_rej = 0

            for nid in order:
                node = node_map[nid]
                nplan = exec_plan.nodes[nid]
                _log(
                    f"→ Running node '{node.label or nid}' ({node.type}) "
                    f"feed={nplan.feed} ({nplan.reason})"
                )
                component = create_component(node.type, node.config)
                component.validate_config()

                dataset, input_rows, upstream_artifacts, upstream_handle = _gather_inputs(
                    nid, inbound, node_outputs, ctx, self.batch_size
                )

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

                total_in += cres.metrics.rows_in
                total_out += cres.metrics.rows_out
                total_rej += cres.metrics.rows_rejected
                _log(
                    f"  ✓ {node.type}: in={cres.metrics.rows_in} "
                    f"out={cres.metrics.rows_out} rejected={cres.metrics.rows_rejected} "
                    f"feed={nplan.feed} ({cres.metrics.duration_ms:.1f}ms)"
                )

            result.status = "success"
            result.metrics = {
                "rows_in": total_in,
                "rows_out": total_out,
                "rows_rejected": total_rej,
                "batch_size": self.batch_size,
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


def _gather_inputs(
    nid: str,
    inbound: dict[str, list],
    node_outputs: dict[str, ComponentResult],
    ctx: RunContext,
    batch_size: int,
) -> tuple[DatasetHandle | None, list[dict[str, Any]] | None, dict[str, Any], ArtifactHandle | None]:
    edges_in = inbound[nid]
    if not edges_in:
        ctx.variables.pop("_input_streams", None)
        return None, None, {}, None

    input_rows: list[dict[str, Any]] = []
    input_streams: dict[str, list[dict[str, Any]]] = {}
    upstream_artifacts: dict[str, Any] = {}
    upstream_handle: ArtifactHandle | None = None
    passthrough_dataset: DatasetHandle | None = None

    for e in edges_in:
        up = node_outputs[e.source]
        handle = e.sourceHandle or "out"
        if handle == "rejects" and up.rejects:
            chunk = list(up.rejects)
            chunk_ds = DatasetHandle.from_rows(chunk, batch_size)
        elif handle in up.streams:
            chunk = list(up.streams[handle])
            chunk_ds = DatasetHandle.from_rows(chunk, batch_size)
        else:
            chunk = list(up.rows)
            chunk_ds = up.dataset if up.dataset is not None else DatasetHandle.from_rows(chunk, batch_size)
        target_port = e.targetHandle or "in"
        input_streams.setdefault(target_port, []).extend(chunk)
        input_rows.extend(chunk)
        upstream_artifacts.update(up.artifacts)
        if up.artifact is not None:
            upstream_handle = up.artifact
        if len(edges_in) == 1 and handle not in ("rejects",) and handle not in up.streams:
            passthrough_dataset = chunk_ds

    if any(p != "in" for p in input_streams) or len(input_streams) > 1:
        ctx.variables["_input_streams"] = input_streams
        for pref in ("left", "main", "in"):
            if pref in input_streams:
                input_rows = list(input_streams[pref])
                passthrough_dataset = DatasetHandle.from_rows(input_rows, batch_size)
                break
    else:
        ctx.variables.pop("_input_streams", None)

    if passthrough_dataset is None:
        passthrough_dataset = DatasetHandle.from_rows(input_rows, batch_size)
    return passthrough_dataset, input_rows, upstream_artifacts, upstream_handle


def _invoke(
    component: Any,
    ctx: RunContext,
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


def _remember_source_path(ctx: RunContext, node_type: str, cres: ComponentResult) -> None:
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
        "rejects": len(o.rejects),
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
