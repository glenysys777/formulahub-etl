"""SFTP Source — download remote file(s) via paramiko (demo mocks the wire)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.capabilities import ARTIFACT_SOURCE
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.data import ArtifactHandle
from formulaetl.sdk.registry import register


def _demo_active(ctx: RunContext, host: str) -> bool:
    if ctx.demo_mode or os.environ.get("FORMULAETL_DEMO") == "1":
        return True
    return str(host or "").strip().lower() in ("demo", "localhost-demo", "sftp.demo")


def _fixture_for_remote(ctx: RunContext, remote_path: str) -> Path:
    """Map remote_path to a local fixture under fixtures/sample/."""
    sample = ctx.work_dir / "fixtures" / "sample"
    name = Path(remote_path).name
    # Prefer exact basename match
    candidate = sample / name
    if candidate.exists():
        return candidate
    # Allow remote_path like demo/orders.xlsx → fixtures/sample/orders.xlsx
    alt = sample / Path(remote_path).name
    if alt.exists():
        return alt
    # Common demo aliases
    for fallback in ("orders.xlsx", "orders_17cols.csv", "api_orders.json"):
        p = sample / fallback
        if p.exists():
            return p
    raise FileNotFoundError(
        f"SFTPSource (demo): no fixture for remote_path={remote_path!r} under {sample}"
    )


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
        },
    }
    parameters = [
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
            "help": "Optional SSH private key path",
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
            import paramiko

            port = int(self.config.get("port") or 22)
            username = self.config.get("username") or ""
            password = self.config.get("password") or None
            key_path = self.config.get("key_path") or None
            if not username:
                raise ValueError("SFTPSource: username required for real SFTP")

            if staging.suffix:
                dest = staging
                dest.parent.mkdir(parents=True, exist_ok=True)
            else:
                staging.mkdir(parents=True, exist_ok=True)
                dest = staging / Path(remote_path).name

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
                    sftp.get(remote_path, str(dest))
                finally:
                    sftp.close()
            finally:
                transport.close()

            handle = ArtifactHandle.from_path(dest, temp=False)
            ctx.emit(f"SFTPSource: downloaded sftp://{host}:{port}{remote_path} → {dest}")
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
