"""SFTP Source — paramiko download with timeouts, retries, host-key checks.

DEMO=1 / host=demo mocks the wire via fixtures. Live path never silently
disables host-key verification outside explicit ``host_key_policy=auto_add``
(intended for lab only).
"""

from __future__ import annotations

import os
import shutil
import socket
from pathlib import Path
from typing import Any

from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.capabilities import ARTIFACT_SOURCE
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.data import ArtifactHandle
from formulaetl.sdk.io_util import redact_secrets, retry_call
from formulaetl.sdk.connections import connection_id_param
from formulaetl.sdk.registry import register


def _demo_active(ctx: RunContext, host: str) -> bool:
    if ctx.demo_mode or os.environ.get("FORMULAETL_DEMO") == "1":
        return True
    return str(host or "").strip().lower() in ("demo", "localhost-demo", "sftp.demo")


def _fixture_for_remote(ctx: RunContext, remote_path: str) -> Path:
    """Map remote_path to a local fixture under fixtures/sample/."""
    sample = ctx.work_dir / "fixtures" / "sample"
    name = Path(remote_path).name
    candidate = sample / name
    if candidate.exists():
        return candidate
    alt = sample / Path(remote_path).name
    if alt.exists():
        return alt
    for fallback in ("orders.xlsx", "orders_17cols.csv", "api_orders.json"):
        p = sample / fallback
        if p.exists():
            return p
    raise FileNotFoundError(
        f"SFTPSource (demo): no fixture for remote_path={remote_path!r} under {sample}"
    )


def _load_pkey(paramiko, key_path: Path, password: str | None):
    """Try common key types; clear error if none load."""
    errors: list[str] = []
    for loader in (
        getattr(paramiko, "Ed25519Key", None),
        getattr(paramiko, "ECDSAKey", None),
        paramiko.RSAKey,
        getattr(paramiko, "DSSKey", None),
    ):
        if loader is None:
            continue
        try:
            return loader.from_private_key_file(str(key_path), password=password)
        except Exception as exc:  # noqa: BLE001 — collect and re-raise clearly
            errors.append(f"{loader.__name__}: {redact_secrets(str(exc))}")
    raise ValueError(
        f"SFTPSource: cannot load private key {key_path}: " + "; ".join(errors)
    )


def _host_key_policy(paramiko, policy: str, known_hosts: Path | None):
    """Return (client_setup_fn). Default is reject unknown hosts."""
    policy = (policy or "reject").strip().lower()

    def setup(client) -> None:
        if known_hosts and known_hosts.exists():
            client.load_host_keys(str(known_hosts))
        system_kh = Path.home() / ".ssh" / "known_hosts"
        if system_kh.exists():
            try:
                client.load_host_keys(str(system_kh))
            except OSError:
                pass
        if policy in ("auto_add", "auto-add", "warning"):
            # auto_add is lab-only; warning still accepts but records.
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        else:
            client.set_missing_host_key_policy(paramiko.RejectPolicy())

    return setup


def _sftp_download(
    *,
    host: str,
    port: int,
    username: str,
    password: str | None,
    key_path: Path | None,
    remote_path: str,
    dest: Path,
    connect_timeout: float,
    timeout: float,
    host_key_policy: str,
    known_hosts: Path | None,
) -> None:
    import paramiko

    client = paramiko.SSHClient()
    _host_key_policy(paramiko, host_key_policy, known_hosts)(client)

    pkey = None
    if key_path is not None:
        pkey = _load_pkey(paramiko, key_path, password)

    try:
        client.connect(
            hostname=host,
            port=port,
            username=username,
            password=password if pkey is None else (password if not key_path else None),
            pkey=pkey,
            timeout=connect_timeout,
            allow_agent=False,
            look_for_keys=False,
            banner_timeout=connect_timeout,
            auth_timeout=connect_timeout,
        )
        transport = client.get_transport()
        if transport is not None:
            transport.set_keepalive(30)
        sftp = client.open_sftp()
        try:
            sftp.get_channel().settimeout(timeout)
            # Stream to disk — paramiko get writes in chunks, not whole-file RAM.
            dest.parent.mkdir(parents=True, exist_ok=True)
            sftp.get(remote_path, str(dest))
        finally:
            sftp.close()
    except paramiko.BadHostKeyException as exc:
        raise ConnectionError(
            f"SFTPSource: host key verification failed for {host}:{port} — "
            f"add the host to known_hosts or set host_key_policy only in lab "
            f"({redact_secrets(str(exc))})"
        ) from exc
    except paramiko.AuthenticationException as exc:
        raise PermissionError(
            f"SFTPSource: authentication failed for {username}@{host}:{port} "
            f"(password and/or key_path). {redact_secrets(str(exc))}"
        ) from exc
    except (socket.timeout, TimeoutError, OSError) as exc:
        raise TimeoutError(
            f"SFTPSource: connection/transfer timeout talking to {host}:{port} "
            f"({redact_secrets(str(exc))})"
        ) from exc
    except Exception as exc:
        raise RuntimeError(
            f"SFTPSource: download failed sftp://{host}:{port}{remote_path} — "
            f"{redact_secrets(str(exc))}"
        ) from exc
    finally:
        client.close()


