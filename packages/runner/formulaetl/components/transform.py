"""Transform — rename, cast date, map fields via config."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.capabilities import ROWWISE
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.registry import register


def _cast_date(value: Any, in_fmt: str, out_fmt: str) -> str:
    if value is None or value == "":
        return ""
    s = str(value).strip()
    for fmt in (in_fmt, "%Y-%m-%d", "%m/%d/%Y", "%d-%m-%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).strftime(out_fmt)
        except ValueError:
            continue
    return s  # leave as-is if unparseable


@register
class Transform(BaseComponent):
    component_type = "transform"
    display_name = "Transform"
    category = "transform"
    capabilities = ROWWISE
    config_schema = {
        "type": "object",
        "properties": {
            "rename": {
                "type": "object",
                "description": "Map old_name → new_name",
            },
            "cast": {
                "type": "object",
                "description": "Map column → {type, input_format?, output_format?}",
            },
            "map": {
                "type": "object",
                "description": "Map new_field → source_field (copy/alias)",
            },
            "drop": {
                "type": "array",
                "items": {"type": "string"},
            },
            "add_constants": {
                "type": "object",
                "description": "Constant fields to add to every row",
            },
        },
    }
    parameters = [
        {"key": "rename", "label": "Rename map", "type": "string", "required": False, "help": "JSON map old_name → new_name"},
        {"key": "cast", "label": "Cast rules", "type": "string", "required": False, "help": "JSON map column → type or {type, formats}"},
        {"key": "map", "label": "Field map", "type": "string", "required": False, "help": "JSON map new_field → source_field"},
        {"key": "drop", "label": "Drop columns", "type": "string_list", "required": False, "help": "Columns to drop"},
        {"key": "add_constants", "label": "Constants", "type": "string", "required": False, "help": "JSON map of constant fields to add"},
    ]

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            rows = rows or []
            rename: dict[str, str] = self.config.get("rename") or {}
            cast_cfg: dict[str, Any] = self.config.get("cast") or {}
            field_map: dict[str, str] = self.config.get("map") or {}
            drop = set(self.config.get("drop") or [])
            constants: dict[str, Any] = self.config.get("add_constants") or {}

            out: list[dict[str, Any]] = []
            for row in rows:
                new_row = dict(row)

                # rename
                for old, new in rename.items():
                    if old in new_row:
                        new_row[new] = new_row.pop(old)

                # map (copy)
                for dest, src in field_map.items():
                    if src in new_row:
                        new_row[dest] = new_row[src]

                # cast
                for col, spec in cast_cfg.items():
                    if col not in new_row:
                        continue
                    if isinstance(spec, str):
                        typ = spec
                        in_fmt, out_fmt = "%Y-%m-%d", "%Y-%m-%d"
                    else:
                        typ = spec.get("type", "string")
                        in_fmt = spec.get("input_format", "%Y-%m-%d")
                        out_fmt = spec.get("output_format", "%Y-%m-%d")
                    val = new_row[col]
                    if typ in ("date", "datetime"):
                        new_row[col] = _cast_date(val, in_fmt, out_fmt)
                    elif typ in ("int", "integer"):
                        try:
                            new_row[col] = int(float(str(val).strip())) if val not in (None, "") else None
                        except ValueError:
                            pass
                    elif typ in ("float", "number"):
                        try:
                            new_row[col] = float(str(val).strip()) if val not in (None, "") else None
                        except ValueError:
                            pass
                    elif typ == "string":
                        new_row[col] = "" if val is None else str(val)

                for d in drop:
                    new_row.pop(d, None)

                new_row.update(constants)
                out.append(new_row)

            metrics.rows_in = len(rows)
            metrics.rows_out = len(out)
            ctx.emit(f"Transform: processed {len(out)} rows")

        return ComponentResult(rows=out, metrics=metrics)
