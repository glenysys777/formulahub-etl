"""Master / Child pipeline nesting helpers.

Cycle detection, depth limits, Job Context merge modes, and child publishes.
See ``docs/architecture/MASTER_CHILD_PIPELINES.md``.
"""

from __future__ import annotations

import os
from copy import deepcopy
from typing import Any

from formulaetl.models.pipeline import PipelineDefinition
from formulaetl.sdk.vars import parse_contexts


DEFAULT_MAX_DEPTH = 5

CONTEXT_MODES = frozenset({"inherit", "child_active", "override"})
ON_FAILURE_MODES = frozenset({"fail_master", "continue"})


class PipelineNestingError(ValueError):
    """Raised for cycles, depth limits, or invalid nesting config."""


def max_pipeline_depth() -> int:
    raw = (os.environ.get("FORMULAETL_PIPELINE_MAX_DEPTH") or "").strip()
    if not raw:
        return DEFAULT_MAX_DEPTH
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_MAX_DEPTH


def check_nesting(stack: list[str], child_pipeline_id: str) -> None:
    """Raise if adding ``child_pipeline_id`` would cycle or exceed max depth.

    ``stack`` is the list of pipeline ids already active (master first).
    Depth after nesting = ``len(stack) + 1``.
    """
    cid = (child_pipeline_id or "").strip()
    if not cid:
        raise PipelineNestingError("run_pipeline: pipeline_id is required")
    if cid in stack:
        chain = " → ".join([*stack, cid])
        raise PipelineNestingError(f"Pipeline cycle detected: {chain}")
    depth_after = len(stack) + 1
    limit = max_pipeline_depth()
    if depth_after > limit:
        raise PipelineNestingError(
            f"Pipeline nesting depth {depth_after} exceeds "
            f"FORMULAETL_PIPELINE_MAX_DEPTH={limit}"
        )


def _as_str_map(values: dict[str, Any] | None) -> dict[str, Any]:
    if not values:
        return {}
    return {str(k): v for k, v in values.items()}


