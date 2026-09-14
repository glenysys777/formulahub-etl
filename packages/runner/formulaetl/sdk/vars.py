"""Dynamic SQL / config variable resolution.

Supports namespaced refs in string configs and SQL text:

- ``${context.key}`` — active Job Context (DEV / QA / PROD / custom)
- ``${run.key}`` — run_id, pipeline_id, run_date, …
- ``${env.NAME}`` — process environment (explicit; not bare ``${NAME}``)
- ``${upstream.field}`` — field from the first upstream row
- ``${key}`` — merged param map (run_params + active context + extras)

Job Contexts live on ``pipeline.metadata.contexts``:

```json
{
  "active": "DEV",
  "sets": {
    "DEV": {"env": "dev"},
    "QA": {"env": "qa"},
    "PROD": {"env": "prod"}
  }
}
```

Optional ``metadata.run_params`` supplies run-scoped keys (e.g. ``run_date``).
Override the active context at runtime with ``FORMULAETL_CONTEXT``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

# ${context.env} | ${run.run_date} | ${env.HOME} | ${upstream.order_id} | ${run_date}
_VAR_RE = re.compile(r"\$\{([^{}]+)\}")

_SKIP_RESOLVE_KEYS = frozenset(
    {
        "connection_id",
        "token",
        "password",
        "passphrase",
        "secret",
        "api_key",
        "access_key",
        "secret_access_key",
        "private_key",
        "aws_secret_access_key",
        "auth_bearer",
    }
)


@dataclass
class VarScope:
    """Lookup tables for ``${…}`` substitution."""

    context: dict[str, Any] = field(default_factory=dict)
    run: dict[str, Any] = field(default_factory=dict)
    env: Mapping[str, str] = field(default_factory=lambda: os.environ)
    upstream: dict[str, Any] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    active_context: str = ""

    def lookup(self, expr: str) -> tuple[Any | None, str]:
        """Return ``(value_or_None, source)`` for a bare expression inside ``${…}``."""
        raw = (expr or "").strip()
        if not raw:
            return None, "empty"

        if raw.startswith("context."):
            key = raw[len("context.") :]
            if key in self.context:
                return self.context[key], "context"
            return None, "context"

        if raw.startswith("run."):
            key = raw[len("run.") :]
            if key in self.run:
                return self.run[key], "run"
            return None, "run"

        if raw.startswith("env."):
            key = raw[len("env.") :]
            if key in self.env:
                return self.env[key], "env"
            return None, "env"

        if raw.startswith("upstream."):
            key = raw[len("upstream.") :]
            if key in self.upstream:
                return self.upstream[key], "upstream"
            return None, "upstream"

        # Plain ${key}: params → context → run → upstream (never bare env)
        if key_in(self.params, raw):
            return self.params[raw], "params"
        if key_in(self.context, raw):
            return self.context[raw], "context"
        if key_in(self.run, raw):
            return self.run[raw], "run"
        if key_in(self.upstream, raw):
            return self.upstream[raw], "upstream"
        return None, "unresolved"


def key_in(d: Mapping[str, Any], key: str) -> bool:
    return key in d


def find_refs(text: str) -> list[str]:
    """Return unique ``${…}`` expressions (inner text) in order of first appearance."""
    seen: set[str] = set()
    out: list[str] = []
    for m in _VAR_RE.finditer(text or ""):
        inner = m.group(1).strip()
        if inner not in seen:
            seen.add(inner)
            out.append(inner)
    return out


def resolve_string(
    text: str,
    scope: VarScope,
    *,
    missing: str = "keep",
) -> str:
    """Substitute ``${…}`` in ``text``.

    ``missing``:
      - ``keep`` — leave unresolved refs as-is (default)
      - ``empty`` — replace with empty string
      - ``error`` — raise ``KeyError``
    """

    def repl(m: re.Match[str]) -> str:
        expr = m.group(1).strip()
        val, _src = scope.lookup(expr)
        if val is None:
            if missing == "error":
                raise KeyError(f"Unresolved variable ${{{expr}}}")
            if missing == "empty":
                return ""
            return m.group(0)
        return str(val)

    return _VAR_RE.sub(repl, text or "")


def resolve_value(value: Any, scope: VarScope, *, missing: str = "keep") -> Any:
    """Recursively resolve strings inside dicts/lists; leave other types unchanged."""
    if isinstance(value, str):
        return resolve_string(value, scope, missing=missing)
    if isinstance(value, list):
        return [resolve_value(v, scope, missing=missing) for v in value]
    if isinstance(value, dict):
        return {
            k: (
                v
                if str(k).lower() in _SKIP_RESOLVE_KEYS
                else resolve_value(v, scope, missing=missing)
            )
            for k, v in value.items()
        }
    return value


def resolve_map_values(
    mapping: dict[str, str], scope: VarScope, *, missing: str = "keep"
) -> dict[str, str]:
    """Resolve values of a string map (e.g. notebook_params)."""
    return {
        str(k): resolve_string(str(v), scope, missing=missing)
        for k, v in mapping.items()
    }


def preview_refs(
    text: str, scope: VarScope
) -> list[dict[str, str]]:
    """Table rows for Studio: key, value, source (no execution)."""
    rows: list[dict[str, str]] = []
    for expr in find_refs(text):
        val, source = scope.lookup(expr)
        rows.append(
            {
                "key": expr,
                "value": "" if val is None else str(val),
                "source": source if val is not None else "unresolved",
                "resolved": "false" if val is None else "true",
            }
        )
    return rows


def parse_contexts(metadata: dict[str, Any] | None) -> tuple[str, dict[str, dict[str, Any]]]:
    """Return ``(active_name, sets)`` from pipeline metadata."""
    meta = metadata or {}
    block = meta.get("contexts") or {}
    if not isinstance(block, dict):
        return "", {}
    sets_raw = block.get("sets") or {}
    sets: dict[str, dict[str, Any]] = {}
    if isinstance(sets_raw, dict):
        for name, vals in sets_raw.items():
            if isinstance(vals, dict):
                sets[str(name)] = {str(k): v for k, v in vals.items()}
    active = str(block.get("active") or "").strip()
    env_override = (os.environ.get("FORMULAETL_CONTEXT") or "").strip()
    if env_override:
        active = env_override
    if not active and sets:
        # Prefer common names, else first key
        for preferred in ("DEV", "dev", "QA", "qa", "PROD", "prod"):
            if preferred in sets:
                active = preferred
                break
        if not active:
            active = next(iter(sets))
    return active, sets


def build_run_vars(
    *,
    run_id: str,
    pipeline_id: str,
    run_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Standard ``${run.*}`` keys plus optional ``run_params``."""
    now = datetime.now(timezone.utc)
    base: dict[str, Any] = {
        "run_id": run_id,
        "pipeline_id": pipeline_id,
        "run_date": now.strftime("%Y-%m-%d"),
        "run_ts": now.strftime("%Y%m%dT%H%M%SZ"),
        "year": now.strftime("%Y"),
        "month": now.strftime("%m"),
        "day": now.strftime("%d"),
    }
    if run_params:
        for k, v in run_params.items():
            base[str(k)] = v
    return base