@register
class SFTPSource(BaseComponent):
    component_type = "sftp_source"
    display_name = "SFTP Source"
    category = "source"
    capabilities = ARTIFACT_SOURCE
    config_schema = {
        "type": "object",
        "required": ["host", "remote_path", "local_staging_path"],
        "properties": {
            "host": {"type": "string"},
            "port": {"type": "integer", "default": 22},
            "username": {"type": "string"},
            "password": {"type": "string"},
            "key_path": {"type": "string"},
            "remote_path": {"type": "string"},
            "local_staging_path": {"type": "string"},
            "connect_timeout": {"type": "number", "default": 15},
            "timeout": {"type": "number", "default": 120},
            "max_retries": {"type": "integer", "default": 3},
            "host_key_policy": {
                "type": "string",
                "enum": ["reject", "warning", "auto_add"],
                "default": "reject",
                "description": "reject unknown hosts by default; auto_add is lab-only",
            },
            "known_hosts": {"type": "string"},
        },
    }
    parameters = [
        connection_id_param(),
        {
            "key": "host",
            "label": "Host",
            "type": "string",
            "required": True,
            "default": "demo",
            "help": "SFTP host (use 'demo' or FORMULAETL_DEMO=1 to mock)",
        },
        {
            "key": "port",
            "label": "Port",
            "type": "number",
            "required": False,
            "default": 22,
            "help": "SFTP port (default 22)",
        },
        {
            "key": "username",
            "label": "Username",
            "type": "string",
            "required": False,
            "help": "SFTP username (required for real SFTP)",
        },
        {
            "key": "password",
            "label": "Password",
            "type": "secret",
            "required": False,
            "help": "Password or leave empty when using key_path",
        },
        {
            "key": "key_path",
            "label": "Private key path",
            "type": "string",
            "required": False,
            "help": "Optional SSH private key path (RSA/Ed25519/ECDSA)",
        },
        {
            "key": "remote_path",
            "label": "Remote path",
            "type": "string",
            "required": True,
            "help": "Remote file path to download",
        },
        {
            "key": "local_staging_path",
            "label": "Local staging path",
            "type": "string",
            "required": True,
            "default": "data/out/sftp_staging/",
            "help": "Local directory or file path for the downloaded object",
        },
        {
            "key": "connect_timeout",
            "label": "Connect timeout (s)",
            "type": "number",
            "required": False,
            "default": 15,
            "help": "TCP/auth connect timeout seconds",
        },
        {
            "key": "timeout",
            "label": "Transfer timeout (s)",
            "type": "number",
            "required": False,
            "default": 120,
            "help": "Per-channel transfer timeout seconds",
        },
        {
            "key": "max_retries",
            "label": "Max retries",
            "type": "number",
            "required": False,
            "default": 3,
            "help": "Retry count for transient network failures",
        },
        {
            "key": "host_key_policy",
            "label": "Host key policy",
            "type": "string",
            "required": False,
            "default": "reject",
            "help": "reject (default) | warning | auto_add (lab only)",
        },
        {
            "key": "known_hosts",
            "label": "known_hosts path",
            "type": "string",
            "required": False,
            "help": "Optional known_hosts file for host-key verification",
        },
    ]

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            host = str(self.config.get("host") or "demo")
            remote_path = str(self.config["remote_path"])
            staging_cfg = str(self.config["local_staging_path"])
            staging = ctx.resolve(staging_cfg)

            if _demo_active(ctx, host):
                src = _fixture_for_remote(ctx, remote_path)
                if staging.suffix:
                    dest = staging
                    dest.parent.mkdir(parents=True, exist_ok=True)
                else:
                    staging.mkdir(parents=True, exist_ok=True)
                    dest = staging / src.name
                shutil.copy2(src, dest)
                handle = ArtifactHandle.from_path(dest, temp=False)
                ctx.emit(
                    f"SFTPSource [demo]: mocked sftp://{host}/{remote_path} "
                    f"← fixtures → {dest} ({handle.size} bytes)"
                )
                metrics.rows_out = 1
                return ComponentResult(
                    rows=[
                        {
                            "_sftp_host": host,
                            "_sftp_remote": remote_path,
                            "_local_path": str(dest),
                            "_size": handle.size,
                        }
                    ],
                    metrics=metrics,
                    artifacts={
                        "path": str(dest),
                        "remote_path": remote_path,
                        "artifact": handle.to_dict(),
                    },
                    artifact=handle,
                    side_effects={
                        "mode": "demo",
                        "local_path": str(dest),
                        "fixture": str(src),
                        "note": "Demo mocks the wire; real SFTP needs credentials + FORMULAETL_DEMO=0",
                    },
                )

            # Real SFTP via paramiko
            port = int(self.config.get("port") or 22)
            username = self.config.get("username") or ""
            password = self.config.get("password") or None
            key_cfg = self.config.get("key_path") or None
            if not username:
                raise ValueError("SFTPSource: username required for real SFTP")
            if not password and not key_cfg:
                raise ValueError(
                    "SFTPSource: provide password and/or key_path for authentication"
                )

            if staging.suffix:
                dest = staging
                dest.parent.mkdir(parents=True, exist_ok=True)
            else:
                staging.mkdir(parents=True, exist_ok=True)
                dest = staging / Path(remote_path).name

            key_path = ctx.resolve(key_cfg) if key_cfg else None
            if key_path is not None and not key_path.exists():
                raise FileNotFoundError(f"SFTPSource: key_path not found: {key_path}")

            connect_timeout = float(self.config.get("connect_timeout") or 15)
            timeout = float(self.config.get("timeout") or 120)
            max_retries = int(self.config.get("max_retries") or 3)
            host_key_policy = str(self.config.get("host_key_policy") or "reject")
            if host_key_policy == "auto_add":
                ctx.emit(
                    "SFTPSource: WARNING host_key_policy=auto_add — "
                    "unknown hosts will be accepted (lab only)"
                )
            kh_cfg = self.config.get("known_hosts")
            known_hosts = ctx.resolve(str(kh_cfg)) if kh_cfg else None

            def _once() -> None:
                _sftp_download(
                    host=host,
                    port=port,
                    username=username,
                    password=password,
                    key_path=key_path,
                    remote_path=remote_path,
                    dest=dest,
                    connect_timeout=connect_timeout,
                    timeout=timeout,
                    host_key_policy=host_key_policy,
                    known_hosts=known_hosts,
                )

            def _on_retry(attempt: int, exc: BaseException) -> None:
                ctx.emit(
                    f"SFTPSource: retry {attempt}/{max_retries} after "
                    f"{redact_secrets(str(exc))}"
                )

            retry_call(
                _once,
                attempts=max_retries,
                label=f"SFTP download {host}:{port}",
                retry_on=(TimeoutError, OSError, ConnectionError, RuntimeError),
                on_retry=_on_retry,
            )

            handle = ArtifactHandle.from_path(dest, temp=False)
            ctx.emit(
                f"SFTPSource: downloaded sftp://{host}:{port}{remote_path} → {dest} "
                f"({handle.size} bytes)"
            )
            metrics.rows_out = 1
            return ComponentResult(
                rows=[
                    {
                        "_sftp_host": host,
                        "_sftp_remote": remote_path,
                        "_local_path": str(dest),
                        "_size": handle.size,
                    }
                ],
                metrics=metrics,
                artifacts={
                    "path": str(dest),
                    "remote_path": remote_path,
                    "artifact": handle.to_dict(),
                },
                artifact=handle,
                side_effects={"mode": "sftp", "local_path": str(dest)},
            )
