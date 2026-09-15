"""Schema Validate — validate columns/types; reject invalid rows."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Callable

from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.capabilities import ROWWISE
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.registry import register


def _as_int(v: Any) -> bool:
    if v is None or v == "":
        return False
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return True
    s = v if isinstance(v, str) else str(v)
    s = s.strip()
    if not s:
        return False
    if s[0] in "+-":
        s = s[1:]
    return s.isdigit()


def _as_float(v: Any) -> bool:
    if v is None or v == "":
        return False
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return True
    s = v if isinstance(v, str) else str(v)
    try:
        float(s)
        return True
    except (TypeError, ValueError):
        return False


def _as_str(v: Any) -> bool:
    return v is not None and str(v).strip() != ""


def _as_date(v: Any, fmt: str = "%Y-%m-%d") -> bool:
    if v is None or v == "":
        return False
    s = v if isinstance(v, str) else str(v)
    s = s.strip()
    if fmt == "%Y-%m-%d" and len(s) == 10 and s[4] == "-" and s[7] == "-":
        try:
            datetime.fromisoformat(s)
            return True
        except ValueError:
            return False
    try:
        datetime.strptime(s, fmt)
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
    capabilities = ROWWISE
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
            spec = getattr(self, "_compiled", None)
            if spec is None:
                columns: dict[str, str] = self.config.get("columns", {})
                if isinstance(columns, str):
                    columns = json.loads(columns) if columns.strip() else {}
                if not columns:
                    upstream = ctx.variables.get("target_schema")
                    if isinstance(upstream, dict) and upstream:
                        columns = {str(k): str(v) for k, v in upstream.items()}
                required = set(self.config.get("required_columns") or list(columns.keys()))
                strict = bool(self.config.get("strict", False))
                checks: list[tuple[str, str, Any]] = []
                for col, typ in columns.items():
                    checker = TYPE_CHECKERS.get(str(typ).lower())
                    if checker:
                        checks.append((col, str(typ), checker))
                spec = (required, checks, strict, set(columns.keys()))
                self._compiled = spec
            required, checks, strict, known = spec

            good: list[dict[str, Any]] = []
            rejects: list[dict[str, Any]] = []
            good_append = good.append
            rejects_append = rejects.append

            for row in rows:
                errors: list[str] | None = None
                for col in required:
                    val = row.get(col)
                    if val is None or val == "":
                        errors = errors or []
                        errors.append(f"missing required column '{col}'")
                for col, typ, checker in checks:
                    val = row.get(col)
                    if val is None or val == "":
                        continue
                    if not checker(val):
                        errors = errors or []
                        errors.append(f"column '{col}' failed type '{typ}' (value={val!r})")
                if strict:
                    extra = {k for k in row if not str(k).startswith("_")} - known
                    if extra:
                        errors = errors or []
                        errors.append(f"unexpected columns: {sorted(extra)}")
                if errors:
                    bad = dict(row)
                    bad["_reject_reason"] = "; ".join(errors)
                    rejects_append(bad)
                else:
                    good_append(row)

            metrics.rows_in = len(rows)
            metrics.rows_out = len(good)
            metrics.rows_rejected = len(rejects)
            if len(rows) < 4096 or getattr(self, "_emit_count", 0) < 1:
                ctx.emit(
                    f"SchemaValidate: {len(good)} valid, {len(rejects)} rejected "
                    f"(of {len(rows)})"
                )
                self._emit_count = getattr(self, "_emit_count", 0) + 1

        return ComponentResult(
            rows=good,
            rejects=rejects,
            metrics=metrics,
            streams={"out": good, "rejects": rejects},
        )
