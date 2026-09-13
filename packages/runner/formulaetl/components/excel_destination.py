"""Excel Destination — write row dicts to .xlsx."""

from __future__ import annotations

from typing import Any

from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.registry import register


@register
class ExcelDestination(BaseComponent):
    component_type = "excel_destination"
    display_name = "Excel Destination"
    category = "destination"
    config_schema = {
        "type": "object",
        "required": ["path"],
        "properties": {
            "path": {"type": "string"},
            "sheet_name": {"type": "string", "default": "Sheet1"},
            "has_header": {"type": "boolean", "default": True},
        },
    }
    parameters = [
        {
            "key": "path",
            "label": "Output path",
            "type": "string",
            "required": True,
            "help": "Destination .xlsx path relative to work_dir",
        },
        {
            "key": "sheet_name",
            "label": "Sheet name",
            "type": "string",
            "required": False,
            "default": "Sheet1",
            "help": "Worksheet name to write",
        },
        {
            "key": "has_header",
            "label": "Write header",
            "type": "boolean",
            "required": False,
            "default": True,
            "help": "Write column names as the first row",
        },
    ]

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            from openpyxl import Workbook

            rows = rows or []
            path = ctx.resolve(self.config["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            sheet_name = str(self.config.get("sheet_name") or "Sheet1")
            has_header = self.config.get("has_header", True)
            if isinstance(has_header, str):
                has_header = has_header.strip().lower() in ("1", "true", "yes", "y")

            def _clean_row(r: dict[str, Any]) -> dict[str, Any]:
                return {
                    k: v
                    for k, v in r.items()
                    if (not k.startswith("_")) or k == "_reject_reason"
                }

            clean = [_clean_row(r) for r in rows]
            fieldnames: list[str] = []
            if clean:
                fieldnames = list(clean[0].keys())
                for r in clean[1:]:
                    for k in r:
                        if k not in fieldnames:
                            fieldnames.append(k)

            wb = Workbook()
            ws = wb.active
            ws.title = sheet_name[:31] or "Sheet1"
            if has_header and fieldnames:
                ws.append(fieldnames)
            for r in clean:
                ws.append([r.get(k) for k in fieldnames])
            wb.save(path)

            metrics.rows_in = len(rows)
            metrics.rows_out = len(rows)
            ctx.emit(f"ExcelDestination: wrote {len(rows)} rows → {path}")

        return ComponentResult(
            rows=rows,
            metrics=metrics,
            side_effects={
                "written_path": str(path),
                "sheet_name": sheet_name,
                "format": "xlsx",
            },
            artifacts={"path": str(path)},
        )
