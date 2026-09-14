"""Aggregate (tAggregateRow-lite) — group_by + sum/count/min/max/avg."""

from __future__ import annotations

from typing import Any

from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.capabilities import BLOCKING_ROWS
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.registry import register

_SUPPORTED = frozenset({"sum", "count", "min", "max", "avg", "average", "mean"})


def _parse_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    if isinstance(raw, str):
        return [ln.strip() for ln in raw.replace(",", "\n").splitlines() if ln.strip()]
    return [str(raw)]


def _parse_aggs(raw: Any) -> list[tuple[str, str]]:
    """Parse 'sum:amount', 'count:*', 'avg:x' → (fn, col)."""
    out: list[tuple[str, str]] = []
    for line in _parse_list(raw):
        if ":" in line:
            fn, col = line.split(":", 1)
            fn, col = fn.strip().lower(), col.strip()
        else:
            fn, col = line.strip().lower(), "*"
        if fn in ("average", "mean"):
            fn = "avg"
        if fn not in _SUPPORTED:
            raise ValueError(f"Aggregate: unsupported agg {fn!r} (use sum/count/min/max/avg)")
        if not col:
            col = "*"
        out.append((fn, col))
    return out


def _num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


@register
class Aggregate(BaseComponent):
    component_type = "aggregate"
    display_name = "Aggregate"
    category = "transform"
    capabilities = BLOCKING_ROWS
    config_schema = {
        "type": "object",
        "required": ["aggs"],
        "properties": {
            "group_by": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Group-by column names",
            },
            "aggs": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Agg specs: sum:amount, count:*, min:x, max:x, avg:x",
            },
        },
    }
    parameters = [
        {
            "key": "group_by",
            "label": "Group by",
            "type": "string_list",
            "required": False,
            "default": [],
            "help": "Columns to group by (empty = single group over all rows)",
            "placeholder": "status",
        },
        {
            "key": "aggs",
            "label": "Aggregations",
            "type": "string_list",
            "required": True,
            "help": "One per line: sum:amount, count:*, min:x, max:x, avg:x",
            "placeholder": "sum:amount",
        },
    ]

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            rows = rows or []
            group_by = _parse_list(self.config.get("group_by"))
            aggs = _parse_aggs(self.config.get("aggs"))
            if not aggs:
                raise ValueError("Aggregate: aggs is required")

            groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
            order: list[tuple[Any, ...]] = []
            for row in rows:
                key = tuple(row.get(c) for c in group_by)
                if key not in groups:
                    groups[key] = []
                    order.append(key)
                groups[key].append(row)

            out: list[dict[str, Any]] = []
            for key in order:
                bucket = groups[key]
                new_row: dict[str, Any] = {}
                for i, col in enumerate(group_by):
                    new_row[col] = key[i]
                for fn, col in aggs:
                    out_name = f"{fn}_{col}" if col != "*" else fn
                    if fn == "count":
                        if col == "*":
                            new_row[out_name] = len(bucket)
                        else:
                            new_row[out_name] = sum(
                                1 for r in bucket if r.get(col) not in (None, "")
                            )
                    elif fn == "sum":
                        vals = [_num(r.get(col)) for r in bucket]
                        nums = [v for v in vals if v is not None]
                        new_row[out_name] = sum(nums) if nums else 0
                    elif fn == "min":
                        vals = [_num(r.get(col)) for r in bucket]
                        nums = [v for v in vals if v is not None]
                        new_row[out_name] = min(nums) if nums else None
                    elif fn == "max":
                        vals = [_num(r.get(col)) for r in bucket]
                        nums = [v for v in vals if v is not None]
                        new_row[out_name] = max(nums) if nums else None
                    elif fn == "avg":
                        vals = [_num(r.get(col)) for r in bucket]
                        nums = [v for v in vals if v is not None]
                        new_row[out_name] = (sum(nums) / len(nums)) if nums else None
                out.append(new_row)

            metrics.rows_in = len(rows)
            metrics.rows_out = len(out)
            ctx.emit(
                f"Aggregate: {len(rows)} → {len(out)} groups on {group_by or '(all)'} "
                f"aggs={[f'{f}:{c}' for f, c in aggs]}"
            )

        return ComponentResult(rows=out, metrics=metrics)
