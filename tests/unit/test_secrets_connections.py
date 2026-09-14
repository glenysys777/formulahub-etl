"""Unit tests for SecretProvider + connection merge (Phase F)."""

from __future__ import annotations

from formulaetl.sdk.connections import (
    ConnectionRecord,
    merge_connection_into_config,
    resolve_node_config,
)
from formulaetl.sdk.secrets import (
    CompositeSecretProvider,
    EnvSecretProvider,
    MemorySecretStore,
    is_secret_ref,
    mask_config,
    resolve_secret_value,
    strip_secrets_for_ai,
)


def test_env_and_memory_secret_refs(monkeypatch):
    monkeypatch.setenv("MY_TOKEN", "abc123")
    env = EnvSecretProvider()
    mem = MemorySecretStore()
    ref = mem.put("tok", "stored-value")
    assert ref.startswith("secret:")
    provider = CompositeSecretProvider(env, mem)
    assert provider.get("env:MY_TOKEN") == "abc123"
    assert provider.get("${MY_TOKEN}") == "abc123"
    assert provider.get(ref) == "stored-value"
    assert is_secret_ref(ref)
    assert is_secret_ref("env:MY_TOKEN")
    assert not is_secret_ref("plain-password")


def test_mask_and_strip_for_ai():
    cfg = {"host": "sftp.example", "password": "sekrit", "remote_path": "/a"}
    masked = mask_config(cfg, component_type="sftp_source")
    assert masked["password"] == "***"
    assert masked["host"] == "sftp.example"
    stripped = strip_secrets_for_ai(cfg, component_type="sftp_source")
    assert stripped["password"] == "[omitted]"
    # refs preserved
    cfg2 = {"password": "env:FOO"}
    assert strip_secrets_for_ai(cfg2)["password"] == "env:FOO"


def test_merge_connection_resolves_secrets(monkeypatch):
    monkeypatch.setenv("SF_PASS", "snow-pass")
    mem = MemorySecretStore()
    provider = CompositeSecretProvider(EnvSecretProvider(), mem)
    conn = ConnectionRecord(
        id="c1",
        name="sf",
        kind="snowflake",
        config={"account": "xy123", "user": "etl", "database": "D"},
        secrets={"password": "env:SF_PASS"},
    )
    merged = merge_connection_into_config(
        {"connection_id": "c1", "table": "ORDERS"},
        conn,
        provider,
    )
    assert "connection_id" not in merged
    assert merged["account"] == "xy123"
    assert merged["table"] == "ORDERS"
    assert merged["password"] == "snow-pass"


def test_resolve_node_config_unknown_connection():
    try:
        resolve_node_config(
            {"connection_id": "missing"},
            get_connection=lambda _cid: None,
            provider=EnvSecretProvider(),
        )
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "Unknown connection_id" in str(exc)


def test_resolve_secret_value_literal():
    assert resolve_secret_value("plain", EnvSecretProvider()) == "plain"
    assert resolve_secret_value("***", EnvSecretProvider()) is None