def build_scope(
    *,
    run_id: str,
    pipeline_id: str,
    metadata: dict[str, Any] | None = None,
    upstream_row: dict[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
    extra_params: dict[str, Any] | None = None,
) -> VarScope:
    """Build a ``VarScope`` from pipeline metadata + run identity."""
    meta = metadata or {}
    active, sets = parse_contexts(meta)
    context = dict(sets.get(active) or {})
    run_params = meta.get("run_params") if isinstance(meta.get("run_params"), dict) else {}
    run = build_run_vars(run_id=run_id, pipeline_id=pipeline_id, run_params=run_params)
    # Merged plain map: run_params + context (+ extras). Context wins over run_params.
    params: dict[str, Any] = {}
    params.update({str(k): v for k, v in (run_params or {}).items()})
    params.update(context)
    if extra_params:
        params.update({str(k): v for k, v in extra_params.items()})
    upstream: dict[str, Any] = {}
    if upstream_row:
        upstream = {
            str(k): v
            for k, v in upstream_row.items()
            if not str(k).startswith("_")
        }
    return VarScope(
        context=context,
        run=run,
        env=env if env is not None else os.environ,
        upstream=upstream,
        params=params,
        active_context=active,
    )


def bind_pipeline_variables(ctx: Any, pipeline: Any) -> VarScope:
    """Attach scope tables onto ``RunContext.variables`` and return the scope."""
    meta = getattr(pipeline, "metadata", None) or {}
    if not isinstance(meta, dict):
        meta = {}
    scope = build_scope(
        run_id=str(ctx.run_id),
        pipeline_id=str(getattr(pipeline, "id", ctx.pipeline_id)),
        metadata=meta,
    )
    ctx.variables["_var_scope"] = scope
    ctx.variables["_contexts_active"] = scope.active_context
    ctx.variables["context"] = dict(scope.context)
    ctx.variables["run"] = dict(scope.run)
    # Flatten common run keys for casual access
    for k, v in scope.run.items():
        ctx.variables.setdefault(k, v)
    for k, v in scope.context.items():
        ctx.variables.setdefault(k, v)
    return scope


def scope_from_context(
    ctx: Any, *, upstream_rows: list[dict[str, Any]] | None = None
) -> VarScope:
    """Refresh upstream slice of the bound scope (or rebuild a minimal one)."""
    base: VarScope | None = ctx.variables.get("_var_scope")
    row: dict[str, Any] | None = None
    if upstream_rows:
        row = upstream_rows[0]
    if base is None:
        return build_scope(
            run_id=str(ctx.run_id),
            pipeline_id=str(ctx.pipeline_id),
            upstream_row=row,
        )
    upstream: dict[str, Any] = {}
    if row:
        upstream = {
            str(k): v for k, v in row.items() if not str(k).startswith("_")
        }
    return VarScope(
        context=dict(base.context),
        run=dict(base.run),
        env=base.env,
        upstream=upstream,
        params=dict(base.params),
        active_context=base.active_context,
    )


def resolve_config_vars(
    config: dict[str, Any],
    ctx: Any,
    *,
    upstream_rows: list[dict[str, Any]] | None = None,
    missing: str = "keep",
) -> dict[str, Any]:
    """Apply ``${…}`` resolution to a node config (after secret/connection merge)."""
    scope = scope_from_context(ctx, upstream_rows=upstream_rows)
    ctx.variables["_var_scope"] = scope
    if scope.upstream:
        ctx.variables["upstream"] = dict(scope.upstream)
    return resolve_value(config, scope, missing=missing)
