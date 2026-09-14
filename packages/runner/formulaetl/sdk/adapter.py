"""Adapters between DatasetHandle / ArtifactHandle and legacy list[dict] + bytes.

Existing components that still implement ``run(ctx, rows: list[dict])`` keep
working. File nodes that expose a local path no longer receive whole-object
``bytes`` copies in ``config``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from formulaetl.sdk.capabilities import ComponentCapabilities
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.data import ArtifactHandle, DatasetHandle, DEFAULT_BATCH_SIZE

FeedMode = str  # "none" | "artifact" | "batches" | "materialized_rows"


def rows_to_dataset(
    rows: list[dict[str, Any]] | None,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> DatasetHandle:
    return DatasetHandle.from_rows(rows, batch_size=batch_size)


def dataset_to_rows(dataset: DatasetHandle | None) -> list[dict[str, Any]]:
    if dataset is None:
        return []
    return dataset.materialize()


def artifact_from_result(result: ComponentResult) -> ArtifactHandle | None:
    if result.artifact is not None:
        return result.artifact
    raw = result.artifacts.get("artifact")
    if isinstance(raw, dict):
        handle = ArtifactHandle.from_dict(raw)
        if handle:
            return handle
    path = result.artifacts.get("path")
    if path:
        p = Path(str(path))
        if p.exists():
            return ArtifactHandle.from_path(p, checksum=False)
    return None


def ensure_dataset(
    result: ComponentResult,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> DatasetHandle:
    if result.dataset is not None:
        return result.dataset
    return DatasetHandle.from_rows(result.rows, batch_size=batch_size)


def apply_upstream_to_component(
    component: Any,
    ctx: RunContext,
    *,
    artifacts: dict[str, Any],
    handle: ArtifactHandle | None,
    next_caps: ComponentCapabilities,
) -> None:
    """Copy upstream file pointers into the next node without cloning giant payloads.

    If a local path exists, skip injecting ``bytes`` / ``content``. That is the
    adapter for remaining components that still *can* read path/upstream_path.
    Bytes are only copied when there is no path (true legacy byte-only hop).
    """
    cfg = dict(component.config)
    inject_payload = True
    path: str | None = None
    if handle is not None and handle.path:
        path = handle.path
    elif artifacts.get("path"):
        path = str(artifacts["path"])

    if path:
        ctx.variables["upstream_path"] = path
        if handle is not None:
            ctx.variables["upstream_artifact"] = handle.to_dict()
        elif "artifact" in artifacts and isinstance(artifacts["artifact"], dict):
            ctx.variables["upstream_artifact"] = artifacts["artifact"]
        if "path" not in cfg:
            cfg["path"] = path
        # File exists → do not copy whole-object bytes/content into config/RAM.
        if Path(path).exists():
            inject_payload = False
            ctx.variables.pop("upstream_bytes", None)
            ctx.variables.pop("upstream_content", None)

    if inject_payload:
        if "content" not in cfg and "content" in artifacts:
            cfg["content"] = artifacts["content"]
            ctx.variables["upstream_content"] = artifacts["content"]
        if "bytes" not in cfg and "bytes" in artifacts:
            cfg["bytes"] = artifacts["bytes"]
            ctx.variables["upstream_bytes"] = artifacts["bytes"]
        elif handle is not None and next_caps.io_kind in ("artifact", "mixed") and not path:
            # Last resort adapter: materialize bytes from the handle.
            raw = handle.read_bytes()
            cfg["bytes"] = raw
            ctx.variables["upstream_bytes"] = raw

    component.config = cfg


def run_legacy(
    component: Any,
    ctx: RunContext,
    dataset: DatasetHandle | None,
) -> ComponentResult:
    """Materialize the dataset and call ``run(ctx, list[dict])``."""
    rows = None if dataset is None else dataset.materialize()
    return component.run(ctx, rows)


def run_batched(
    component: Any,
    ctx: RunContext,
    dataset: DatasetHandle,
    batch_size: int,
) -> ComponentResult:
    """Call ``run`` once per RowBatch and concatenate outputs (legacy-compatible).

    Input to each ``run`` is bounded. Output is still concatenated in this
    process so a following blocking sink can ``materialize()``.
    """
    out_rows: list[dict[str, Any]] = []
    out_rejects: list[dict[str, Any]] = []
    streams: dict[str, list[dict[str, Any]]] = {}
    side_effects: dict[str, Any] = {}
    artifacts: dict[str, Any] = {}
    artifact: ArtifactHandle | None = None
    metrics = Metrics()
    n_batches = 0
    with timed(metrics):
        for batch in dataset.iter_batches(batch_size):
            n_batches += 1
            cres = component.run(ctx, list(batch.rows))
            out_rows.extend(cres.rows)
            out_rejects.extend(cres.rejects)
            for key, rows in cres.streams.items():
                streams.setdefault(key, []).extend(rows)
            side_effects.update(cres.side_effects or {})
            artifacts.update(cres.artifacts or {})
            if cres.artifact is not None:
                artifact = cres.artifact
            metrics.rows_in += cres.metrics.rows_in
            metrics.rows_out += cres.metrics.rows_out
            metrics.rows_rejected += cres.metrics.rows_rejected
    metrics.extras["feed"] = "batches"
    metrics.extras["batches"] = n_batches
    if not streams and out_rows:
        streams = {"out": out_rows}
    if out_rejects and "rejects" not in streams:
        streams["rejects"] = out_rejects
    return ComponentResult(
        rows=out_rows,
        rejects=out_rejects,
        side_effects=side_effects,
        metrics=metrics,
        artifacts=artifacts,
        streams=streams,
        dataset=DatasetHandle.from_rows(out_rows, batch_size=batch_size),
        artifact=artifact,
    )
