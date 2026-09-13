"""CSV Parser — parse CSV bytes/text to records."""

from __future__ import annotations

import csv
import io
from typing import Any

from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.registry import register


@register
class CSVParser(BaseComponent):
    component_type = "csv_parser"
    display_name = "CSV Parser"
    category = "transform"
    config_schema = {
        "type": "object",
        "properties": {
            "delimiter": {"type": "string", "default": ","},
            "encoding": {"type": "string", "default": "utf-8"},
            "content": {"type": "string", "description": "Inline CSV text (or from upstream)"},
        },
    }
    parameters = [
        {"key": "delimiter", "label": "Delimiter", "type": "string", "required": False, "default": ",", "help": "CSV field delimiter"},
        {"key": "encoding", "label": "Encoding", "type": "string", "required": False, "default": "utf-8", "help": "Text encoding"},
        {"key": "content", "label": "Inline content", "type": "string", "required": False, "help": "Inline CSV text (or from upstream)"},
    ]

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            content = self.config.get("content")
            if content is None and "bytes" in self.config:
                content = self.config["bytes"]
                if isinstance(content, bytes):
                    content = content.decode(self.config.get("encoding", "utf-8"))
            if content is None and ctx.variables.get("upstream_content"):
                content = ctx.variables["upstream_content"]
            if content is None and ctx.variables.get("upstream_bytes"):
                b = ctx.variables["upstream_bytes"]
                content = b.decode(self.config.get("encoding", "utf-8")) if isinstance(b, bytes) else b
            if content is None and rows:
                # If upstream already produced row dicts with CSV-like data, pass through
                # Or look for _content field
                if all(not k.startswith("_") for r in rows for k in r):
                    metrics.rows_in = len(rows)
                    metrics.rows_out = len(rows)
                    return ComponentResult(rows=list(rows), metrics=metrics)
                raise ValueError("CSVParser: no CSV content available")
            if content is None:
                raise ValueError("CSVParser: no CSV content available")

            delimiter = self.config.get("delimiter", ",")
            reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
            out_rows = [dict(r) for r in reader]
            metrics.rows_in = 1
            metrics.rows_out = len(out_rows)
            ctx.emit(f"CSVParser: parsed {len(out_rows)} rows")

        return ComponentResult(rows=out_rows, metrics=metrics)
