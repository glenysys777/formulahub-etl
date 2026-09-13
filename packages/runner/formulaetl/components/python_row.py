"""Python Row — restricted Python per row or batch.

Sandboxed Python expression/script (no open/network/os/import).
"""

from __future__ import annotations

from typing import Any

from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.registry import register

# Safe builtins only — no open / network / os / import / eval / exec exposure
_SAFE_BUILTINS: dict[str, Any] = {
    "abs": abs,
    "min": min,
    "max": max,
    "len": len,
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "round": round,
    "sum": sum,
    "sorted": sorted,
    "enumerate": enumerate,
    "zip": zip,
    "range": range,
    "list": list,
    "dict": dict,
    "set": set,
    "tuple": tuple,
    "isinstance": isinstance,
    "type": type,
    "True": True,
    "False": False,
    "None": None,
    "print": lambda *a, **k: None,  # no-op; logging via ctx is unavailable inside sandbox
}


def _run_code(code: str, local_ns: dict[str, Any]) -> dict[str, Any]:
    """Exec user code in a restricted namespace. Mutates/returns local_ns."""
    # Block obvious dangerous patterns early (token-ish, not over-broad)
    import re
    patterns = [
        r"__import__",
        r"\bimport\b",
        r"\bopen\s*\(",
        r"\bexec\s*\(",
        r"\beval\s*\(",
        r"\bos\s*\.",
        r"\bsys\s*\.",
        r"\bsubprocess\b",
        r"\bsocket\b",
        r"\burllib\b",
        r"\bpathlib\b",
        r"\bbuiltins\b",
        r"\bglobals\s*\(",
        r"\blocals\s*\(",
        r"\bgetattr\s*\(",
        r"\bsetattr\s*\(",
        r"\bdelattr\s*\(",
        r"__class__",
        r"__bases__",
        r"__subclasses__",
    ]
    for pat in patterns:
        if re.search(pat, code):
            raise ValueError(f"PythonRow: disallowed pattern in code: {pat}")

    g: dict[str, Any] = {"__builtins__": _SAFE_BUILTINS}
    # Compile first so SyntaxError is clear
    compiled = compile(code, "<python_row>", "exec")
    exec(compiled, g, local_ns)  # noqa: S102 — intentional restricted sandbox
    return local_ns


@register
class PythonRow(BaseComponent):
    component_type = "python_row"
    display_name = "Python Row"
    category = "transform"
    config_schema = {
        "type": "object",
        "required": ["code"],
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["row", "batch"],
                "default": "row",
                "description": "row = per-row script; batch = whole list as rows",
            },
            "code": {
                "type": "string",
                "description": "Python script (NOT Java). Mutate row / rows in place or assign result.",
            },
            "input_var": {
                "type": "string",
                "default": "row",
                "description": "Variable name: 'row' (mode=row) or 'rows' (mode=batch)",
            },
        },
    }
    parameters = [
        {
            "key": "mode",
            "label": "Mode",
            "type": "select",
            "required": False,
            "default": "row",
            "options": ["row", "batch"],
            "help": "row = run once per row; batch = run once on the full list",
        },
        {
            "key": "code",
            "label": "Python code",
            "type": "secret",
            "required": True,
            "help": (
                "Python (not Java / not tJavaRow). Restricted sandbox: only row/rows + safe builtins. "
                "No open/network/os. Example: row['total'] = float(row.get('amount') or 0) * 1.1"
            ),
            "placeholder": "row['flag'] = 'ok'",
        },
        {
            "key": "input_var",
            "label": "Input variable",
            "type": "string",
            "required": False,
            "default": "row",
            "help": "Name bound in the sandbox: 'row' (dict) or 'rows' (list of dicts)",
        },
    ]

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            rows = rows or []
            mode = (self.config.get("mode") or "row").lower()
            if mode not in ("row", "batch"):
                mode = "row"
            code = str(self.config.get("code") or "").strip()
            if not code:
                raise ValueError("PythonRow: code is required")
            input_var = str(self.config.get("input_var") or ("row" if mode == "row" else "rows"))

            out: list[dict[str, Any]] = []
            if mode == "batch":
                batch_rows = [dict(r) for r in rows]
                local: dict[str, Any] = {"row": None, "rows": batch_rows}
                if input_var not in local:
                    local[input_var] = batch_rows
                else:
                    local[input_var] = batch_rows
                _run_code(code, local)
                result = local.get("rows")
                if not isinstance(result, list) and input_var != "rows":
                    result = local.get(input_var)
                if not isinstance(result, list):
                    raise ValueError("PythonRow batch mode: code must leave 'rows' as a list of dicts")
                out = [dict(r) if isinstance(r, dict) else {"value": r} for r in result]
            else:
                for row in rows:
                    local = {"row": dict(row), "rows": None}
                    if input_var != "row":
                        local[input_var] = local["row"]
                    _run_code(code, local)
                    result = local.get("row")
                    if input_var != "row" and local.get(input_var) is not None:
                        result = local[input_var]
                    if result is None:
                        continue  # drop row if set to None
                    if not isinstance(result, dict):
                        raise ValueError("PythonRow row mode: 'row' must remain a dict (or None to drop)")
                    out.append(result)

            metrics.rows_in = len(rows)
            metrics.rows_out = len(out)
            ctx.emit(
                f"PythonRow [{mode}]: {len(rows)} → {len(out)} "
                f"(sandbox Python — not Java/tJavaRow)"
            )

        return ComponentResult(rows=out, metrics=metrics)
