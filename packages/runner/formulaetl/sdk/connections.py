"""Reusable Connections — credential profiles referenced by ``connection_id``.

Nodes keep path/query/table settings in pipeline JSON; host/user/password live
on a Connection (secrets as refs only). Inline demo hosts still work when
``FORMULAETL_DEMO=1`` and no ``connection_id`` is set.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from formulaetl.sdk.secrets import (
    SecretProvider,
    is_masked,
    is_secret_ref,
    mask_config,
    resolve_secret_value,
    secret_keys_for_component,
)

# Wedge kinds for Customer #1 connectors.
CONNECTION_KINDS = frozenset({"sftp", "s3", "snowflake", "postgres", "http", "databricks"})

# Non-secret fields accepted per kind (others allowed but not validated strictly).
KIND_PUBLIC_FIELDS: dict[str, frozenset[str]] = {
    "sftp": frozenset(
        {"host", "port", "username", "key_path", "host_key_policy", "known_hosts", "connect_timeout"}
    ),
    "s3": frozenset(
        {"region", "endpoint_url", "bucket", "access_key_id", "connect_timeout", "read_timeout"}
    ),
    "snowflake": frozenset(
        {"account", "user", "warehouse", "database", "schema", "role", "demo_path"}
    ),
    "postgres": frozenset({"host", "port", "database", "user", "dbname", "dsn"}),
    "http": frozenset({"base_url", "url", "timeout_sec", "headers"}),
    "databricks": frozenset(
        {"workspace_host", "warehouse_id", "http_path", "job_id", "catalog", "schema"}
    ),
}

KIND_SECRET_FIELDS: dict[str, frozenset[str]] = {
    "sftp": frozenset({"password"}),
    "s3": frozenset({"secret_access_key", "aws_secret_access_key", "access_key"}),
    "snowflake": frozenset({"password"}),
    "postgres": frozenset({"password"}),
    "http": frozenset({"auth_bearer", "token", "api_key", "password"}),
    "databricks": frozenset({"token"}),
}

# Map component_type → expected connection kind (for soft validation).
COMPONENT_CONNECTION_KIND: dict[str, str] = {
    "sftp_source": "sftp",
    "sftp_destination": "sftp",
    "s3_source": "s3",
    "snowflake_destination": "snowflake",
    "postgres_source": "postgres",
    "postgres_destination": "postgres",
    "http_api_source": "http",
    "databricks_job": "databricks",
    "databricks_sql": "databricks",
}


@dataclass
class ConnectionRecord:
    id: str
    name: str
    kind: str
    config: dict[str, Any] = field(default_factory=dict)
    # Map of secret field → ref (env:… / secret:…); never plaintext in durable form ideally
    secrets: dict[str, str] = field(default_factory=dict)
    description: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_public_dict(self) -> dict[str, Any]:
        """API-safe view: secret values masked; refs preserved."""
        secret_keys = KIND_SECRET_FIELDS.get(self.kind, frozenset()) | set(self.secrets)
        cfg = dict(self.config)
        # Surface secret field presence as masked / ref
        secrets_view: dict[str, str] = {}
        for k, ref in self.secrets.items():
            if is_secret_ref(ref):
                secrets_view[k] = ref
            else:
                secrets_view[k] = "***"
            # Also place into config for UI convenience (masked)
            if k not in cfg or cfg[k]:
                cfg[k] = secrets_view[k]
        for k in secret_keys:
            if k in cfg and not is_secret_ref(cfg[k]) and cfg[k] not in (None, ""):
                cfg[k] = "***"
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "description": self.description,
            "config": mask_config(cfg),
            "secrets": secrets_view,
            "has_secrets": sorted(self.secrets.keys()),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def split_connection_payload(
    kind: str,
    config: dict[str, Any],
    secrets: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split a create/update body into public config vs secret field map."""
    secret_keys = set(KIND_SECRET_FIELDS.get(kind, frozenset()))
    public: dict[str, Any] = {}
    secret_vals: dict[str, Any] = dict(secrets or {})
    for k, v in (config or {}).items():
        if k in secret_keys or k in ("password", "auth_bearer", "token", "secret_access_key"):
            if v is not None and v != "" and not is_masked(v):
                secret_vals[k] = v
        else:
            public[k] = v
    return public, secret_vals


def merge_connection_into_config(
    node_config: dict[str, Any],
    connection: ConnectionRecord,
    provider: SecretProvider | None,
) -> dict[str, Any]:
    """Merge connection public fields + resolved secrets into a node config copy.

    Precedence: explicit non-empty node config overrides connection defaults.
    Secrets from the connection fill empty / masked node fields.
    ``connection_id`` is removed from the result (runtime-only merge).
    """
    merged = dict(connection.config)
    node = dict(node_config)
    node.pop("connection_id", None)

    secret_keys = set(KIND_SECRET_FIELDS.get(connection.kind, frozenset()))
    secret_keys |= set(connection.secrets)
    secret_keys |= secret_keys_for_component(None)

    for k, v in node.items():
        if k in secret_keys:
            if v in (None, "",) or is_masked(v):
                continue  # keep connection secret
            merged[k] = v
        else:
            merged[k] = v

    # Resolve connection secrets into merged config
    for sk, sref in connection.secrets.items():
        cur = merged.get(sk)
        if cur in (None, "") or is_masked(cur):
            resolved = resolve_secret_value(sref, provider)
            if resolved is not None:
                merged[sk] = resolved
        elif is_secret_ref(cur):
            resolved = resolve_secret_value(cur, provider)
            if resolved is not None:
                merged[sk] = resolved

    # Resolve any remaining refs on secret keys in the merged config
    for sk in list(merged.keys()):
        if sk in secret_keys and is_secret_ref(merged.get(sk)):
            resolved = resolve_secret_value(str(merged[sk]), provider)
            if resolved is not None:
                merged[sk] = resolved

    # http: map base_url → url when node did not set url
    if connection.kind == "http":
        if not merged.get("url") and merged.get("base_url"):
            merged["url"] = merged["base_url"]

    return merged


def resolve_node_config(
    node_config: dict[str, Any],
    *,
    component_type: str | None = None,
    get_connection: Callable[[str], ConnectionRecord | None] | None = None,
    provider: SecretProvider | None = None,
) -> dict[str, Any]:
    """Resolve ``connection_id`` + secret refs for a single node. Never mutates input."""
    cfg = dict(node_config or {})
    cid = cfg.get("connection_id")
    if cid and get_connection is not None:
        conn = get_connection(str(cid))
        if conn is None:
            raise ValueError(f"Unknown connection_id '{cid}'")
        expected = COMPONENT_CONNECTION_KIND.get(component_type or "")
        if expected and conn.kind != expected:
            # Soft warning path — still merge (design-partner flexibility)
            pass
        cfg = merge_connection_into_config(cfg, conn, provider)
    else:
        # Inline mode: resolve env/secret refs on secret keys only
        keys = secret_keys_for_component(component_type)
        for sk in list(cfg.keys()):
            if sk in keys and is_secret_ref(cfg.get(sk)):
                resolved = resolve_secret_value(str(cfg[sk]), provider)
                if resolved is not None:
                    cfg[sk] = resolved
        cfg.pop("connection_id", None)
    return cfg


def connection_id_param() -> dict[str, Any]:
    """Shared UI parameter for connector nodes."""
    return {
        "key": "connection_id",
        "label": "Connection",
        "type": "string",
        "required": False,
        "help": (
            "Optional reusable connection id (credentials via SecretProvider). "
            "Leave empty to use inline demo host/fields when FORMULAETL_DEMO=1."
        ),
    }
