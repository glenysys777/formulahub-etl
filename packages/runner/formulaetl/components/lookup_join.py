"""Lookup Join — join primary rows with a lookup set (left/inner/right/full)."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
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


def _merge_rows(
    left_row: dict[str, Any] | None,
    right_row: dict[str, Any] | None,
    left_keys: list[str],
    right_keys: list[str],
    prefix: str,
) -> dict[str, Any]:
    """Merge left + right. Unmatched right maps join keys onto left key names."""
    if left_row is None and right_row is None:
        return {}
    if left_row is None:
        assert right_row is not None
        merged: dict[str, Any] = {}
        for lk, rk in zip(left_keys, right_keys):
            merged[lk] = right_row.get(rk)
        for k, v in right_row.items():
            if k in right_keys:
                continue
            dest_k = f"{prefix}{k}" if prefix else k
            merged[dest_k] = v
        return merged

    merged = dict(left_row)
    if right_row:
        for k, v in right_row.items():
            if k in right_keys:
                continue
            dest_k = f"{prefix}{k}" if prefix else k
            if dest_k not in merged:
                merged[dest_k] = v
    return merged


@register
class LookupJoin(BaseComponent):
    """Join primary (left) input rows with a lookup (right) dataset on key columns.

    Right/lookup side comes from (in order):
    1. ``ctx.variables['_input_streams']['right']`` (multi-input via targetHandle=right)
    2. ``lookup_path`` config (CSV/JSON file)
    3. empty (pass-through left rows when how keeps unmatched left)

    Wire two sources: primary → Lookup Join **left/in** handle, lookup → **right** handle.
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
            "how": {
                "type": "string",
                "enum": ["left", "inner", "right", "full"],
                "default": "left",
            },
            "match": {
                "type": "string",
                "enum": ["all", "first"],
                "default": "all",
            },
        },
    }
    parameters = [
        {
            "key": "left_keys",
            "label": "Primary (left) join keys",
            "type": "string_list",
            "required": True,
            "help": "Column(s) on the primary input (wire to the left/in handle). Example: customer_id",
        },
        {
            "key": "right_keys",
            "label": "Lookup (right) join keys",
            "type": "string_list",
            "required": True,
            "help": "Matching column(s) on the lookup input (wire to the right handle, or set Lookup file)",
        },
        {
            "key": "lookup_path",
            "label": "Lookup file",
            "type": "string",
            "required": False,
            "help": "Optional CSV/JSON lookup when not wiring a second source into the right handle",
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
            "options": ["left", "inner", "right", "full"],
            "help": "left = keep unmatched primary; inner = matches only; right = keep unmatched lookup; full = keep both unmatched sides",
        },
        {
            "key": "match",
            "label": "Match mode",
            "type": "select",
            "required": False,
            "default": "all",
            "options": ["all", "first"],
            "help": "all = one output row per matching lookup row (one-to-many); first = only the first hit per key",
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
            if how not in ("left", "inner", "right", "full"):
                raise ValueError(f"LookupJoin: unsupported how={how!r} (use left|inner|right|full)")
            match_mode = (self.config.get("match") or "all").lower()
            if match_mode not in ("all", "first"):
                raise ValueError(f"LookupJoin: unsupported match={match_mode!r} (use all|first)")

            index: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
            for rr in right_rows:
                index[_row_key(rr, right_keys)].append(rr)

            out: list[dict[str, Any]] = []
            rejected = 0
            used_right_keys: set[tuple] = set()

            for lr in left_rows:
                key = _row_key(lr, left_keys)
                matches = list(index.get(key) or [])
                if match_mode == "first" and matches:
                    matches = matches[:1]

                if not matches:
                    if how in ("left", "full"):
                        out.append(_merge_rows(lr, None, left_keys, right_keys, prefix))
                    elif how == "inner":
                        rejected += 1
                    # how == "right": drop unmatched primary
                    continue

                used_right_keys.add(key)
                for match in matches:
                    out.append(_merge_rows(lr, match, left_keys, right_keys, prefix))

            if how in ("right", "full"):
                for key, rrs in index.items():
                    if key in used_right_keys:
                        continue
                    picks = rrs[:1] if match_mode == "first" else rrs
                    for rr in picks:
                        out.append(_merge_rows(None, rr, left_keys, right_keys, prefix))

            metrics.rows_in = len(left_rows)
            metrics.rows_out = len(out)
            metrics.rows_rejected = rejected
            ctx.emit(
                f"LookupJoin: left={len(left_rows)} lookup={len(right_rows)} → {len(out)} "
                f"(how={how}, match={match_mode})"
            )

        return ComponentResult(
            rows=out,
            metrics=metrics,
            side_effects={
                "left_keys": left_keys,
                "right_keys": right_keys,
                "lookup_rows": len(right_rows),
                "how": how,
                "match": match_mode,
            },
        )
