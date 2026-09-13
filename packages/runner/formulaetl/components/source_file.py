"""Local file / FileSource — read CSV/JSON/bytes from disk."""

from __future__ import annotations

from typing import Any

from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.registry import register


@register
class LocalFileSource(BaseComponent):
    component_type = "local_file_source"
    display_name = "Local File Source"
    category = "source"
    config_schema = {
        "type": "object",
        "required": ["path"],
        "properties": {
            "path": {"type": "string", "description": "File path relative to work_dir"},
            "format": {"type": "string", "enum": ["auto", "csv", "json", "bytes"], "default": "auto"},
            "encoding": {"type": "string", "default": "utf-8"},
        },
    }
    parameters = [
        {"key": "path", "label": "File path", "type": "string", "required": True, "help": "File path relative to work_dir"},
        {"key": "format", "label": "Format", "type": "select", "required": False, "default": "auto", "options": ["auto", "csv", "json", "bytes"], "help": "Input format"},
        {"key": "encoding", "label": "Encoding", "type": "string", "required": False, "default": "utf-8", "help": "Text encoding"},
    ]

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            path = ctx.resolve(self.config["path"])
            if not path.exists():
                raise FileNotFoundError(f"LocalFileSource: file not found: {path}")

            fmt = self.config.get("format", "auto")
            if fmt == "auto":
                suffix = path.suffix.lower()
                if suffix == ".csv":
                    fmt = "csv"
                elif suffix == ".json":
                    fmt = "json"
                else:
                    fmt = "bytes"

            encoding = self.config.get("encoding", "utf-8")
            raw = path.read_bytes()
            ctx.emit(f"LocalFileSource: read {path} ({len(raw)} bytes, format={fmt})")

            out_rows: list[dict[str, Any]] = []
            artifacts: dict[str, Any] = {"path": str(path), "bytes": raw}

            if fmt == "csv":
                import csv
                import io

                text = raw.decode(encoding)
                reader = csv.DictReader(io.StringIO(text))
                out_rows = [dict(r) for r in reader]
                artifacts["content"] = text
            elif fmt == "json":
                import json

                data = json.loads(raw.decode(encoding))
                if isinstance(data, list):
                    out_rows = data
                else:
                    out_rows = [data]
                artifacts["content"] = raw.decode(encoding)
            else:
                # Pass through as artifact for downstream decrypt/parse
                out_rows = [{"_path": str(path), "_size": len(raw)}]

            metrics.rows_in = 0
            metrics.rows_out = len(out_rows) if fmt != "bytes" else 1

        return ComponentResult(rows=out_rows, metrics=metrics, artifacts=artifacts)


# Alias
FileSource = LocalFileSource
