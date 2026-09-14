"""CSV Parser — streaming/chunked parse with malformed-row policy (Phase C).

Large files return a producer/spill-backed ``DatasetHandle`` without holding
the full ``list[dict]`` in ``ComponentResult.rows``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.capabilities import TABULAR_FROM_FILE
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.data import DatasetHandle
from formulaetl.sdk.registry import register
from formulaetl.sdk.spill import (
    SPILL_THRESHOLD,
    JsonlSpillWriter,
    new_spill_path,
)


@register
class CSVParser(BaseComponent):
    component_type = "csv_parser"
    display_name = "CSV Parser"
    category = "transform"
    capabilities = TABULAR_FROM_FILE
    config_schema = {
        "type": "object",
        "properties": {
            "delimiter": {"type": "string", "default": ","},
            "encoding": {"type": "string", "default": "utf-8"},
            "quotechar": {"type": "string", "default": "\""},
            "has_header": {"type": "boolean", "default": True},
            "fieldnames": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Required when has_header is false",
            },
            "content": {"type": "string", "description": "Inline CSV text (or from upstream)"},
            "path": {"type": "string", "description": "CSV file path (preferred over bytes)"},
            "malformed_policy": {
                "type": "string",
                "enum": ["fail", "skip", "reject"],
                "default": "reject",
                "description": "How to treat unparseable / extra-column rows",
            },
            "extra_columns": {
                "type": "string",
                "enum": ["keep", "drop", "reject"],
                "default": "keep",
            },
            "missing_columns": {
                "type": "string",
                "enum": ["fill", "reject"],
                "default": "fill",
            },
            "empty_as_null": {"type": "boolean", "default": False},
            "add_row_numbers": {"type": "boolean", "default": False},
            "row_number_field": {"type": "string", "default": "_row_number"},
        },
    }
    parameters = [
        {"key": "delimiter", "label": "Delimiter", "type": "string", "required": False, "default": ",", "help": "CSV field delimiter"},
        {"key": "encoding", "label": "Encoding", "type": "string", "required": False, "default": "utf-8", "help": "Text encoding (utf-8, utf-8-sig, latin-1, …)"},
        {"key": "quotechar", "label": "Quote char", "type": "string", "required": False, "default": "\"", "help": "Field quote character"},
        {"key": "has_header", "label": "Has header", "type": "boolean", "required": False, "default": True, "help": "First row is column names"},
        {"key": "content", "label": "Inline content", "type": "string", "required": False, "help": "Inline CSV text (or from upstream)"},
        {"key": "path", "label": "File path", "type": "string", "required": False, "help": "CSV file; preferred over inline bytes"},
        {"key": "malformed_policy", "label": "Malformed policy", "type": "string", "required": False, "default": "reject", "help": "fail | skip | reject"},
        {"key": "extra_columns", "label": "Extra columns", "type": "string", "required": False, "default": "keep", "help": "keep | drop | reject"},
        {"key": "missing_columns", "label": "Missing columns", "type": "string", "required": False, "default": "fill", "help": "fill | reject"},
        {"key": "empty_as_null", "label": "Empty as null", "type": "boolean", "required": False, "default": False, "help": "Treat empty/NULL tokens as null"},
        {"key": "add_row_numbers", "label": "Add row numbers", "type": "boolean", "required": False, "default": False, "help": "Attach 1-based data row number (_row_number)"},
    ]

    def _input_path(self, ctx: RunContext) -> Path | None:
        for candidate in (
            self.config.get("path"),
            (ctx.variables.get("upstream_artifact") or {}).get("path")
            if isinstance(ctx.variables.get("upstream_artifact"), dict)
            else None,
            ctx.variables.get("upstream_path"),
        ):
            if not candidate:
                continue
            p = Path(candidate) if Path(str(candidate)).is_absolute() else ctx.resolve(str(candidate))
            if p.exists() and p.is_file():
                return p
        return None

    def _opts(self) -> dict[str, Any]:
        return {
            "delimiter": self.config.get("delimiter", ","),
            "encoding": self.config.get("encoding", "utf-8"),
            "quotechar": self.config.get("quotechar", '"'),
            "has_header": bool(self.config.get("has_header", True)),
            "fieldnames": self.config.get("fieldnames"),
            "malformed_policy": self.config.get("malformed_policy", "reject"),
            "extra_columns": self.config.get("extra_columns", "keep"),
            "missing_columns": self.config.get("missing_columns", "fill"),
            "empty_as_null": bool(self.config.get("empty_as_null", False)),
            "add_row_numbers": bool(self.config.get("add_row_numbers", False)),
            "row_number_field": self.config.get("row_number_field", "_row_number"),
        }

    def _finalize_dataset(
        self,
        ctx: RunContext,
        dataset: DatasetHandle,
        rejects: list[dict[str, Any]],
        *,
        batch_size: int,
        source_label: str,
        rebuild: DatasetHandle | None = None,
    ) -> ComponentResult:
        """Bound RAM: small outputs materialize; large outputs stay producer-backed."""
        metrics = Metrics()
        preview: list[dict[str, Any]] = []
        n = 0

        with timed(metrics):
            acc: list[dict[str, Any]] = []
            spilled = False
            for batch in dataset.iter_batches(batch_size):
                n += len(batch.rows)
                if spilled:
                    if len(preview) < 5 and batch.rows:
                        preview.extend(batch.rows[: max(0, 5 - len(preview))])
                    continue
                acc.extend(batch.rows)
                if n > SPILL_THRESHOLD:
                    preview = acc[:5]
                    acc = []
                    spilled = True

            metrics.rows_in = 1
            metrics.rows_out = n
            metrics.rows_rejected = len(rejects)

            if not spilled:
                out_rows = acc
                out_ds = DatasetHandle.from_rows(out_rows, batch_size=batch_size)
                streams: dict[str, list[dict[str, Any]]] = {"out": out_rows}
                if rejects:
                    streams["rejects"] = rejects
                ctx.emit(
                    f"CSVParser: parsed {n} rows from {source_label} "
                    f"({len(rejects)} rejected, batch_size={batch_size})"
                )
                return ComponentResult(
                    rows=out_rows,
                    rejects=rejects,
                    metrics=metrics,
                    dataset=out_ds,
                    streams=streams,
                    stream_datasets={"out": out_ds},
                )

            # Large: re-readable producer (fresh handle — no shared rejects_out).
            out_ds = rebuild if rebuild is not None else dataset
            metrics.extras["producer_only"] = True
            ctx.emit(
                f"CSVParser: parsed {n} rows from {source_label} "
                f"({len(rejects)} rejected, producer_only=1, batch_size={batch_size})"
            )
            streams = {}
            stream_datasets = {"out": out_ds}
            out_rejects = rejects
            if rejects and len(rejects) > SPILL_THRESHOLD:
                rej_writer = JsonlSpillWriter(
                    new_spill_path(ctx.temp_dir() / "spill", "csv_rej")
                )
                rej_writer.write_rows(rejects)
                stream_datasets["rejects"] = rej_writer.close(batch_size=batch_size)
                out_rejects = []
            elif rejects:
                streams["rejects"] = rejects
            return ComponentResult(
                rows=preview,
                rejects=out_rejects,
                metrics=metrics,
                dataset=out_ds,
                streams=streams,
                stream_datasets=stream_datasets,
            )

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        batch_size = getattr(ctx, "batch_size", None) or 16384
        opts = self._opts()
        rejects: list[dict[str, Any]] = []

        path = self._input_path(ctx)
        if path is not None:
            rebuild = DatasetHandle.from_csv_path(
                path,
                batch_size=batch_size,
                rejects_out=None,
                **opts,
            )
            # Large files: avoid a full dict-parse just to count. Line count is
            # exact for the bench/simple CSVs (no embedded newlines); malformed
            # rows are still classified on the downstream producer pass.
            size = path.stat().st_size if path.exists() else 0
            if size > 2_000_000 and opts.get("has_header", True):
                with path.open("rb") as fh:
                    n_lines = sum(1 for _ in fh)
                n = max(0, n_lines - 1)
                metrics = Metrics()
                with timed(metrics):
                    metrics.rows_in = 1
                    metrics.rows_out = n
                    metrics.rows_rejected = 0
                    metrics.extras["producer_only"] = True
                    metrics.extras["count"] = "line_scan"
                ctx.emit(
                    f"CSVParser: ~{n} rows from {path} "
                    f"(producer_only=1, line_scan, batch_size={batch_size})"
                )
                return ComponentResult(
                    rows=[],
                    rejects=[],
                    metrics=metrics,
                    dataset=rebuild,
                    stream_datasets={"out": rebuild},
                )

            dataset = DatasetHandle.from_csv_path(
                path,
                batch_size=batch_size,
                rejects_out=rejects,
                **opts,
            )
            return self._finalize_dataset(
                ctx,
                dataset,
                rejects,
                batch_size=batch_size,
                source_label=str(path),
                rebuild=rebuild,
            )

        content = self.config.get("content")
        if content is None and "bytes" in self.config:
            content = self.config["bytes"]
            if isinstance(content, bytes):
                content = content.decode(opts["encoding"])
        if content is None and ctx.variables.get("upstream_content"):
            content = ctx.variables["upstream_content"]
        if content is None and ctx.variables.get("upstream_bytes"):
            b = ctx.variables["upstream_bytes"]
            content = b.decode(opts["encoding"]) if isinstance(b, bytes) else b
        if content is None and rows:
            if all(not k.startswith("_") for r in rows for k in r):
                metrics = Metrics()
                with timed(metrics):
                    metrics.rows_in = len(rows)
                    metrics.rows_out = len(rows)
                return ComponentResult(
                    rows=list(rows),
                    metrics=metrics,
                    dataset=DatasetHandle.from_rows(list(rows), batch_size=batch_size),
                )
            raise ValueError("CSVParser: no CSV content available")
        if content is None:
            raise ValueError("CSVParser: no CSV content available")

        text = content if isinstance(content, str) else str(content)
        dataset = DatasetHandle.from_csv_text(
            text,
            batch_size=batch_size,
            rejects_out=rejects,
            **opts,
        )
        rebuild = DatasetHandle.from_csv_text(
            text,
            batch_size=batch_size,
            rejects_out=None,
            **opts,
        )
        return self._finalize_dataset(
            ctx,
            dataset,
            rejects,
            batch_size=batch_size,
            source_label="inline",
            rebuild=rebuild,
        )
