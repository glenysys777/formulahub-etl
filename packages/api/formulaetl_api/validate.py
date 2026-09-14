"""Pipeline preflight validation (Phase G).

Structured checks only — no marketing fluff, no secret values in responses.
"""

from __future__ import annotations

from typing import Any, Callable

from formulaetl.models.pipeline import PipelineDefinition
from formulaetl.sdk.registry import create_component, get_component
from formulaetl.sdk.secrets import (
    secret_keys_for_component,
)

CheckSeverity = str  # "ok" | "warn" | "error"


def _check(
    *,
    code: str,
    severity: CheckSeverity,
    message: str,
    node_id: str | None = None,
    edge_id: str | None = None,
    keys: list[str] | None = None,
    connection_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    symbol = {"ok": "✓", "warn": "⚠", "error": "✗"}.get(severity, "?")
    item: dict[str, Any] = {
        "code": code,
        "severity": severity,
        "symbol": symbol,
        "message": message,
    }
    if node_id is not None:
        item["node_id"] = node_id
    if edge_id is not None:
        item["edge_id"] = edge_id
    if keys is not None:
        item["keys"] = keys
    if connection_id is not None:
        item["connection_id"] = connection_id
    if extra:
        item.update(extra)
    return item


def _parse_mappings(raw: Any) -> list[tuple[str, str]]:
    """Mirror column_map / tmap mapping presence without importing component internals."""
    if raw is None:
        return []
    if isinstance(raw, dict):
        return [(str(k), str(v)) for k, v in raw.items() if str(k).strip() and str(v).strip()]
    lines: list[str] = []
    if isinstance(raw, str):
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    elif isinstance(raw, list):
        # tmap may use list of {source, target, expression} or "old:new" strings
        out: list[tuple[str, str]] = []
        for item in raw:
            if isinstance(item, dict):
                src = item.get("source") or item.get("from") or item.get("old")
                tgt = item.get("target") or item.get("to") or item.get("new") or item.get("name")
                expr = item.get("expression") or item.get("expr")
                if tgt and (src or expr):
                    out.append((str(src or expr), str(tgt)))
                continue
            s = str(item).strip()
            if s:
                lines.append(s)
        if out:
            return out
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
            # bare target name still counts as a mapping presence for tmap-style
            if line:
                mappings.append((line, line))
            continue
        old, new = line.split(sep, 1)
        old, new = old.strip(), new.strip()
        if old and new:
            mappings.append((old, new))
    return mappings


def _is_explicit_secret_ref(value: Any) -> bool:
    """True for env:/secret:/${}/FORMULAETL_* refs — not bare uppercase like GET."""
    if not isinstance(value, str):
        return False
    raw = value.strip()
    if not raw:
        return False
    if raw.startswith("env:") or raw.startswith("secret:"):
        return True
    if raw.startswith("${") and raw.endswith("}"):
        return True
    if raw.startswith("FORMULAETL_") and raw.replace("_", "").isalnum():
        return True
    return False


def _collect_secret_refs(config: dict[str, Any], component_type: str) -> list[tuple[str, str]]:
    """Return (key, ref) pairs that are explicit secret refs on secret-ish keys."""
    keys = secret_keys_for_component(component_type)
    found: list[tuple[str, str]] = []
    for k, v in (config or {}).items():
        if not isinstance(v, str):
            continue
        raw = v.strip()
        if not _is_explicit_secret_ref(raw):
            continue
        # Prefer secret-typed keys; still flag clear refs on other keys
        if k in keys or raw.startswith(("env:", "secret:", "${")):
            found.append((k, raw))
    return found


def validate_pipeline_definition(
    pipeline: PipelineDefinition,
    *,
    get_connection: Callable[[str], Any] | None = None,
    secret_exists: Callable[[str], bool] | None = None,
    connection_test_status: Callable[[str], dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """Run structured preflight checks. Never executes the pipeline.

    Returns::
        {
          "ok": bool,
          "checks": [...],
          "summary": {"errors": n, "warnings": n, "ok": n},
        }
    """
    checks: list[dict[str, Any]] = []

    if not pipeline.nodes:
        checks.append(
            _check(
                code="empty_graph",
                severity="error",
                message="Pipeline has no nodes",
            )
        )
        return _finalize(checks)

    node_ids = {n.id for n in pipeline.nodes}
    if len(node_ids) != len(pipeline.nodes):
        checks.append(
            _check(
                code="duplicate_node_id",
                severity="error",
                message="Duplicate node ids in graph",
            )
        )

    # Edges reference existing nodes
    for e in pipeline.edges:
        if e.source not in node_ids or e.target not in node_ids:
            checks.append(
                _check(
                    code="dangling_edge",
                    severity="error",
                    message=f"Edge references unknown node (source={e.source}, target={e.target})",
                    edge_id=e.id,
                )
            )

    # Cycles + required port walk via topological_order
    try:
        order = pipeline.topological_order()
        checks.append(
            _check(
                code="graph_acyclic",
                severity="ok",
                message=f"Graph is acyclic ({len(order)} nodes in topo order)",
            )
        )
    except ValueError as exc:
        msg = str(exc)
        code = "cycle" if "cycle" in msg.lower() else "graph_invalid"
        checks.append(
            _check(
                code=code,
                severity="error",
                message=msg,
            )
        )

    # Isolated nodes (warn)
    connected: set[str] = set()
    for e in pipeline.edges:
        connected.add(e.source)
        connected.add(e.target)
    if pipeline.nodes and pipeline.edges:
        for n in pipeline.nodes:
            if n.id not in connected:
                checks.append(
                    _check(
                        code="isolated_node",
                        severity="warn",
                        message="Node has no edges",
                        node_id=n.id,
                    )
                )

    # Per-node checks
    for node in pipeline.nodes:
        ntype = node.type
        cfg = dict(node.config or {})

        # Unknown type
        try:
            get_component(ntype)
        except KeyError:
            checks.append(
                _check(
                    code="unknown_type",
                    severity="error",
                    message=f"Unknown component type '{ntype}'",
                    node_id=node.id,
                )
            )
            continue

        # Required parameters (match runner validate_config)
        try:
            create_component(ntype, cfg).validate_config()
            checks.append(
                _check(
                    code="required_params",
                    severity="ok",
                    message="Required parameters present",
                    node_id=node.id,
                )
            )
        except ValueError as exc:
            # Extract missing keys when possible
            keys: list[str] = []
            text = str(exc)
            if "missing required config:" in text:
                keys = [k.strip() for k in text.split(":", 1)[-1].split(",") if k.strip()]
            checks.append(
                _check(
                    code="missing_required",
                    severity="error",
                    message=text,
                    node_id=node.id,
                    keys=keys or None,
                )
            )

        # Schema / mapping presence for column_map and tmap (Formula Map family)
        if ntype in ("column_map", "tmap"):
            mappings = _parse_mappings(cfg.get("mappings"))
            if mappings:
                checks.append(
                    _check(
                        code="mapping_present",
                        severity="ok",
                        message=f"{len(mappings)} mapping(s) present",
                        node_id=node.id,
                        extra={"mapping_count": len(mappings)},
                    )
                )
            else:
                # If required_params already failed, still emit specific mapping code
                checks.append(
                    _check(
                        code="mapping_missing",
                        severity="error",
                        message="No usable mappings (expected old:new lines or mapping objects)",
                        node_id=node.id,
                        keys=["mappings"],
                    )
                )

        # connection_id resolve + optional test status
        cid = cfg.get("connection_id")
        if cid:
            cid_s = str(cid).strip()
            if get_connection is None:
                checks.append(
                    _check(
                        code="connection_unchecked",
                        severity="warn",
                        message="connection_id present but no connection store wired",
                        node_id=node.id,
                        connection_id=cid_s,
                    )
                )
            else:
                rec = get_connection(cid_s)
                if rec is None:
                    checks.append(
                        _check(
                            code="connection_missing",
                            severity="error",
                            message=f"connection_id '{cid_s}' not found",
                            node_id=node.id,
                            connection_id=cid_s,
                        )
                    )
                else:
                    kind = getattr(rec, "kind", None)
                    if kind is None and isinstance(rec, dict):
                        kind = rec.get("kind")
                    checks.append(
                        _check(
                            code="connection_resolves",
                            severity="ok",
                            message=f"connection_id resolves (kind={kind or '?'})",
                            node_id=node.id,
                            connection_id=cid_s,
                        )
                    )
                    if connection_test_status is not None:
                        status = connection_test_status(cid_s)
                        if status is not None:
                            ok = bool(status.get("ok"))
                            checks.append(
                                _check(
                                    code="connection_test",
                                    severity="ok" if ok else "warn",
                                    message=status.get("message")
                                    or ("last test ok" if ok else "last test failed"),
                                    node_id=node.id,
                                    connection_id=cid_s,
                                    extra={
                                        "test": {
                                            k: status[k]
                                            for k in status
                                            if k != "detail"
                                        }
                                    },
                                )
                            )

        # Secret refs resolve (existence only — never return values)
        if secret_exists is not None:
            for key, ref in _collect_secret_refs(cfg, ntype):
                # Redact ref shape in message (show prefix only)
                if ref.startswith("secret:"):
                    shown = "secret:<id>"
                elif ref.startswith("env:"):
                    shown = f"env:{ref[4:]}"
                elif ref.startswith("${") and ref.endswith("}"):
                    shown = ref
                else:
                    shown = "<ref>"
                if secret_exists(ref):
                    checks.append(
                        _check(
                            code="secret_resolves",
                            severity="ok",
                            message=f"Secret ref for '{key}' resolves ({shown})",
                            node_id=node.id,
                            keys=[key],
                        )
                    )
                else:
                    checks.append(
                        _check(
                            code="secret_unresolved",
                            severity="error",
                            message=f"Secret ref for '{key}' does not resolve ({shown})",
                            node_id=node.id,
                            keys=[key],
                        )
                    )

    return _finalize(checks)


def _finalize(checks: list[dict[str, Any]]) -> dict[str, Any]:
    errors = sum(1 for c in checks if c["severity"] == "error")
    warnings = sum(1 for c in checks if c["severity"] == "warn")
    oks = sum(1 for c in checks if c["severity"] == "ok")
    return {
        "ok": errors == 0,
        "checks": checks,
        "summary": {"errors": errors, "warnings": warnings, "ok": oks},
    }


def run_summary_from_detail(
    *,
    status: str,
    metrics: dict[str, Any],
    duration_ms: float,
    node_runs: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compact observability block for GET /api/runs/{id}."""
    nodes_success = sum(1 for n in node_runs if n.get("status") == "success")
    nodes_failed = sum(1 for n in node_runs if n.get("status") == "failed")
    rows_in = int(metrics.get("rows_in") or 0)
    rows_out = int(metrics.get("rows_out") or 0)
    rows_rejected = int(metrics.get("rows_rejected") or 0)
    # Prefer summed node_runs when metrics empty
    if node_runs and rows_in == 0 and rows_out == 0:
        rows_in = sum(int(n.get("rows_in") or 0) for n in node_runs)
        rows_out = sum(int(n.get("rows_out") or 0) for n in node_runs)
        rows_rejected = sum(int(n.get("rows_rejected") or 0) for n in node_runs)
    return {
        "status": status,
        "nodes_total": len(node_runs),
        "nodes_success": nodes_success,
        "nodes_failed": nodes_failed,
        "rows_in": rows_in,
        "rows_out": rows_out,
        "rows_rejected": rows_rejected,
        "duration_ms": duration_ms,
        "event_count": len(events),
    }
