"""JSON Parser — parse JSON array/object/file content into row dicts."""

from __future__ import annotations

import json
from typing import Any

from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.registry import register


def _dig(data: Any, path: str | None) -> Any:
    if not path:
        return data
    cur = data
    for part in path.replace("[", ".").replace("]", "").split("."):
        if part == "":
            continue
        if isinstance(cur, dict):
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit():
            cur = cur[int(part)]
        else:
            raise KeyError(f"json_path '{path}' unresolved at '{part}'")
    return cur


@register
class JSONParser(BaseComponent):
    component_type = "json_parser"
    display_name = "JSON Parser"
    category = "transform"
    config_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Optional JSON file path"},
            "content": {"type": "string", "description": "Inline JSON text"},
            "json_path": {
                "type": "string",
                "description": "Dot path to array/object, e.g. data.items",
            },
        },
    }
    parameters = [
        {
            "key": "path",
            "label": "JSON file path",
            "type": "string",
            "required": False,
            "help": "Read JSON from this file (relative to work_dir)",
        },
        {
            "key": "content",
            "label": "Inline JSON",
            "type": "string",
            "required": False,
            "help": "Inline JSON text (or use upstream bytes/content)",
        },
        {
            "key": "json_path",
            "label": "JSON path",
            "type": "string",
            "required": False,
            "help": "Dot path to rows array, e.g. data.items",
        },
    ]

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            data: Any = None
            content: str | None = self.config.get("content")

            if content is None and self.config.get("path"):
                p = ctx.resolve(self.config["path"])
                if not p.exists():
                    raise FileNotFoundError(f"JSONParser: file not found: {p}")
                content = p.read_text(encoding="utf-8")

            if content is None and ctx.variables.get("upstream_content"):
                content = ctx.variables["upstream_content"]
            if content is None and ctx.variables.get("upstream_bytes"):
                b = ctx.variables["upstream_bytes"]
                content = b.decode("utf-8") if isinstance(b, bytes) else str(b)

            if content is None and rows:
                if len(rows) == 1 and isinstance(rows[0].get("_json"), (dict, list)):
                    data = rows[0]["_json"]
                elif len(rows) == 1 and isinstance(rows[0].get("content"), str):
                    content = rows[0]["content"]
                elif all(isinstance(r, dict) for r in rows) and all(
                    not any(str(k).startswith("_") for k in r) for r in rows
                ):
                    metrics.rows_in = len(rows)
                    metrics.rows_out = len(rows)
                    return ComponentResult(rows=list(rows), metrics=metrics)

            if data is None:
                if content is None:
                    raise ValueError("JSONParser: no JSON content available")
                data = json.loads(content)

            extracted = _dig(data, self.config.get("json_path"))
            if isinstance(extracted, list):
                out_rows = [
                    dict(x) if isinstance(x, dict) else {"value": x} for x in extracted
                ]
            elif isinstance(extracted, dict):
                out_rows = [dict(extracted)]
            else:
                out_rows = [{"value": extracted}]

            metrics.rows_in = 1
            metrics.rows_out = len(out_rows)
            ctx.emit(f"JSONParser: parsed {len(out_rows)} rows")

        return ComponentResult(rows=out_rows, metrics=metrics)
