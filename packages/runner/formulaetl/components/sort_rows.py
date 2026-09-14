"""Sort Rows (tSortRow) — sort by one or more keys asc/desc."""

from __future__ import annotations

from typing import Any

from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.capabilities import BLOCKING_ROWS
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.registry import register


def _parse_keys(raw: Any) -> list[tuple[str, bool]]:
    """Parse string_list of 'col:asc' / 'col:desc' (default asc)."""
    lines: list[str] = []
    if raw is None:
        return []
    if isinstance(raw, str):
        lines = [ln.strip() for ln in raw.replace(",", "\n").splitlines() if ln.strip()]
    elif isinstance(raw, list):
        lines = [str(x).strip() for x in raw if str(x).strip()]
    else:
        return []

    keys: list[tuple[str, bool]] = []
    for line in lines:
        if ":" in line:
            col, direction = line.rsplit(":", 1)
            col, direction = col.strip(), direction.strip().lower()
        else:
            col, direction = line.strip(), "asc"
        if not col:
            continue
        reverse = direction in ("desc", "descending", "d", "1")
        keys.append((col, reverse))
    return keys


def _sort_key_value(v: Any) -> tuple[int, Any]:
    """None/missing last; mixed types comparable via (type_rank, value)."""
    if v is None or v == "":
        return (2, "")
    if isinstance(v, bool):
        return (0, int(v))
    if isinstance(v, (int, float)):
        return (0, float(v))
    try:
        return (0, float(str(v).strip()))
    except (TypeError, ValueError):
        return (1, str(v).lower())


@register
class SortRows(BaseComponent):
    component_type = "sort"
    display_name = "Sort Rows"
    category = "transform"
    capabilities = BLOCKING_ROWS
    config_schema = {
        "type": "object",
        "required": ["keys"],
        "properties": {
            "keys": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Lines of col:asc or col:desc",
            },
        },
    }
    parameters = [
        {
            "key": "keys",
            "label": "Sort keys",
            "type": "string_list",
            "required": True,
            "help": "One key per line: col:asc or col:desc (tSortRow)",
            "placeholder": "status:asc",
        },
    ]

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            rows = list(rows or [])
            keys = _parse_keys(self.config.get("keys"))
            if not keys:
                raise ValueError("Sort: keys is required (e.g. amount:desc)")

            # Stable multi-key sort: apply least-significant key first
            out = list(rows)
            for col, reverse in reversed(keys):
                out.sort(key=lambda r, c=col: _sort_key_value(r.get(c)), reverse=reverse)

            metrics.rows_in = len(rows)
            metrics.rows_out = len(out)
            key_desc = ", ".join(f"{c}:{'desc' if rev else 'asc'}" for c, rev in keys)
            ctx.emit(f"Sort: {len(out)} rows by [{key_desc}]")

        return ComponentResult(rows=out, metrics=metrics)
