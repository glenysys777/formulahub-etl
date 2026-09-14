"""DAG pipeline runner.

Honesty (not a production data plane): nodes run sequentially in one process.
The working set is ``list[dict]`` rows plus optional whole-object ``bytes``
artifacts (S3/SFTP/PGP). There is no chunked I/O, spill, or worker isolation.
Default ``FORMULAETL_DEMO=1`` is fixture/mock mode.
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from formulaetl.models.pipeline import PipelineDefinition
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext
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


class PipelineRunner:
    """Execute a PipelineDefinition as a sequential DAG."""

    def __init__(
        self,
        work_dir: str | Path | None = None,
        demo_mode: bool | None = None,
    ):
        self.work_dir = Path(work_dir or os.getcwd()).resolve()
        if demo_mode is None:
            demo_mode = os.environ.get("FORMULAETL_DEMO", "1") == "1"
        self.demo_mode = demo_mode

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
        )

        result = RunResult(
            run_id=run_id,
            pipeline_id=pipeline.id,
            status="running",
            logs=logs,
        )
        t0 = time.perf_counter()
        _log(f"Starting pipeline '{pipeline.name}' (demo={self.demo_mode})")

        try:
            order = pipeline.topological_order()
            node_map = pipeline.node_map()

            # Collect inbound edges per target for multi-input support
            inbound: dict[str, list] = {n.id: [] for n in pipeline.nodes}
            for e in pipeline.edges:
                inbound[e.target].append(e)

            node_outputs: dict[str, ComponentResult] = {}
            total_in = total_out = total_rej = 0

            for nid in order:
                node = node_map[nid]
                _log(f"→ Running node '{node.label or nid}' ({node.type})")
                component = create_component(node.type, node.config)
                component.validate_config()

                # Gather input rows from upstream (prefer main stream)
                input_rows: list[dict[str, Any]] | None = None
                upstream_artifacts: dict[str, Any] = {}
                edges_in = inbound[nid]
                if edges_in:
                    input_rows = []
                    input_streams: dict[str, list[dict[str, Any]]] = {}
                    for e in edges_in:
                        up = node_outputs[e.source]
                        handle = e.sourceHandle or "out"
                        if handle == "rejects" and up.rejects:
                            chunk = list(up.rejects)
                        elif handle in up.streams:
                            chunk = list(up.streams[handle])
                        else:
                            chunk = list(up.rows)
                        target_port = e.targetHandle or "in"
                        input_streams.setdefault(target_port, []).extend(chunk)
                        input_rows.extend(chunk)
                        upstream_artifacts.update(up.artifacts)
                    # Expose named ports for multi-input transforms (e.g. lookup_join)
                    if any(p != "in" for p in input_streams) or len(input_streams) > 1:
                        ctx.variables["_input_streams"] = input_streams
                        # Prefer left/main/in as the primary row list
                        for pref in ("left", "main", "in"):
                            if pref in input_streams:
                                input_rows = list(input_streams[pref])
                                break
                    else:
                        ctx.variables.pop("_input_streams", None)

                # Merge upstream artifacts into config for file-path chaining
                if upstream_artifacts:
                    ctx.variables.update({f"upstream_{k}": v for k, v in upstream_artifacts.items()})
                    # Preserve the first on-disk source path for ArchiveFiles
                    if "path" in upstream_artifacts and "original_source_path" not in ctx.variables:
                        if node.type in ("s3_source", "local_file_source"):
                            pass  # set after run below
                    cfg = dict(component.config)
                    if "path" not in cfg and "path" in upstream_artifacts:
                        cfg["path"] = upstream_artifacts["path"]
                    if "content" not in cfg and "content" in upstream_artifacts:
                        cfg["content"] = upstream_artifacts["content"]
                    if "bytes" not in cfg and "bytes" in upstream_artifacts:
                        cfg["bytes"] = upstream_artifacts["bytes"]
                    component.config = cfg

                cres = component.run(ctx, input_rows)
                node_outputs[nid] = cres
                ctx.record_metrics(nid, cres.metrics)

                # Remember original source path (S3/local file) for archive step
                if node.type in ("s3_source", "local_file_source", "sftp_source") and cres.artifacts.get("path"):
                    ctx.variables["original_source_path"] = cres.artifacts["path"]
                    ctx.variables["upstream_path"] = cres.artifacts["path"]
                    ctx.variables["upstream_bytes"] = cres.artifacts.get("bytes")
                elif cres.artifacts:
                    for k, v in cres.artifacts.items():
                        ctx.variables[f"upstream_{k}"] = v

                total_in += cres.metrics.rows_in
                total_out += cres.metrics.rows_out
                total_rej += cres.metrics.rows_rejected
                _log(
                    f"  ✓ {node.type}: in={cres.metrics.rows_in} "
                    f"out={cres.metrics.rows_out} rejected={cres.metrics.rows_rejected} "
                    f"({cres.metrics.duration_ms:.1f}ms)"
                )

            # Aggregate from last sink-ish nodes
            result.status = "success"
            result.metrics = {
                "rows_in": total_in,
                "rows_out": total_out,
                "rows_rejected": total_rej,
            }
            result.node_metrics = ctx.all_metrics()
            result.outputs = {
                nid: {
                    "rows": len(o.rows),
                    "rejects": len(o.rejects),
                    "side_effects": o.side_effects,
                    "artifacts": {
                        k: (str(v) if isinstance(v, (Path, bytes)) else v)
                        for k, v in o.artifacts.items()
                        if k != "bytes" and k != "content"
                    },
                }
                for nid, o in node_outputs.items()
            }
            _log("Pipeline completed successfully")

        except Exception as exc:
            result.status = "failed"
            result.error = str(exc)
            _log(f"Pipeline FAILED: {exc}")

        result.duration_ms = (time.perf_counter() - t0) * 1000
        result.metrics["duration_ms"] = round(result.duration_ms, 2)
        result.logs = logs
        return result
