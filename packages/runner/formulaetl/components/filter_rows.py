"""Filter — row filter expressions."""

from __future__ import annotations

import ast
import operator
from typing import Any

from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.registry import register

_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.And: lambda a, b: a and b,
    ast.Or: lambda a, b: a or b,
}


def _eval_node(node: ast.AST, row: dict[str, Any]) -> Any:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, row)
    if isinstance(node, ast.BoolOp):
        op = _OPS[type(node.op)]
        vals = [_eval_node(v, row) for v in node.values]
        result = vals[0]
        for v in vals[1:]:
            result = op(result, v)
        return result
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _eval_node(node.operand, row)
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, row)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval_node(comparator, row)
            if not _OPS[type(op)](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.Name):
        return row.get(node.id)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Str):  # py<3.12 compat
        return node.s
    if isinstance(node, ast.Num):
        return node.n
    raise ValueError(f"Unsupported expression node: {type(node).__name__}")


def eval_filter(expr: str, row: dict[str, Any]) -> bool:
    """Safely evaluate a simple comparison expression against a row."""
    tree = ast.parse(expr, mode="eval")
    return bool(_eval_node(tree, row))


@register
class Filter(BaseComponent):
    component_type = "filter"
    display_name = "Filter"
    category = "transform"
    config_schema = {
        "type": "object",
        "required": ["expression"],
        "properties": {
            "expression": {
                "type": "string",
                "description": "Python-like expression, e.g. status == 'active' and amount > 0",
            },
        },
    }
    parameters = [
        {"key": "expression", "label": "Expression", "type": "string", "required": True, "help": "Python-like expression, e.g. status == 'active' and amount > 0"},
    ]

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            rows = rows or []
            expr = self.config["expression"]
            kept: list[dict[str, Any]] = []
            dropped: list[dict[str, Any]] = []
            for row in rows:
                try:
                    if eval_filter(expr, row):
                        kept.append(row)
                    else:
                        dropped.append(row)
                except Exception:
                    dropped.append(row)
            metrics.rows_in = len(rows)
            metrics.rows_out = len(kept)
            metrics.rows_rejected = len(dropped)
            ctx.emit(f"Filter: kept {len(kept)} / {len(rows)} (expr={expr!r})")

        return ComponentResult(rows=kept, rejects=dropped, metrics=metrics)
