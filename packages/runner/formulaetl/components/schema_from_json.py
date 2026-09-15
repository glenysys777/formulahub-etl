"""Schema from JSON — load JSON Schema or sample JSON and expose fields.

Downstream Schema Validate / Field Mapper can use the inferred column map
(via Discover, artifacts, or ``ctx.variables['target_schema']``).
"""

from __future__ import annotations

import json
from typing import Any

from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.registry import register


def _json_schema_type(prop: dict[str, Any]) -> str:
    t = prop.get("type")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), t[0] if t else "string")
    if t in ("integer", "int"):
        return "int"
    if t in ("number", "float", "double"):
        return "float"
    if t in ("boolean", "bool"):
        return "boolean"
    if t == "object":
        return "object"
    if t == "array":
        return "array"
    fmt = str(prop.get("format") or "")
    if fmt in ("date", "date-time", "email"):
        return "date" if fmt.startswith("date") else fmt
    return "string"


def columns_from_json_schema(schema: dict[str, Any]) -> dict[str, str]:
    """Flatten top-level JSON Schema properties → FormulaHub column types."""
    props = schema.get("properties")
    if not isinstance(props, dict):
        # $ref / items wrappers
        if isinstance(schema.get("items"), dict):
            return columns_from_json_schema(schema["items"])
        return {}
    out: dict[str, str] = {}
    for name, prop in props.items():
        if not isinstance(prop, dict):
            out[str(name)] = "string"
            continue
        if "properties" in prop and prop.get("type") in (None, "object"):
            # One-level nest: parent.child
            nested = columns_from_json_schema(prop)
            if nested:
                for nk, nv in nested.items():
                    out[f"{name}.{nk}"] = nv
            else:
                out[str(name)] = "object"
        else:
            out[str(name)] = _json_schema_type(prop)
    return out


def _infer_value_type(v: Any) -> str:
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int) and not isinstance(v, bool):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, dict):
        return "object"
    if isinstance(v, list):
        return "array"
    if isinstance(v, str):
        s = v.strip()
        if "@" in s and "." in s.split("@")[-1]:
            return "email"
        if len(s) == 10 and s[4] == "-" and s[7] == "-":
            return "date"
    return "string"


def columns_from_sample(data: Any) -> dict[str, str]:
    """Infer column→type from sample JSON (object, array of objects, or wrapped)."""
    if isinstance(data, list):
        rows = [x for x in data if isinstance(x, dict)]
        if not rows:
            return {"value": _infer_value_type(data[0]) if data else "string"}
        keys: dict[str, str] = {}
        for row in rows[:50]:
            for k, v in row.items():
                if str(k).startswith("_"):
                    continue
                if isinstance(v, dict):
                    for nk, nv in v.items():
                        keys.setdefault(f"{k}.{nk}", _infer_value_type(nv))
                else:
                    keys.setdefault(str(k), _infer_value_type(v))
        return keys
    if isinstance(data, dict):
        # Prefer common envelope keys
        for key in ("items", "data", "results", "records", "rows"):
            inner = data.get(key)
            if isinstance(inner, list) and inner and isinstance(inner[0], dict):
                return columns_from_sample(inner)
            if isinstance(inner, dict) and "items" in inner:
                return columns_from_sample(inner)
            if isinstance(inner, dict) and any(
                isinstance(v, (str, int, float, bool)) for v in inner.values()
            ):
                # data: { field: ... } single record
                if key == "data" and not any(
                    isinstance(v, (list, dict)) for v in inner.values()
                ):
                    return columns_from_sample(inner)
        # JSON Schema lookalike
        if "properties" in data and isinstance(data["properties"], dict):
            return columns_from_json_schema(data)
        out: dict[str, str] = {}
        for k, v in data.items():
            if str(k).startswith("_"):
                continue
            if isinstance(v, dict):
                for nk, nv in v.items():
                    out[f"{k}.{nk}"] = _infer_value_type(nv)
            else:
                out[str(k)] = _infer_value_type(v)
        return out
    return {"value": _infer_value_type(data)}


