"""SFTP Destination — upload local file to remote (demo writes to data/out/sftp_mock/)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.connections import connection_id_param
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.registry import register


def _demo_active(ctx: RunContext, host: str) -> bool:
    if ctx.demo_mode or os.environ.get("FORMULAETL_DEMO") == "1":
        return True
    return str(host or "").strip().lower() in ("demo", "localhost-demo", "sftp.demo")


def _resolve_local_file(ctx: RunContext, rows: list[dict[str, Any]] | None, config: dict) -> Path:
    """Pick local file from config path, upstream artifact, or first row metadata."""
    if config.get("local_path"):
        return ctx.resolve(str(config["local_path"]))
    up = ctx.variables.get("upstream_path")
    if up:
        p = Path(str(up))
        if p.exists():
            return p
    if rows:
        for r in rows:
            for key in ("_local_path", "path", "written_path"):
                if r.get(key):
                    p = Path(str(r[key]))
                    if not p.is_absolute():
                        p = ctx.resolve(str(r[key]))
                    if p.exists() and p.is_file():
                        return p
    raise FileNotFoundError(
        "SFTPDestination: no local file — set local_path or chain from a source with a path artifact"
    )


@register
class SFTPDestination(BaseComponent):
    component_type = "sftp_destination"
    display_name = "SFTP Destination"
    category = "destination"
    config_schema = {
        "type": "object",
        "required": ["host", "remote_path"],
        "properties": {
            "host": {"type": "string"},
            "port": {"type": "integer", "default": 22},
            "username": {"type": "string"},
            "password": {"type": "string"},
            "key_path": {"type": "string"},
            "remote_path": {"type": "string"},
            "local_path": {"type": "string"},
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
            "help": "SFTP port",
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
            "help": "Optional SSH private key path",
        },
        {
            "key": "remote_path",
            "label": "Remote path",
            "type": "string",
            "required": True,
            "help": "Destination path on the remote server (file or directory)",
        },
        {
            "key": "local_path",
            "label": "Local path",
            "type": "string",
            "required": False,
            "help": "Local file to upload (optional if chained from upstream path)",
        },
    ]

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            rows = rows or []
            host = str(self.config.get("host") or "demo")
            remote_path = str(self.config["remote_path"])
            local = _resolve_local_file(ctx, rows, self.config)
            if not local.exists():
                raise FileNotFoundError(f"SFTPDestination: local file not found: {local}")

            if _demo_active(ctx, host):
                mock_root = ctx.data_dir / "out" / "sftp_mock"
                mock_root.mkdir(parents=True, exist_ok=True)
                remote_name = Path(remote_path).name or local.name
                # Preserve nested remote dirs under mock root
                rel = remote_path.lstrip("/")
                if rel and not remote_path.endswith("/") and Path(rel).name:
                    dest = mock_root / rel
                elif remote_path.endswith("/"):
                    dest = mock_root / rel / local.name
                else:
                    dest = mock_root / remote_name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(local, dest)
                ctx.emit(
                    f"SFTPDestination [demo]: mocked upload {local.name} → "
                    f"data/out/sftp_mock/... ({dest})"
                )
                metrics.rows_in = len(rows)
                metrics.rows_out = len(rows)
                return ComponentResult(
                    rows=rows,
                    metrics=metrics,
                    artifacts={"path": str(dest), "remote_path": remote_path},
                    side_effects={
                        "mode": "demo",
                        "written_path": str(dest),
                        "remote_path": remote_path,
                        "local_path": str(local),
                        "note": "Demo mocks the wire; real SFTP needs credentials + FORMULAETL_DEMO=0",
                    },
                )

            import paramiko

            port = int(self.config.get("port") or 22)
            username = self.config.get("username") or ""
            password = self.config.get("password") or None
            key_path = self.config.get("key_path") or None
            if not username:
                raise ValueError("SFTPDestination: username required for real SFTP")

            remote_file = remote_path
            if remote_path.endswith("/"):
                remote_file = remote_path + local.name

            transport = paramiko.Transport((host, port))
            try:
                pkey = None
                if key_path:
                    kp = ctx.resolve(key_path)
                    pkey = paramiko.RSAKey.from_private_key_file(str(kp))
                transport.connect(username=username, password=password, pkey=pkey)
                sftp = paramiko.SFTPClient.from_transport(transport)
                assert sftp is not None
                try:
                    sftp.put(str(local), remote_file)
                finally:
                    sftp.close()
            finally:
                transport.close()

            ctx.emit(f"SFTPDestination: uploaded {local} → sftp://{host}:{port}{remote_file}")
            metrics.rows_in = len(rows)
            metrics.rows_out = len(rows)
            return ComponentResult(
                rows=rows,
                metrics=metrics,
                artifacts={"remote_path": remote_file, "local_path": str(local)},
                side_effects={
                    "mode": "sftp",
                    "remote_path": remote_file,
                    "local_path": str(local),
                },
            )
