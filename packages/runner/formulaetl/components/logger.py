"""Logger / Metrics — emit rows_in, rows_out, rows_rejected, duration_ms."""

from __future__ import annotations

from typing import Any

from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.capabilities import ROWWISE
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.registry import register


@register
class LoggerMetrics(BaseComponent):
    component_type = "logger_metrics"
    display_name = "Logger / Metrics"
    category = "utility"
    capabilities = ROWWISE
    config_schema = {
        "type": "object",
        "properties": {
            "label": {"type": "string", "default": "checkpoint"},
            "log_sample": {"type": "integer", "default": 0, "description": "Log N sample rows"},
        },
    }
    parameters = [
        {"key": "label", "label": "Label", "type": "string", "required": False, "default": "checkpoint", "help": "Checkpoint label in logs"},
        {"key": "log_sample", "label": "Sample rows", "type": "number", "required": False, "default": 0, "help": "Log N sample rows"},
    ]

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            rows = rows or []
            label = self.config.get("label", "checkpoint")
            metrics.rows_in = len(rows)
            metrics.rows_out = len(rows)
            sample_n = int(self.config.get("log_sample", 0))
            ctx.emit(
                f"LoggerMetrics[{label}]: rows_in={metrics.rows_in} "
                f"rows_out={metrics.rows_out} rows_rejected={metrics.rows_rejected}"
            )
            if sample_n > 0:
                for i, row in enumerate(rows[:sample_n]):
                    ctx.emit(f"  sample[{i}]: {row}")

        return ComponentResult(rows=rows, metrics=metrics)