def load_schema_payload(
    *,
    content: str | None,
    path: Any | None,
    source_kind: str,
) -> tuple[dict[str, str], dict[str, Any]]:
    """Return (columns map, meta)."""
    raw: Any
    if content:
        raw = json.loads(content)
    elif path is not None:
        text = path.read_text(encoding="utf-8")
        raw = json.loads(text)
    else:
        raise ValueError("Schema from JSON: provide path or content")

    kind = (source_kind or "auto").lower()
    if kind == "json_schema" or (
        kind == "auto"
        and isinstance(raw, dict)
        and ("properties" in raw or raw.get("$schema") or raw.get("type") == "object")
        and not any(k in raw for k in ("data", "items", "results"))
    ):
        cols = columns_from_json_schema(raw) if isinstance(raw, dict) else {}
        if not cols and isinstance(raw, dict):
            cols = columns_from_sample(raw)
        return cols, {"source_kind": "json_schema"}
    cols = columns_from_sample(raw)
    return cols, {"source_kind": "sample"}


@register
class SchemaFromJSON(BaseComponent):
    component_type = "schema_from_json"
    display_name = "Schema from JSON"
    category = "quality"
    config_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "JSON Schema or sample JSON file"},
            "content": {"type": "string", "description": "Inline JSON Schema or sample"},
            "source_kind": {
                "type": "string",
                "enum": ["auto", "json_schema", "sample"],
                "default": "auto",
            },
            "pass_rows": {
                "type": "boolean",
                "default": True,
                "description": "Pass upstream rows through after loading schema",
            },
        },
    }
    parameters = [
        {
            "key": "path",
            "label": "Schema / sample path",
            "type": "string",
            "required": False,
            "help": "JSON Schema file or sample JSON (relative to workspace)",
        },
        {
            "key": "content",
            "label": "Inline JSON",
            "type": "string",
            "required": False,
            "help": "Paste JSON Schema or a sample object/array",
        },
        {
            "key": "source_kind",
            "label": "Source kind",
            "type": "select",
            "required": False,
            "default": "auto",
            "options": ["auto", "json_schema", "sample"],
            "help": "Treat input as JSON Schema, sample JSON, or auto-detect",
        },
        {
            "key": "pass_rows",
            "label": "Pass rows through",
            "type": "boolean",
            "required": False,
            "default": True,
            "help": "Forward upstream rows (schema is also stored for Validate / Field Mapper)",
        },
    ]

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            content = self.config.get("content")
            path = None
            if not content and self.config.get("path"):
                path = ctx.resolve(self.config["path"])
                if not path.exists():
                    raise FileNotFoundError(f"Schema from JSON: file not found: {path}")

            columns, meta = load_schema_payload(
                content=content,
                path=path,
                source_kind=str(self.config.get("source_kind") or "auto"),
            )
            if not columns:
                raise ValueError("Schema from JSON: no fields inferred from input")

            # Expose for Schema Validate / Field Mapper / Discover consumers.
            ctx.variables["target_schema"] = dict(columns)
            ctx.variables["discovered_schema"] = {
                "columns": [
                    {"name": k, "type": v, "nullable": True} for k, v in columns.items()
                ]
            }

            pass_rows = bool(self.config.get("pass_rows", True))
            out_rows = list(rows or []) if pass_rows else []
            metrics.rows_in = len(rows or [])
            metrics.rows_out = len(out_rows)
            metrics.extras["fields"] = len(columns)
            metrics.extras["source_kind"] = meta.get("source_kind")
            ctx.emit(
                f"Schema from JSON: {len(columns)} fields "
                f"({meta.get('source_kind')})"
            )

        return ComponentResult(
            rows=out_rows,
            metrics=metrics,
            side_effects={"columns": columns, **meta},
            artifacts={
                "columns": columns,
                "discovered_schema": {
                    "columns": [
                        {"name": k, "type": v, "nullable": True}
                        for k, v in columns.items()
                    ]
                },
            },
        )
