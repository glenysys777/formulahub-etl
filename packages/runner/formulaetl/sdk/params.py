"""UI-facing parameter schema helpers for FormulaETL components."""

from __future__ import annotations

from typing import Any

PARAM_TYPES = frozenset({"string", "number", "boolean", "secret", "select", "string_list"})


def normalize_param(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize a parameter definition to the UI contract."""
    key = raw.get("key") or raw.get("name")
    if not key:
        raise ValueError(f"parameter missing key: {raw}")
    ptype = raw.get("type", "string")
    if ptype not in PARAM_TYPES:
        # Complex / freeform configs edit as JSON string in the inspector
        ptype = "string"
    out: dict[str, Any] = {
        "key": key,
        "label": raw.get("label") or str(key).replace("_", " ").title(),
        "type": ptype,
        "required": bool(raw.get("required", False)),
        "default": raw.get("default"),
        "help": raw.get("help") or raw.get("description") or "",
    }
    if raw.get("options"):
        out["options"] = list(raw["options"])
    if raw.get("placeholder"):
        out["placeholder"] = raw["placeholder"]
    return out


def derive_parameters_from_schema(config_schema: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Best-effort conversion from JSON-schema-like config_schema → parameters."""
    if not config_schema:
        return []
    props = config_schema.get("properties") or {}
    required = set(config_schema.get("required") or [])
    params: list[dict[str, Any]] = []
    for key, spec in props.items():
        if not isinstance(spec, dict):
            continue
        json_type = spec.get("type", "string")
        enum = spec.get("enum")
        if enum:
            ptype = "select"
            options = list(enum)
        elif json_type == "boolean":
            ptype = "boolean"
        elif json_type in ("number", "integer"):
            ptype = "number"
        elif json_type == "array":
            ptype = "string_list"
            options = None
        elif key.lower() in ("password", "passphrase", "secret", "token", "api_key"):
            ptype = "secret"
            options = None
        else:
            # objects and unknowns → string (JSON / free text in UI)
            ptype = "string"
            options = None
        raw: dict[str, Any] = {
            "key": key,
            "label": key.replace("_", " ").title(),
            "type": ptype,
            "required": key in required,
            "default": spec.get("default"),
            "help": spec.get("description") or "",
        }
        if options is not None:
            raw["options"] = options
        params.append(normalize_param(raw))
    return params


def resolve_parameters(
    explicit: list[dict[str, Any]] | None,
    config_schema: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Prefer explicit parameters; otherwise derive from config_schema."""
    if explicit:
        return [normalize_param(p) for p in explicit]
    return derive_parameters_from_schema(config_schema)
