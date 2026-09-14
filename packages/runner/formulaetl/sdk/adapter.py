"""Adapters between DatasetHandle / ArtifactHandle and legacy list[dict] + bytes.

Existing components that still implement ``run(ctx, rows: list[dict])`` keep
working. File nodes that expose a local path no longer receive whole-object
``bytes`` copies in ``config``.

Phase Perf: ``run_batched`` spills large outputs to JSONL so hops do not
concatenate full ``list[dict]`` working sets in RAM (Talend-style OOM avoidance).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from formulaetl.sdk.capabilities import ComponentCapabilities
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.data import ArtifactHandle, DatasetHandle, DEFAULT_BATCH_SIZE
from formulaetl.sdk.spill import (
    SPILL_THRESHOLD,
    JsonlSpillWriter,
    new_spill_path,
    spill_enabled,
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
    """Call ``run`` once per RowBatch; spill outputs when large.

    Input to each ``run`` is bounded. When ``FORMULAETL_STREAM_SPILL`` is on
    (default), outputs go to JSONL under the run temp dir instead of a full
    in-RAM concat — avoids Talend-style OOM on multi-hop wedges.
    """
    use_spill = spill_enabled()
    # Prefer consume_dataset when the component implements a true streaming sink.
    consume = getattr(component, "consume_dataset", None)
    if callable(consume):
        cres = consume(ctx, dataset)
        if "feed" not in cres.metrics.extras:
            cres.metrics.extras["feed"] = "batches"
        return cres

    out_rows: list[dict[str, Any]] = []
    out_rejects: list[dict[str, Any]] = []
    streams: dict[str, list[dict[str, Any]]] = {}
    side_effects: dict[str, Any] = {}
    artifacts: dict[str, Any] = {}
    artifact: ArtifactHandle | None = None
    metrics = Metrics()
    n_batches = 0

    spill_dir = ctx.temp_dir() / "spill"
    out_writer: JsonlSpillWriter | None = None
    rej_writer: JsonlSpillWriter | None = None
    stream_writers: dict[str, JsonlSpillWriter] = {}

    if use_spill:
        out_writer = JsonlSpillWriter(new_spill_path(spill_dir, "out"))
        rej_writer = JsonlSpillWriter(new_spill_path(spill_dir, "rej"))

    with timed(metrics):
        for batch in dataset.iter_batches(batch_size):
            n_batches += 1
            cres = component.run(ctx, list(batch.rows))
            if use_spill and out_writer is not None and rej_writer is not None:
                out_writer.write_rows(cres.rows)
                rej_writer.write_rows(cres.rejects)
                for key, srows in cres.streams.items():
                    if key in ("out", "rejects"):
                        continue
                    if key not in stream_writers:
                        stream_writers[key] = JsonlSpillWriter(
                            new_spill_path(spill_dir, key)
                        )
                    stream_writers[key].write_rows(srows)
            else:
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

    stream_datasets: dict[str, DatasetHandle] = {}
    dataset_out: DatasetHandle

    if use_spill and out_writer is not None and rej_writer is not None:
        metrics.extras["spill"] = True
        dataset_out = out_writer.close(batch_size=batch_size)
        rej_ds = rej_writer.close(batch_size=batch_size)
        stream_datasets["out"] = dataset_out
        if rej_writer.row_count:
            stream_datasets["rejects"] = rej_ds
        for key, writer in stream_writers.items():
            stream_datasets[key] = writer.close(batch_size=batch_size)

        # Small results: keep list adapter for unit tests / Studio previews.
        if metrics.rows_out <= SPILL_THRESHOLD:
            out_rows = dataset_out.materialize()
            dataset_out = DatasetHandle.from_rows(out_rows, batch_size=batch_size)
            stream_datasets["out"] = dataset_out
        else:
            out_rows = []

        if metrics.rows_rejected <= SPILL_THRESHOLD and "rejects" in stream_datasets:
            out_rejects = stream_datasets["rejects"].materialize()
        elif metrics.rows_rejected > SPILL_THRESHOLD:
            out_rejects = []

        if out_rows:
            streams = {"out": out_rows}
        if out_rejects:
            streams["rejects"] = out_rejects
    else:
        dataset_out = DatasetHandle.from_rows(out_rows, batch_size=batch_size)
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
        dataset=dataset_out,
        artifact=artifact,
        stream_datasets=stream_datasets,
    )
