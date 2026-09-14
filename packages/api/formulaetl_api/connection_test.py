"""Test Connection — short-lived checks without logging secrets."""

from __future__ import annotations

import os
from typing import Any

from formulaetl.sdk.io_util import redact_secrets


def test_connection_config(
    kind: str,
    config: dict[str, Any],
    *,
    demo_mode: bool = True,
) -> dict[str, Any]:
    """Attempt a minimal live check. Never includes secret values in the result."""
    kind = str(kind).lower()
    demo_env = demo_mode or os.environ.get("FORMULAETL_DEMO", "1") == "1"
    host = str(
        config.get("host")
        or config.get("workspace_host")
        or config.get("account")
        or config.get("url")
        or ""
    )
    host_l = host.lower()

    if demo_env and (
        host_l in ("", "demo", "localhost", "127.0.0.1")
        or "example.com" in host_l
        or config.get("demo") is True
        or (kind == "s3" and str(config.get("bucket") or "demo") in ("demo", ""))
        or (kind == "snowflake" and not config.get("account"))
        or (kind == "databricks" and not config.get("token"))
    ):
        return {
            "ok": True,
            "mode": "demo",
            "kind": kind,
            "message": f"Demo check OK for {kind} (FORMULAETL_DEMO=1 / demo host)",
        }

    try:
        if kind == "sftp":
            return _test_sftp(config)
        if kind == "s3":
            return _test_s3(config)
        if kind == "postgres":
            return _test_postgres(config)
        if kind == "snowflake":
            return _test_snowflake(config)
        if kind == "http":
            return _test_http(config)
        if kind == "databricks":
            return {
                "ok": False,
                "mode": "live",
                "kind": "databricks",
                "message": (
                    "LIVE Databricks connection test UNPROVEN in Community — "
                    "configure workspace_host + token and validate outside CI"
                ),
            }
        return {"ok": False, "mode": "live", "kind": kind, "message": f"Unknown kind '{kind}'"}
    except Exception as exc:
        return {
            "ok": False,
            "mode": "live",
            "kind": kind,
            "message": redact_secrets(str(exc)),
        }


def _test_sftp(config: dict[str, Any]) -> dict[str, Any]:
    import paramiko

    host = str(config.get("host") or "")
    port = int(config.get("port") or 22)
    username = str(config.get("username") or "")
    password = config.get("password") or None
    key_path = config.get("key_path")
    timeout = float(config.get("connect_timeout") or 10)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        kwargs: dict[str, Any] = {
            "hostname": host,
            "port": port,
            "username": username,
            "timeout": timeout,
            "allow_agent": False,
            "look_for_keys": False,
        }
        if key_path:
            kwargs["key_filename"] = str(key_path)
        if password:
            kwargs["password"] = password
        client.connect(**kwargs)
        transport = client.get_transport()
        ok = transport is not None and transport.is_active()
        return {
            "ok": bool(ok),
            "mode": "live",
            "kind": "sftp",
            "message": "SFTP auth OK" if ok else "SFTP transport inactive",
        }
    finally:
        client.close()


def _test_s3(config: dict[str, Any]) -> dict[str, Any]:
    import boto3

    from formulaetl.sdk.io_util import boto3_client_kwargs

    bucket = str(config.get("bucket") or "")
    kwargs = boto3_client_kwargs(
        region=config.get("region"),
        endpoint_url=config.get("endpoint_url"),
        connect_timeout=float(config.get("connect_timeout") or 10),
        read_timeout=float(config.get("read_timeout") or 30),
    )
    # Optional explicit keys from connection (prefer IAM/env)
    if config.get("access_key_id") and config.get("secret_access_key"):
        kwargs["aws_access_key_id"] = config["access_key_id"]
        kwargs["aws_secret_access_key"] = config["secret_access_key"]
    client = boto3.client("s3", **kwargs)
    if bucket:
        client.head_bucket(Bucket=bucket)
        return {
            "ok": True,
            "mode": "live",
            "kind": "s3",
            "message": f"S3 head_bucket OK for '{bucket}'",
        }
    client.list_buckets()
    return {"ok": True, "mode": "live", "kind": "s3", "message": "S3 list_buckets OK"}


def _test_postgres(config: dict[str, Any]) -> dict[str, Any]:
    import psycopg

    dsn = config.get("dsn")
    if not dsn:
        host = config.get("host") or "localhost"
        port = config.get("port") or 5432
        db = config.get("database") or config.get("dbname") or "postgres"
        user = config.get("user") or "postgres"
        password = config.get("password") or ""
        dsn = f"host={host} port={port} dbname={db} user={user} password={password}"
    with psycopg.connect(str(dsn), connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    return {"ok": True, "mode": "live", "kind": "postgres", "message": "Postgres SELECT 1 OK"}


def _test_snowflake(config: dict[str, Any]) -> dict[str, Any]:
    try:
        import snowflake.connector  # type: ignore
    except ImportError:
        return {
            "ok": False,
            "mode": "live",
            "kind": "snowflake",
            "message": "snowflake-connector-python not installed (optional extra)",
        }
    conn = snowflake.connector.connect(
        account=config.get("account"),
        user=config.get("user"),
        password=config.get("password"),
        warehouse=config.get("warehouse"),
        database=config.get("database"),
        schema=config.get("schema"),
        role=config.get("role"),
        login_timeout=15,
    )
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        cur.close()
    finally:
        conn.close()
    return {"ok": True, "mode": "live", "kind": "snowflake", "message": "Snowflake SELECT 1 OK"}


def _test_http(config: dict[str, Any]) -> dict[str, Any]:
    import httpx

    url = str(config.get("url") or config.get("base_url") or "")
    if not url:
        return {"ok": False, "mode": "live", "kind": "http", "message": "url/base_url required"}
    headers: dict[str, str] = {}
    token = config.get("auth_bearer") or config.get("token")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    timeout = float(config.get("timeout_sec") or 15)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        # Prefer HEAD; fall back to GET
        try:
            resp = client.head(url, headers=headers)
            if resp.status_code >= 400:
                resp = client.get(url, headers=headers)
        except httpx.HTTPError:
            resp = client.get(url, headers=headers)
    ok = resp.status_code < 500
    return {
        "ok": ok,
        "mode": "live",
        "kind": "http",
        "message": f"HTTP {resp.status_code} from target",
        "status_code": resp.status_code,
    }
