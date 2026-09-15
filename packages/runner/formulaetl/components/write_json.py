"""Write JSON — write row stream as a JSON array or JSON Lines file."""

from __future__ import annotations

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
        if (not str(k).startswith("_")) or k == "_reject_reason"
    }


def _apply_nest(row: dict[str, Any], nest: dict[str, list[str]]) -> dict[str, Any]:
    """Optional nesting: nest = { parent: [child_field, ...] } pulls flat keys under parent."""
    if not nest:
        return row
    out = dict(row)
    for parent, fields in nest.items():
        if not isinstance(fields, (list, tuple)):
            continue
        child: dict[str, Any] = {}
        for f in fields:
            key = str(f)
            if key in out:
                child[key] = out.pop(key)
        if child:
            existing = out.get(parent)
            if isinstance(existing, dict):
                out[parent] = {**existing, **child}
            else:
                out[parent] = child
    return out


def _parse_nest(raw: Any) -> dict[str, list[str]]:
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return {
            str(k): [str(x) for x in (v if isinstance(v, (list, tuple)) else [v])]
            for k, v in raw.items()
        }
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return _parse_nest(parsed)
        except json.JSONDecodeError:
            pass
        # Lines: parent=field1,field2
        out: dict[str, list[str]] = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or "=" not in line:
                continue
            parent, rest = line.split("=", 1)
            fields = [p.strip() for p in rest.split(",") if p.strip()]
            if fields:
                out[parent.strip()] = fields
        return out
    return {}


@register
class WriteJSON(BaseComponent):
    component_type = "write_json"
    display_name = "Write JSON"
    category = "destination"
    capabilities = STREAMING_SINK
    config_schema = {
        "type": "object",
        "required": ["path"],
        "properties": {
            "path": {"type": "string"},
            "mode": {
                "type": "string",
                "enum": ["array", "jsonl"],
                "default": "array",
                "description": "JSON array document or JSON Lines (one object per line)",
            },
            "pretty": {
                "type": "boolean",
                "default": True,
                "description": "Pretty-print when mode=array",
            },
            "encoding": {"type": "string", "default": "utf-8"},
            "nest": {
                "type": "object",
                "description": "Optional nest map: parent → list of flat field names",
            },
        },
    }
    parameters = [
        {
            "key": "path",
            "label": "Output path",
            "type": "string",
            "required": True,
            "help": "Destination JSON file path (relative to workspace)",
        },
        {
            "key": "mode",
            "label": "Mode",
            "type": "select",
            "required": False,
            "default": "array",
            "options": ["array", "jsonl"],
            "help": "JSON array or JSON Lines",
        },
        {
            "key": "pretty",
            "label": "Pretty print",
            "type": "boolean",
            "required": False,
            "default": True,
            "help": "Indent JSON array output",
        },
        {
            "key": "encoding",
            "label": "Encoding",
            "type": "string",
            "required": False,
            "default": "utf-8",
            "help": "Text encoding",
        },
        {
            "key": "nest",
            "label": "Nest map",
            "type": "string",
            "required": False,
            "help": "Optional nesting: JSON object or lines parent=field1,field2",
        },
    ]

    def consume_dataset(self, ctx: RunContext, dataset: DatasetHandle) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            path, mode, pretty, encoding, nest = self._opts(ctx)
            path.parent.mkdir(parents=True, exist_ok=True)
            n_in = 0
            n_batches = 0

            if mode == "jsonl":
                with path.open("w", encoding=encoding) as f:
                    for batch in dataset.iter_batches(getattr(ctx, "batch_size", None)):
                        n_batches += 1
                        for r in batch.rows:
                            n_in += 1
                            obj = _apply_nest(_clean_row(r), nest)
                            f.write(json.dumps(obj, default=str))
                            f.write("\n")
            else:
                rows = dataset.materialize()
                clean = [_apply_nest(_clean_row(r), nest) for r in rows]
                n_in = len(rows)
                n_batches = 1
                indent = 2 if pretty else None
                path.write_text(
                    json.dumps(clean, indent=indent, default=str),
                    encoding=encoding,
                )

            metrics.rows_in = n_in
            metrics.rows_out = n_in
            metrics.extras["feed"] = "batches"
            metrics.extras["batches"] = n_batches
            metrics.extras["mode"] = mode
            ctx.emit(f"WriteJSON: wrote {n_in} rows → {path} ({mode})")

        return ComponentResult(
            rows=[],
            metrics=metrics,
            side_effects={"written_path": str(path), "format": "json", "mode": mode},
            artifacts={"path": str(path)},
        )

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            rows = rows or []
            path, mode, pretty, encoding, nest = self._opts(ctx)
            path.parent.mkdir(parents=True, exist_ok=True)
            clean = [_apply_nest(_clean_row(r), nest) for r in rows]

            if mode == "jsonl":
                with path.open("w", encoding=encoding) as f:
                    for obj in clean:
                        f.write(json.dumps(obj, default=str))
                        f.write("\n")
            else:
                indent = 2 if pretty else None
                path.write_text(
                    json.dumps(clean, indent=indent, default=str),
                    encoding=encoding,
                )

            metrics.rows_in = len(rows)
            metrics.rows_out = len(rows)
            metrics.extras["mode"] = mode
            ctx.emit(f"WriteJSON: wrote {len(rows)} rows → {path} ({mode})")

        return ComponentResult(
            rows=[],
            metrics=metrics,
            side_effects={"written_path": str(path), "format": "json", "mode": mode},
            artifacts={"path": str(path)},
        )

    def _opts(self, ctx: RunContext) -> tuple[Any, str, bool, str, dict[str, list[str]]]:
        path = ctx.resolve(self.config["path"])
        mode = str(self.config.get("mode") or "array").lower()
        if mode not in ("array", "jsonl"):
            mode = "array"
        pretty = bool(self.config.get("pretty", True))
        encoding = str(self.config.get("encoding") or "utf-8")
        nest = _parse_nest(self.config.get("nest"))
        return path, mode, pretty, encoding, nest
