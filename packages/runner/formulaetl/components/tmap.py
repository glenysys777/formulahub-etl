"""Field Mapper — expression-based column mappings + optional filter.

Not a full visual tMap IDE — enough for demos: out=expr mappings, filter_expr, drop_unmapped.
"""

from __future__ import annotations

import ast
import operator
from typing import Any

from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.registry import register

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_CMP_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}
_BOOL_OPS = {
    ast.And: lambda vals: all(vals),
    ast.Or: lambda vals: any(vals),
}


def _coalesce(*args: Any) -> Any:
    for a in args:
        if a is not None and a != "":
            return a
    return None


def _upper(v: Any) -> str:
    return "" if v is None else str(v).upper()


def _lower(v: Any) -> str:
    return "" if v is None else str(v).lower()


def _str(v: Any) -> str:
    return "" if v is None else str(v)


def _num(v: Any) -> float:
    if v is None or v == "":
        return 0.0
    return float(v)


def _iint(v: Any) -> int:
    if v is None or v == "":
        return 0
    return int(float(v))


_FUNCS = {
    "upper": _upper,
    "lower": _lower,
    "str": _str,
    "int": _iint,
    "float": _num,
    "len": lambda v: len(v) if v is not None else 0,
    "coalesce": _coalesce,
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
}


def _eval(node: ast.AST, row: dict[str, Any], row_dict: dict[str, Any] | None = None) -> Any:
    row_dict = row_dict if row_dict is not None else row
    if isinstance(node, ast.Expression):
        return _eval(node.body, row, row_dict)
    if isinstance(node, ast.BoolOp):
        op = _BOOL_OPS[type(node.op)]
        return op([_eval(v, row, row_dict) for v in node.values])
    if isinstance(node, ast.UnaryOp):
        val = _eval(node.operand, row, row_dict)
        if isinstance(node.op, ast.Not):
            return not val
        if isinstance(node.op, ast.USub):
            return -val
        if isinstance(node.op, ast.UAdd):
            return +val
        raise ValueError(f"Unsupported unary op: {type(node.op).__name__}")
    if isinstance(node, ast.BinOp):
        op = _BIN_OPS.get(type(node.op))
        if not op:
            raise ValueError(f"Unsupported binary op: {type(node.op).__name__}")
        left, right = _eval(node.left, row, row_dict), _eval(node.right, row, row_dict)
        # Soft numeric coercion for + on number-like strings
        if type(node.op) in (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow):
            try:
                if not isinstance(left, (int, float)) and left not in (None, ""):
                    left = float(left)
                if not isinstance(right, (int, float)) and right not in (None, ""):
                    right = float(right)
            except (TypeError, ValueError):
                if type(node.op) is ast.Add:
                    return str(left) + str(right)
        return op(left, right)
    if isinstance(node, ast.Compare):
        left = _eval(node.left, row, row_dict)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval(comparator, row, row_dict)
            fn = _CMP_OPS.get(type(op))
            if not fn:
                raise ValueError(f"Unsupported compare: {type(op).__name__}")
            if not fn(left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError("Only simple function calls allowed")
        name = node.func.id
        if name == "col":
            args = [_eval(a, row, row_dict) for a in node.args]
            if not args:
                raise ValueError("col() requires a column name")
            return row_dict.get(str(args[0]))
        if name not in _FUNCS or name == "col":
            if name not in _FUNCS:
                raise ValueError(f"Unknown function: {name}")
        args = [_eval(a, row, row_dict) for a in node.args]
        return _FUNCS[name](*args)
    if isinstance(node, ast.Subscript):
        base = _eval(node.value, row, row_dict)
        sl = node.slice
        key = _eval(sl, row, row_dict)
        if isinstance(base, dict):
            return base.get(key)
        return base[key]
    if isinstance(node, ast.Name):
        if node.id in ("True", "False", "None"):
            return {"True": True, "False": False, "None": None}[node.id]
        if node.id == "row":
            return row_dict
        return row.get(node.id)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Str):  # pragma: no cover
        return node.s
    if isinstance(node, ast.Num):  # pragma: no cover
        return node.n
    if isinstance(node, ast.List):
        return [_eval(e, row, row_dict) for e in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_eval(e, row, row_dict) for e in node.elts)
    if isinstance(node, ast.IfExp):
        return _eval(node.body, row, row_dict) if _eval(node.test, row, row_dict) else _eval(node.orelse, row, row_dict)
    raise ValueError(f"Unsupported expression node: {type(node).__name__}")


