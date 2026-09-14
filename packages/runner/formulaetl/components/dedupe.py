"""Dedupe — keep unique rows by key columns.

``keep=first`` is streaming/stateful across RowBatches (key set only in RAM).
``keep=last`` remains blocking (needs the full input).
"""

from __future__ import annotations

from typing import Any

from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.capabilities import BLOCKING_ROWS, STREAMING_STATEFUL
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.registry import register


def _parse_keys(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    if isinstance(raw, str):
        parts = []
        for chunk in raw.replace("\n", ",").split(","):
            chunk = chunk.strip()
            if chunk:
                parts.append(chunk)
        return parts
    return [str(raw)]


@register
class Dedupe(BaseComponent):
    component_type = "dedupe"
    display_name = "Dedupe"
    category = "transform"
    capabilities = BLOCKING_ROWS
    config_schema = {
        "type": "object",
        "required": ["keys"],
        "properties": {
            "keys": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Column names that define uniqueness",
            },
            "keep": {
                "type": "string",
                "enum": ["first", "last"],
                "default": "first",
            },
        },
    }
    parameters = [
        {
            "key": "keys",
            "label": "Unique keys",
            "type": "string_list",
            "required": True,
            "help": "Column(s) that define a unique row (one per line or comma-separated)",
            "placeholder": "order_id",
        },
        {
            "key": "keep",
            "label": "Keep",
            "type": "select",
            "required": False,
            "default": "first",
            "options": ["first", "last"],
            "help": "Which duplicate to keep",
        },
    ]

    def get_capabilities(self):
        keep = (self.config.get("keep") or "first").lower()
        if keep == "first":
            return STREAMING_STATEFUL
        return BLOCKING_ROWS

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            rows = rows or []
            keys = _parse_keys(self.config.get("keys"))
            if not keys:
                raise ValueError("Dedupe: keys is required")
            keep = (self.config.get("keep") or "first").lower()
            if keep not in ("first", "last"):
                keep = "first"

            kept: list[dict[str, Any]] = []
            dropped: list[dict[str, Any]] = []

            if keep == "first":
                # Stateful across batched calls on the same component instance.
                seen: set[tuple[Any, ...]] = getattr(self, "_seen", None) or set()
                self._seen = seen
                for row in rows:
                    key = tuple(row.get(k) for k in keys)
                    if key in seen:
                        dropped.append(row)
                    else:
                        seen.add(key)
                        kept.append(row)
            else:
                # keep last occurrence, preserving first-seen key order
                last_by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
                order: list[tuple[Any, ...]] = []
                for row in rows:
                    key = tuple(row.get(k) for k in keys)
                    if key not in last_by_key:
                        order.append(key)
                    else:
                        dropped.append(last_by_key[key])
                    last_by_key[key] = row
                kept = [last_by_key[k] for k in order]

            metrics.rows_in = len(rows)
            metrics.rows_out = len(kept)
            metrics.rows_rejected = len(dropped)
            ctx.emit(
                f"Dedupe: kept {len(kept)} / {len(rows)} unique on {keys} (keep={keep})"
            )

        return ComponentResult(rows=kept, rejects=dropped, metrics=metrics)
