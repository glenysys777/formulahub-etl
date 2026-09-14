"""CSV Parser — streaming/chunked parse with malformed-row policy (Phase C)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.capabilities import TABULAR_FROM_FILE
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.data import DatasetHandle
from formulaetl.sdk.registry import register


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

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            batch_size = getattr(ctx, "batch_size", None) or 1024
            opts = self._opts()
            rejects: list[dict[str, Any]] = []

            path = self._input_path(ctx)
            if path is not None:
                dataset = DatasetHandle.from_csv_path(
                    path,
                    batch_size=batch_size,
                    rejects_out=rejects,
                    **opts,
                )
                # Adapter still materializes for legacy downstream nodes;
                # iteration itself is chunked via RowBatch producer.
                out_rows = dataset.materialize()
                metrics.rows_in = 1
                metrics.rows_out = len(out_rows)
                metrics.rows_rejected = len(rejects)
                ctx.emit(
                    f"CSVParser: parsed {len(out_rows)} rows from {path} "
                    f"({len(rejects)} rejected, batch_size={batch_size})"
                )
                return ComponentResult(
                    rows=out_rows,
                    rejects=rejects,
                    metrics=metrics,
                    dataset=DatasetHandle.from_rows(out_rows, batch_size=batch_size),
                    streams={"out": out_rows, "rejects": rejects} if rejects else {"out": out_rows},
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
                # If upstream already produced row dicts with CSV-like data, pass through
                if all(not k.startswith("_") for r in rows for k in r):
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

            dataset = DatasetHandle.from_csv_text(
                content if isinstance(content, str) else str(content),
                batch_size=batch_size,
                rejects_out=rejects,
                **opts,
            )
            out_rows = dataset.materialize()
            metrics.rows_in = 1
            metrics.rows_out = len(out_rows)
            metrics.rows_rejected = len(rejects)
            ctx.emit(
                f"CSVParser: parsed {len(out_rows)} rows ({len(rejects)} rejected)"
            )

        return ComponentResult(
            rows=out_rows,
            rejects=rejects,
            metrics=metrics,
            dataset=DatasetHandle.from_rows(out_rows, batch_size=batch_size),
            streams={"out": out_rows, "rejects": rejects} if rejects else {"out": out_rows},
        )
