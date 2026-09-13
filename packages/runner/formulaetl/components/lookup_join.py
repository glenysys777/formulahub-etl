"""Lookup Join — simple left join of primary rows with a lookup set."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.registry import register


def _parse_keys(raw: Any) -> list[str]:
    if raw is None or raw == "":
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    s = str(raw).strip()
    if not s:
        return []
    if s.startswith("["):
        try:
            data = json.loads(s)
            if isinstance(data, list):
                return [str(x).strip() for x in data if str(x).strip()]
        except Exception:
            pass
    return [p.strip() for p in s.replace(";", ",").split(",") if p.strip()]


def _row_key(row: dict[str, Any], keys: list[str]) -> tuple:
    return tuple(row.get(k) for k in keys)


def _load_lookup_file(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"LookupJoin: lookup file not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [dict(x) for x in data]
        if isinstance(data, dict):
            for k in ("records", "data", "items", "rows"):
                if isinstance(data.get(k), list):
                    return [dict(x) for x in data[k]]
        raise ValueError(f"LookupJoin: unsupported JSON shape in {path}")
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@register
class LookupJoin(BaseComponent):
    """Left-join primary input rows with a lookup dataset on key columns.

    Right/lookup side comes from (in order):
    1. ``ctx.variables['_input_streams']['right']`` (multi-input via targetHandle=right)
    2. ``lookup_path`` config (CSV/JSON file)
    3. empty (pass-through left rows with null lookup cols if configured)
    """

    component_type = "lookup_join"
    display_name = "Lookup Join"
    category = "transform"
    config_schema = {
        "type": "object",
        "required": ["left_keys", "right_keys"],
        "properties": {
            "left_keys": {"type": "array", "items": {"type": "string"}},
            "right_keys": {"type": "array", "items": {"type": "string"}},
            "lookup_path": {"type": "string"},
            "prefix": {"type": "string", "default": ""},
            "how": {"type": "string", "enum": ["left", "inner"], "default": "left"},
        },
    }
    parameters = [
        {
            "key": "left_keys",
            "label": "Left keys",
            "type": "string_list",
            "required": True,
            "help": "Key column(s) on the primary (left) input",
        },
        {
            "key": "right_keys",
            "label": "Right keys",
            "type": "string_list",
            "required": True,
            "help": "Key column(s) on the lookup (right) input",
        },
        {
            "key": "lookup_path",
            "label": "Lookup file",
            "type": "string",
            "required": False,
            "help": "Optional CSV/JSON lookup when not wired as a second input",
        },
        {
            "key": "prefix",
            "label": "Right column prefix",
            "type": "string",
            "required": False,
            "default": "",
            "help": "Optional prefix for columns taken from the lookup row",
        },
        {
            "key": "how",
            "label": "Join type",
            "type": "select",
            "required": False,
            "default": "left",
            "options": ["left", "inner"],
            "help": "left keeps unmatched; inner drops them",
        },
    ]

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            left_rows = rows or []
            left_keys = _parse_keys(self.config.get("left_keys"))
            right_keys = _parse_keys(self.config.get("right_keys"))
            if not left_keys or not right_keys:
                raise ValueError("LookupJoin: left_keys and right_keys are required")
            if len(left_keys) != len(right_keys):
                raise ValueError("LookupJoin: left_keys and right_keys must be same length")

            streams = ctx.variables.get("_input_streams") or {}
            right_rows: list[dict[str, Any]] = []
            if isinstance(streams, dict) and streams.get("right"):
                right_rows = list(streams["right"])
            elif self.config.get("lookup_path"):
                right_rows = _load_lookup_file(ctx.resolve(str(self.config["lookup_path"])))

            prefix = str(self.config.get("prefix") or "")
            how = (self.config.get("how") or "left").lower()

            index: dict[tuple, dict[str, Any]] = {}
            for rr in right_rows:
                index[_row_key(rr, right_keys)] = rr

            out: list[dict[str, Any]] = []
            rejected = 0
            for lr in left_rows:
                key = _row_key(lr, left_keys)
                match = index.get(key)
                if match is None:
                    if how == "inner":
                        rejected += 1
                        continue
                    out.append(dict(lr))
                    continue
                merged = dict(lr)
                for k, v in match.items():
                    if k in right_keys:
                        continue
                    dest_k = f"{prefix}{k}" if prefix else k
                    if dest_k not in merged:
                        merged[dest_k] = v
                out.append(merged)

            metrics.rows_in = len(left_rows)
            metrics.rows_out = len(out)
            metrics.rows_rejected = rejected
            ctx.emit(
                f"LookupJoin: left={len(left_rows)} lookup={len(right_rows)} → {len(out)} "
                f"(how={how})"
            )

        return ComponentResult(
            rows=out,
            metrics=metrics,
            side_effects={
                "left_keys": left_keys,
                "right_keys": right_keys,
                "lookup_rows": len(right_rows),
                "how": how,
            },
        )
