"""CSV Parser — parse CSV bytes/text/file to records (stream from path when possible)."""

from __future__ import annotations

import csv
import io
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
            "content": {"type": "string", "description": "Inline CSV text (or from upstream)"},
            "path": {"type": "string", "description": "CSV file path (preferred over bytes)"},
        },
    }
    parameters = [
        {"key": "delimiter", "label": "Delimiter", "type": "string", "required": False, "default": ",", "help": "CSV field delimiter"},
        {"key": "encoding", "label": "Encoding", "type": "string", "required": False, "default": "utf-8", "help": "Text encoding"},
        {"key": "content", "label": "Inline content", "type": "string", "required": False, "help": "Inline CSV text (or from upstream)"},
        {"key": "path", "label": "File path", "type": "string", "required": False, "help": "CSV file; preferred over inline bytes"},
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

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            delimiter = self.config.get("delimiter", ",")
            encoding = self.config.get("encoding", "utf-8")
            batch_size = getattr(ctx, "batch_size", None) or 1024

            path = self._input_path(ctx)
            if path is not None:
                dataset = DatasetHandle.from_csv_path(
                    path,
                    delimiter=delimiter,
                    encoding=encoding,
                    batch_size=batch_size,
                )
                out_rows = dataset.materialize()
                metrics.rows_in = 1
                metrics.rows_out = len(out_rows)
                ctx.emit(f"CSVParser: parsed {len(out_rows)} rows from {path}")
                return ComponentResult(
                    rows=out_rows,
                    metrics=metrics,
                    dataset=DatasetHandle.from_rows(out_rows, batch_size=batch_size),
                )

            content = self.config.get("content")
            if content is None and "bytes" in self.config:
                content = self.config["bytes"]
                if isinstance(content, bytes):
                    content = content.decode(encoding)
            if content is None and ctx.variables.get("upstream_content"):
                content = ctx.variables["upstream_content"]
            if content is None and ctx.variables.get("upstream_bytes"):
                b = ctx.variables["upstream_bytes"]
                content = b.decode(encoding) if isinstance(b, bytes) else b
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

            reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
            out_rows = [dict(r) for r in reader]
            metrics.rows_in = 1
            metrics.rows_out = len(out_rows)
            ctx.emit(f"CSVParser: parsed {len(out_rows)} rows")

        return ComponentResult(
            rows=out_rows,
            metrics=metrics,
            dataset=DatasetHandle.from_rows(out_rows, batch_size=batch_size),
        )
