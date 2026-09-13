"""Schema Validate — validate columns/types; reject invalid rows."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.registry import register


def _as_int(v: Any) -> bool:
    if v is None or v == "":
        return False
    try:
        int(str(v).strip())
        return True
    except (TypeError, ValueError):
        return False


def _as_float(v: Any) -> bool:
    if v is None or v == "":
        return False
    try:
        float(str(v).strip())
        return True
    except (TypeError, ValueError):
        return False


def _as_str(v: Any) -> bool:
    return v is not None and str(v).strip() != ""


def _as_date(v: Any, fmt: str = "%Y-%m-%d") -> bool:
    if v is None or v == "":
        return False
    try:
        datetime.strptime(str(v).strip(), fmt)
        return True
    except ValueError:
        return False


def _as_email(v: Any) -> bool:
    if not _as_str(v):
        return False
    s = str(v)
    return "@" in s and "." in s.split("@")[-1]


TYPE_CHECKERS: dict[str, Callable[[Any], bool]] = {
    "string": _as_str,
    "str": _as_str,
    "int": _as_int,
    "integer": _as_int,
    "float": _as_float,
    "number": _as_float,
    "date": lambda v: _as_date(v),
    "datetime": lambda v: _as_date(v, "%Y-%m-%d %H:%M:%S") or _as_date(v, "%Y-%m-%dT%H:%M:%S") or _as_date(v),
    "email": _as_email,
}


@register
class SchemaValidate(BaseComponent):
    component_type = "schema_validate"
    display_name = "Schema Validate"
    category = "quality"
    config_schema = {
        "type": "object",
        "required": ["columns"],
        "properties": {
            "columns": {
                "type": "object",
                "description": "Map of column_name → type (string|int|float|date|email)",
            },
            "required_columns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Columns that must be present and non-empty",
            },
            "strict": {
                "type": "boolean",
                "default": False,
                "description": "If true, reject rows with extra unknown columns",
            },
        },
    }
    parameters = [
        {"key": "columns", "label": "Column schema", "type": "string", "required": True, "help": "JSON map of column_name → type (string|int|float|date|email)"},
        {"key": "required_columns", "label": "Required columns", "type": "string_list", "required": False, "help": "Columns that must be present and non-empty"},
        {"key": "strict", "label": "Strict mode", "type": "boolean", "required": False, "default": False, "help": "Reject rows with extra unknown columns"},
    ]

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            rows = rows or []
            columns: dict[str, str] = self.config.get("columns", {})
            required = set(self.config.get("required_columns") or list(columns.keys()))
            strict = bool(self.config.get("strict", False))

            good: list[dict[str, Any]] = []
            rejects: list[dict[str, Any]] = []

            for row in rows:
                errors: list[str] = []
                for col in required:
                    if col not in row or row[col] is None or str(row[col]).strip() == "":
                        errors.append(f"missing required column '{col}'")
                for col, typ in columns.items():
                    if col not in row:
                        continue
                    checker = TYPE_CHECKERS.get(typ.lower())
                    if checker and row[col] not in (None, "") and not checker(row[col]):
                        errors.append(f"column '{col}' failed type '{typ}' (value={row[col]!r})")
                    elif col in required and not checker(row.get(col)):
                        if f"missing required column '{col}'" not in errors:
                            errors.append(f"column '{col}' invalid for type '{typ}'")
                if strict:
                    known = set(columns.keys())
                    extra = set(row.keys()) - known
                    if extra:
                        errors.append(f"unexpected columns: {sorted(extra)}")

                if errors:
                    bad = dict(row)
                    bad["_reject_reason"] = "; ".join(errors)
                    rejects.append(bad)
                else:
                    good.append(row)

            metrics.rows_in = len(rows)
            metrics.rows_out = len(good)
            metrics.rows_rejected = len(rejects)
            ctx.emit(
                f"SchemaValidate: {len(good)} valid, {len(rejects)} rejected "
                f"(of {len(rows)})"
            )

        return ComponentResult(
            rows=good,
            rejects=rejects,
            metrics=metrics,
            streams={"out": good, "rejects": rejects},
        )