def eval_expr(expr: str, row: dict[str, Any]) -> Any:
    tree = ast.parse(expr.strip(), mode="eval")
    return _eval(tree, row, row)


def _parse_mappings(raw: Any) -> list[tuple[str, str]]:
    lines: list[str] = []
    if raw is None:
        return []
    if isinstance(raw, dict):
        return [(str(k), str(v)) for k, v in raw.items()]
    if isinstance(raw, str):
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    elif isinstance(raw, list):
        lines = [str(x).strip() for x in raw if str(x).strip()]
    mappings: list[tuple[str, str]] = []
    for line in lines:
        if "=" in line:
            out, expr = line.split("=", 1)
        elif ":" in line:
            out, expr = line.split(":", 1)
        else:
            continue
        out, expr = out.strip(), expr.strip()
        if out and expr:
            mappings.append((out, expr))
    return mappings


@register
class TMap(BaseComponent):
    component_type = "tmap"
    display_name = "Field Mapper"
    category = "transform"
    config_schema = {
        "type": "object",
        "required": ["mappings"],
        "properties": {
            "mappings": {
                "type": "array",
                "items": {"type": "string"},
                "description": "out=expr lines, e.g. name_up=upper(name), total=amount*1.1",
            },
            "filter_expr": {
                "type": "string",
                "description": "Optional row filter expression (keep when true)",
            },
            "drop_unmapped": {
                "type": "boolean",
                "default": False,
                "description": "If true, output only mapped columns",
            },
            "reject_unmatched": {
                "type": "boolean",
                "default": False,
                "description": "If true, filter misses go to rejects instead of being dropped silently",
            },
        },
    }
    parameters = [
        {
            "key": "mappings",
            "label": "Mappings",
            "type": "string_list",
            "required": True,
            "help": "One per line: out=expr — e.g. name_up=upper(name), total=amount*1.1, x=coalesce(a,b)",
            "placeholder": "total=amount*1.1",
        },
        {
            "key": "filter_expr",
            "label": "Filter expression",
            "type": "string",
            "required": False,
            "help": "Optional keep-when-true expression (evaluated on input row before/with mapping)",
            "placeholder": "status == 'shipped'",
        },
        {
            "key": "drop_unmapped",
            "label": "Drop unmapped",
            "type": "boolean",
            "required": False,
            "default": False,
            "help": "Keep only output columns produced by mappings",
        },
        {
            "key": "reject_unmatched",
            "label": "Reject unmatched filter",
            "type": "boolean",
            "required": False,
            "default": False,
            "help": "Send filter misses to rejects path instead of dropping",
        },
    ]

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            rows = rows or []
            mappings = _parse_mappings(self.config.get("mappings"))
            if not mappings:
                raise ValueError("tMap: mappings required (out=expr)")
            filter_expr = (self.config.get("filter_expr") or "").strip() or None
            drop_unmapped = bool(self.config.get("drop_unmapped", False))
            reject_unmatched = bool(self.config.get("reject_unmatched", False))

            kept: list[dict[str, Any]] = []
            rejects: list[dict[str, Any]] = []

            for row in rows:
                if filter_expr:
                    try:
                        ok = bool(eval_expr(filter_expr, row))
                    except Exception:
                        ok = False
                    if not ok:
                        if reject_unmatched:
                            r = dict(row)
                            r["_reject_reason"] = f"tmap filter failed: {filter_expr}"
                            rejects.append(r)
                        continue

                if drop_unmapped:
                    new_row: dict[str, Any] = {}
                else:
                    new_row = dict(row)

                for out_col, expr in mappings:
                    try:
                        new_row[out_col] = eval_expr(expr, row)
                    except Exception as exc:
                        new_row[out_col] = None
                        ctx.emit(f"Field Mapper: expr failed for {out_col}={expr!r}: {exc}")

                kept.append(new_row)

            metrics.rows_in = len(rows)
            metrics.rows_out = len(kept)
            metrics.rows_rejected = len(rejects)
            ctx.emit(
                f"Field Mapper: {len(mappings)} mappings, kept {len(kept)}/{len(rows)} "
                f"(filter={filter_expr!r}, drop_unmapped={drop_unmapped})"
            )

        return ComponentResult(rows=kept, rejects=rejects, metrics=metrics)
