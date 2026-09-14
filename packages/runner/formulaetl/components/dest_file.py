"""Local File Destination — write CSV/JSON.

Supports ``consume_dataset`` so large inputs stream to disk without a full
``list[dict]`` materialization.
"""

from __future__ import annotations

import csv
import json
from typing import Any

from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.capabilities import STREAMING_SINK
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.data import DatasetHandle
from formulaetl.sdk.registry import register


def _clean_row(r: dict[str, Any]) -> dict[str, Any]:
    return {
        k: v
        for k, v in r.items()
        if (not k.startswith("_")) or k == "_reject_reason"
    }


@register
class LocalFileDestination(BaseComponent):
    component_type = "local_file_destination"
    display_name = "Local File Destination"
    category = "destination"
    capabilities = STREAMING_SINK
    config_schema = {
        "type": "object",
        "required": ["path"],
        "properties": {
            "path": {"type": "string"},
            "format": {"type": "string", "enum": ["csv", "json"], "default": "csv"},
            "encoding": {"type": "string", "default": "utf-8"},
        },
    }
    parameters = [
        {"key": "path", "label": "Output path", "type": "string", "required": True, "help": "Destination file path"},
        {"key": "format", "label": "Format", "type": "select", "required": False, "default": "csv", "options": ["csv", "json"], "help": "Output format"},
        {"key": "encoding", "label": "Encoding", "type": "string", "required": False, "default": "utf-8", "help": "Text encoding"},
    ]

    def consume_dataset(self, ctx: RunContext, dataset: DatasetHandle) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            path = ctx.resolve(self.config["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            fmt = self.config.get("format", "csv")
            encoding = self.config.get("encoding", "utf-8")
            n_in = 0
            n_batches = 0

            if fmt == "json":
                # JSON array still needs a full list for valid document shape;
                # stream via spill materialize only when format forces it.
                rows = dataset.materialize()
                clean = [_clean_row(r) for r in rows]
                path.write_text(json.dumps(clean, indent=2, default=str), encoding=encoding)
                n_in = len(rows)
                n_batches = 1
            else:
                fieldnames: list[str] | None = None
                with path.open("w", newline="", encoding=encoding) as f:
                    writer: csv.DictWriter | None = None
                    for batch in dataset.iter_batches(getattr(ctx, "batch_size", None)):
                        n_batches += 1
                        clean = [_clean_row(r) for r in batch.rows]
                        n_in += len(batch.rows)
                        if not clean:
                            continue
                        if writer is None:
                            fieldnames = list(clean[0].keys())
                            for r in clean[1:]:
                                for k in r:
                                    if k not in fieldnames:
                                        fieldnames.append(k)
                            writer = csv.DictWriter(
                                f, fieldnames=fieldnames, extrasaction="ignore"
                            )
                            writer.writeheader()
                        writer.writerows(clean)

            metrics.rows_in = n_in
            metrics.rows_out = n_in
            metrics.extras["feed"] = "batches"
            metrics.extras["batches"] = n_batches
            ctx.emit(f"LocalFileDestination: wrote {n_in} rows → {path}")

        return ComponentResult(
            rows=[],
            metrics=metrics,
            side_effects={"written_path": str(path), "format": fmt},
            artifacts={"path": str(path)},
        )

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            rows = rows or []
            path = ctx.resolve(self.config["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            fmt = self.config.get("format", "csv")
            encoding = self.config.get("encoding", "utf-8")
            clean = [_clean_row(r) for r in rows]

            if fmt == "json":
                path.write_text(json.dumps(clean, indent=2, default=str), encoding=encoding)
            else:
                if clean:
                    fieldnames = list(clean[0].keys())
                    for r in clean[1:]:
                        for k in r:
                            if k not in fieldnames:
                                fieldnames.append(k)
                else:
                    fieldnames = []
                with path.open("w", newline="", encoding=encoding) as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(clean)

            metrics.rows_in = len(rows)
            metrics.rows_out = len(rows)
            ctx.emit(f"LocalFileDestination: wrote {len(rows)} rows → {path}")

        return ComponentResult(
            rows=[],
            metrics=metrics,
            side_effects={"written_path": str(path), "format": fmt},
            artifacts={"path": str(path)},
        )
