"""Adapters between DatasetHandle / ArtifactHandle and legacy list[dict] + bytes.

Existing components that still implement ``run(ctx, rows: list[dict])`` keep
working. File nodes that expose a local path no longer receive whole-object
``bytes`` copies in ``config``.

Phase Perf: ``run_batched`` builds a lazy producer chain (one batch at a time)
so multi-hop wedges do not concatenate or spill full ``list[dict]`` working
sets. Streaming sinks (``consume_dataset``) pull the chain in a single pass.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from formulaetl.sdk.capabilities import ComponentCapabilities
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.data import ArtifactHandle, DatasetHandle, DEFAULT_BATCH_SIZE, RowBatch
from formulaetl.sdk.spill import (
    SPILL_THRESHOLD,
    JsonlSpillWriter,
    new_spill_path,
)

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
    if result.stream_datasets.get("out") is not None:
        return result.stream_datasets["out"]
    return DatasetHandle.from_rows(result.rows, batch_size=batch_size)


def apply_upstream_to_component(
    component: Any,
    ctx: RunContext,
    *,
    artifacts: dict[str, Any],
    handle: ArtifactHandle | None,
    next_caps: ComponentCapabilities,
) -> None:
    """Copy upstream file pointers into the next node without cloning giant payloads."""
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


class _LazyBatchState:
    """Mutable metrics filled when a lazy producer is first fully consumed."""

    def __init__(self) -> None:
        self.metrics = Metrics()
        self.n_batches = 0
        self.consumed = False
        self.rejects_path: Path | None = None
        self.rejects_count = 0


def run_batched(
    component: Any,
    ctx: RunContext,
    dataset: DatasetHandle,
    batch_size: int,
) -> ComponentResult:
    """Feed ``run`` once per RowBatch.

    * Streaming sinks (``consume_dataset``) pull eagerly — one pass.
    * Other row-wise nodes return a **lazy** DatasetHandle that transforms
      batches on iteration (no full concat, no intermediate spill). Side
      rejects are written to a JSONL spill as the chain is pulled so fan-out
      edges remain replayable.
    """
    consume = getattr(component, "consume_dataset", None)
    if callable(consume):
        cres = consume(ctx, dataset)
        if "feed" not in cres.metrics.extras:
            cres.metrics.extras["feed"] = "batches"
        return cres

    # Small already-materialized inputs: keep the simple concat path for tests.
    if (
        dataset.is_materialized
        and dataset.row_count is not None
        and dataset.row_count <= SPILL_THRESHOLD
    ):
        return _run_batched_eager_small(component, ctx, dataset, batch_size)

    state = _LazyBatchState()
    spill_dir = ctx.temp_dir() / "spill"
    rej_path = new_spill_path(spill_dir, "rej")
    rej_writer_holder: dict[str, JsonlSpillWriter | None] = {"w": None}

    def producer(bs: int):
        metrics = state.metrics
        with timed(metrics):
            for batch in dataset.iter_batches(bs):
                state.n_batches += 1
                cres = component.run(ctx, batch.rows)
                if cres.rejects:
                    if rej_writer_holder["w"] is None:
                        rej_writer_holder["w"] = JsonlSpillWriter(rej_path)
                    rej_writer_holder["w"].write_rows(cres.rejects)
                    state.rejects_count += len(cres.rejects)
                metrics.rows_in += cres.metrics.rows_in
                metrics.rows_out += cres.metrics.rows_out
                metrics.rows_rejected += cres.metrics.rows_rejected
                yield RowBatch(
                    rows=cres.rows,
                    batch_index=batch.batch_index,
                    eof=batch.eof,
                )
            w = rej_writer_holder["w"]
            if w is not None:
                w.close(batch_size=bs)
                state.rejects_path = rej_path
        state.consumed = True
        metrics.extras["feed"] = "batches"
        metrics.extras["batches"] = state.n_batches
        metrics.extras["lazy"] = True

    out_ds = DatasetHandle(producer=producer, batch_size=batch_size)
    # Placeholder metrics — runner refreshes from state after downstream pull.
    metrics = state.metrics
    metrics.extras["feed"] = "batches"
    metrics.extras["lazy"] = True
    metrics.extras["pending"] = True

    stream_datasets: dict[str, DatasetHandle] = {"out": out_ds}
    # Rejects handle resolves after consumption; expose a producer that waits
    # on the same pull by reading the spill path written during main iteration.
    def rejects_producer(bs: int):
        # Ensure main stream has been (or is being) pulled — if not, pull it.
        if not state.consumed:
            for _ in out_ds.iter_batches(bs):
                pass
        if state.rejects_path and state.rejects_path.exists():
            from formulaetl.sdk.spill import iter_jsonl_batches

            yield from iter_jsonl_batches(state.rejects_path, batch_size=bs)
        else:
            yield RowBatch(rows=[], batch_index=0, eof=True)

    rej_ds = DatasetHandle(producer=rejects_producer, batch_size=batch_size)
    stream_datasets["rejects"] = rej_ds

    result = ComponentResult(
        rows=[],
        rejects=[],
        metrics=metrics,
        streams={},
        dataset=out_ds,
        stream_datasets=stream_datasets,
    )
    # Stash state for the runner to harvest final metrics after the sink pulls.
    result.side_effects["_lazy_batch_state"] = state
    return result


def _run_batched_eager_small(
    component: Any,
    ctx: RunContext,
    dataset: DatasetHandle,
    batch_size: int,
) -> ComponentResult:
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
            for key, srows in cres.streams.items():
                streams.setdefault(key, []).extend(srows)
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


def harvest_lazy_metrics(result: ComponentResult) -> None:
    """Copy finalized lazy-chain metrics onto the ComponentResult after a pull."""
    state = result.side_effects.get("_lazy_batch_state")
    if not isinstance(state, _LazyBatchState):
        return
    if not state.consumed:
        return
    result.metrics = state.metrics
    result.side_effects.pop("_lazy_batch_state", None)