def merge_child_metadata(
    *,
    master_metadata: dict[str, Any] | None,
    child_metadata: dict[str, Any] | None,
    context_mode: str = "inherit",
    context_name: str = "",
    run_params: dict[str, Any] | None = None,
    child_publishes: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build child pipeline metadata for a nested run (no secrets copied).

    - ``inherit``: active name = master's active; values = child set ⊕ master active values
    - ``child_active``: keep child's own active / sets
    - ``override``: active name = ``context_name``; values = child set ⊕ master set of that name
    """
    mode = (context_mode or "inherit").strip() or "inherit"
    if mode not in CONTEXT_MODES:
        raise PipelineNestingError(
            f"run_pipeline: invalid context_mode '{context_mode}' "
            f"(expected inherit|child_active|override)"
        )

    master_meta = dict(master_metadata or {})
    child_meta = deepcopy(dict(child_metadata or {}))

    master_active, master_sets = parse_contexts(master_meta)
    # parse_contexts applies FORMULAETL_CONTEXT — for child_active we must not
    # let that override when reading the child's *declared* active. Re-read raw.
    child_block = child_meta.get("contexts") if isinstance(child_meta.get("contexts"), dict) else {}
    child_sets_raw = child_block.get("sets") if isinstance(child_block.get("sets"), dict) else {}
    child_sets: dict[str, dict[str, Any]] = {}
    for name, vals in child_sets_raw.items():
        if isinstance(vals, dict):
            child_sets[str(name)] = {str(k): v for k, v in vals.items()}
    child_declared_active = str(child_block.get("active") or "").strip()

    if mode == "child_active":
        active = child_declared_active
        if not active and child_sets:
            active = next(iter(child_sets))
        # Still honor FORMULAETL_CONTEXT if set (runtime override for the whole process)
        env_override = (os.environ.get("FORMULAETL_CONTEXT") or "").strip()
        if env_override:
            active = env_override
        merged_values = dict(child_sets.get(active) or {})
    elif mode == "override":
        active = (context_name or "").strip()
        if not active:
            raise PipelineNestingError(
                "run_pipeline: context_name is required when context_mode=override"
            )
        merged_values = dict(child_sets.get(active) or {})
        merged_values.update(_as_str_map(master_sets.get(active)))
    else:  # inherit
        active = master_active
        if not active and child_sets:
            active = next(iter(child_sets))
        merged_values = dict(child_sets.get(active) or {})
        merged_values.update(_as_str_map(master_sets.get(active) if active else {}))
        # Prefer master's live active values (already includes FORMULAETL_CONTEXT on master)
        if active and active in master_sets:
            merged_values.update(_as_str_map(master_sets[active]))

    # Preserve all child sets; ensure the active set holds merged values for this run.
    sets_out = dict(child_sets)
    if active:
        sets_out[active] = merged_values
    elif merged_values:
        # No named active — still expose values under a synthetic set only if needed
        pass

    child_meta["contexts"] = {
        "active": active,
        "sets": sets_out,
    }

    # run_params: master base ← node run_params ← flatten child publishes for ${child.*}
    master_rp = master_meta.get("run_params") if isinstance(master_meta.get("run_params"), dict) else {}
    child_rp = child_meta.get("run_params") if isinstance(child_meta.get("run_params"), dict) else {}
    merged_rp: dict[str, Any] = {}
    merged_rp.update(_as_str_map(child_rp))
    merged_rp.update(_as_str_map(master_rp))
    merged_rp.update(_as_str_map(run_params))
    # Expose prior sibling publishes as nested map under run_params["_children"]
    # for bind; also flat child.* via VarScope.
    if child_publishes:
        merged_rp["_children"] = {
            str(k): dict(v) for k, v in child_publishes.items() if isinstance(v, dict)
        }
    child_meta["run_params"] = merged_rp
    return child_meta


def extract_publish(
    *,
    child_pipeline: PipelineDefinition,
    child_result: Any,
    publish_as: str,
    active_context: str = "",
    context_values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the publish map stored under master ``children[publish_as]``."""
    metrics = getattr(child_result, "metrics", None) or {}
    if not isinstance(metrics, dict):
        metrics = {}
    published: dict[str, Any] = {
        "status": getattr(child_result, "status", None),
        "run_id": getattr(child_result, "run_id", None),
        "pipeline_id": getattr(child_result, "pipeline_id", None)
        or getattr(child_pipeline, "id", None),
        "rows_in": metrics.get("rows_in", 0),
        "rows_out": metrics.get("rows_out", 0),
        "rows_rejected": metrics.get("rows_rejected", 0),
        "duration_ms": metrics.get("duration_ms", getattr(child_result, "duration_ms", 0)),
        "error": getattr(child_result, "error", None),
    }
    if active_context:
        published["context"] = active_context
    if context_values:
        # Non-secret context keys for chaining (shallow copy)
        for k, v in context_values.items():
            key = str(k).lower()
            if key in {
                "token",
                "password",
                "secret",
                "api_key",
                "passphrase",
                "private_key",
                "access_key",
                "secret_access_key",
                "aws_secret_access_key",
                "auth_bearer",
            }:
                continue
            published[f"context_{k}"] = v
            # Also expose bare key when not colliding with metrics
            if str(k) not in published:
                published[str(k)] = v

    meta = getattr(child_pipeline, "metadata", None) or {}
    if isinstance(meta, dict):
        declare = meta.get("publish")
        if isinstance(declare, dict):
            for k, v in declare.items():
                published[str(k)] = v
        # Common run_params worth chaining
        rp = meta.get("run_params") if isinstance(meta.get("run_params"), dict) else {}
        for k in ("run_date", "job_name", "env"):
            if k in rp and k not in published:
                published[k] = rp[k]

    published["publish_as"] = publish_as
    return published


def load_child_pipeline(
    pipeline_id: str,
    *,
    work_dir: Any,
    get_pipeline: Any | None = None,
) -> PipelineDefinition:
    """Resolve a child by store callback, then by relative JSON path."""
    from pathlib import Path

    from formulaetl.cli import load_pipeline

    pid = (pipeline_id or "").strip()
    if not pid:
        raise PipelineNestingError("run_pipeline: pipeline_id is required")

    if get_pipeline is not None:
        loaded = get_pipeline(pid)
        if loaded is not None:
            return loaded

    root = Path(work_dir)
    candidates = [
        root / pid,
        root / f"{pid}.json",
        Path(pid),
    ]
    # Also try demos/… relative paths as-is
    for path in candidates:
        try:
            resolved = path if path.is_absolute() else (root / path).resolve()
        except OSError:
            continue
        if resolved.is_file():
            return load_pipeline(resolved)

    raise PipelineNestingError(
        f"run_pipeline: child pipeline '{pid}' not found "
        f"(no store entry and no JSON under work_dir)"
    )
