"""Column Map — rename/select columns via old:new lines."""

from __future__ import annotations

from typing import Any

from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.registry import register


def _parse_mappings(raw: Any) -> list[tuple[str, str]]:
    """Parse string_list or newline string of 'old:new' / 'old→new' / 'old=new'."""
    lines: list[str] = []
    if raw is None:
        return []
    if isinstance(raw, dict):
        return [(str(k), str(v)) for k, v in raw.items()]
    if isinstance(raw, str):
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    elif isinstance(raw, list):
        lines = [str(x).strip() for x in raw if str(x).strip()]
    else:
        return []

    mappings: list[tuple[str, str]] = []
    for line in lines:
        sep = None
        for candidate in (":", "→", "->", "="):
            if candidate in line:
                sep = candidate
                break
        if not sep:
            continue
        old, new = line.split(sep, 1)
        old, new = old.strip(), new.strip()
        if old and new:
            mappings.append((old, new))
    return mappings


@register
class ColumnMap(BaseComponent):
    component_type = "column_map"
    display_name = "Schema Map"
    category = "transform"
    config_schema = {
        "type": "object",
        "required": ["mappings"],
        "properties": {
            "mappings": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Lines of old:new column renames",
            },
            "drop_unmapped": {
                "type": "boolean",
                "default": False,
                "description": "If true, drop columns not listed as a mapping source or target",
            },
        },
    }
    parameters = [
        {
            "key": "mappings",
            "label": "Mappings",
            "type": "string_list",
            "required": True,
            "help": "One rename per line: old:new (also accepts old=new)",
            "placeholder": "orderId:order_id",
        },
        {
            "key": "drop_unmapped",
            "label": "Drop unmapped",
            "type": "boolean",
            "required": False,
            "default": False,
            "help": "Keep only mapped columns (targets); drop everything else",
        },
    ]

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            rows = rows or []
            mappings = _parse_mappings(self.config.get("mappings"))
            drop_unmapped = bool(self.config.get("drop_unmapped", False))
            targets = {new for _, new in mappings}

            out: list[dict[str, Any]] = []
            for row in rows:
                new_row = dict(row)
                for old, new in mappings:
                    if old in new_row:
                        new_row[new] = new_row.pop(old)
                    elif new not in new_row and old not in new_row:
                        # source missing — leave as-is
                        pass
                if drop_unmapped:
                    new_row = {k: v for k, v in new_row.items() if k in targets}
                out.append(new_row)

            metrics.rows_in = len(rows)
            metrics.rows_out = len(out)
            ctx.emit(
                f"ColumnMap: applied {len(mappings)} mappings "
                f"(drop_unmapped={drop_unmapped}) on {len(out)} rows"
            )

        return ComponentResult(rows=out, metrics=metrics)
