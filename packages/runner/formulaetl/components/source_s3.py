"""S3 Source — boto3 with streaming download, retries, paginated prefix list.

DEMO=1 reads ``./data/s3`` mock objects. Live path uses the default credential
chain (IAM role / env / shared config) — never list an entire huge prefix into
a single in-memory list without pagination.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.capabilities import ARTIFACT_SOURCE
from formulaetl.sdk.connections import connection_id_param
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.data import ArtifactHandle
from formulaetl.sdk.io_util import boto3_client_kwargs, redact_secrets, retry_call
from formulaetl.sdk.registry import register


def iter_s3_keys(
    client: Any,
    *,
    bucket: str,
    prefix: str,
    page_size: int = 1000,
    max_keys: int | None = None,
) -> Iterator[dict[str, Any]]:
    """Paginated list of object summaries — never accumulates the full set."""
    token: str | None = None
    yielded = 0
    while True:
        kwargs: dict[str, Any] = {
            "Bucket": bucket,
            "Prefix": prefix or "",
            "MaxKeys": min(page_size, 1000),
        }
        if token:
            kwargs["ContinuationToken"] = token
        resp = client.list_objects_v2(**kwargs)
        for obj in resp.get("Contents") or []:
            yield {
                "key": obj["Key"],
                "size": obj.get("Size"),
                "etag": obj.get("ETag"),
                "last_modified": str(obj.get("LastModified") or ""),
            }
            yielded += 1
            if max_keys is not None and yielded >= max_keys:
                return
        if not resp.get("IsTruncated"):
            return
        token = resp.get("NextContinuationToken")
        if not token:
            return


@register
class S3Source(BaseComponent):
    component_type = "s3_source"
    display_name = "S3 Source"
    category = "source"
    capabilities = ARTIFACT_SOURCE
    config_schema = {
        "type": "object",
        "required": ["bucket"],
        "properties": {
            "bucket": {"type": "string"},
            "key": {"type": "string", "description": "Object key / path within bucket"},
            "prefix": {
                "type": "string",
                "description": "If set without key (or list_only), list keys under prefix (paginated)",
            },
            "list_only": {
                "type": "boolean",
                "default": False,
                "description": "Return paginated key listing as rows instead of downloading",
            },
            "max_keys": {
                "type": "integer",
                "description": "Optional cap when listing (still paginated under the hood)",
            },
            "page_size": {"type": "integer", "default": 1000},
            "endpoint_url": {"type": "string"},
            "region": {"type": "string", "default": "us-east-1"},
            "connect_timeout": {"type": "number", "default": 10},
            "read_timeout": {"type": "number", "default": 60},
            "max_attempts": {"type": "integer", "default": 5},
        },
    }
    parameters = [
        connection_id_param(),
        {"key": "bucket", "label": "Bucket", "type": "string", "required": True, "help": "S3 bucket name"},
        {"key": "key", "label": "Object key", "type": "string", "required": False, "help": "Object key / path within bucket"},
        {"key": "prefix", "label": "Prefix", "type": "string", "required": False, "help": "Optional prefix to list (paginated)"},
        {"key": "list_only", "label": "List only", "type": "boolean", "required": False, "default": False, "help": "List keys under prefix instead of downloading"},
        {"key": "region", "label": "Region", "type": "string", "required": False, "default": "us-east-1", "help": "AWS region"},
        {"key": "endpoint_url", "label": "Endpoint URL", "type": "string", "required": False, "help": "Custom S3-compatible endpoint"},
        {"key": "connect_timeout", "label": "Connect timeout (s)", "type": "number", "required": False, "default": 10},
        {"key": "read_timeout", "label": "Read timeout (s)", "type": "number", "required": False, "default": 60},
        {"key": "max_attempts", "label": "Max attempts", "type": "number", "required": False, "default": 5, "help": "botocore retry attempts"},
    ]

    def _demo_path(self, ctx: RunContext) -> Path:
        bucket = self.config["bucket"]
        key = self.config.get("key") or ""
        base = ctx.data_dir / "s3"
        candidate = base / bucket / key
        if candidate.exists():
            return candidate
        alt = base / key
        if alt.exists():
            return alt
        return candidate

    def _demo_list(self, ctx: RunContext) -> list[dict[str, Any]]:
        bucket = self.config["bucket"]
        prefix = (self.config.get("prefix") or self.config.get("key") or "").lstrip("/")
        root = ctx.data_dir / "s3"
        rows: list[dict[str, Any]] = []
        max_keys = self.config.get("max_keys")
        if not root.exists():
            return rows
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            rel = str(p.relative_to(root)).replace("\\", "/")
            if prefix and not rel.startswith(prefix):
                continue
            # Prefer keys that live under the configured bucket folder when present
            if (root / bucket).exists() and not rel.startswith(bucket + "/") and "/" in rel:
                continue
            rows.append(
                {
                    "_s3_bucket": bucket,
                    "_s3_key": rel,
                    "_size": p.stat().st_size,
                }
            )
            if max_keys is not None and len(rows) >= int(max_keys):
                break
        return rows

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            bucket = self.config["bucket"]
            key = self.config.get("key")
            prefix = self.config.get("prefix")
            list_only = bool(self.config.get("list_only", False))

            if ctx.demo_mode or os.environ.get("FORMULAETL_DEMO") == "1":
                if list_only or (prefix and not key):
                    listed = self._demo_list(ctx)
                    metrics.rows_out = len(listed)
                    ctx.emit(
                        f"S3Source [demo]: listed {len(listed)} object(s) under "
                        f"s3://{bucket}/{prefix or ''}"
                    )
                    return ComponentResult(
                        rows=listed,
                        metrics=metrics,
                        side_effects={"mode": "demo", "list_only": True},
                    )
                if not key:
                    raise ValueError("S3Source: 'key' is required unless list_only/prefix listing")
                path = self._demo_path(ctx)
                if not path.exists():
                    raise FileNotFoundError(
                        f"S3Source (demo): object not found at {path}. "
                        f"Expected mock object under data/s3/"
                    )
                handle = ArtifactHandle.from_path(path, content_type=None, temp=False)
                ctx.emit(
                    f"S3Source [demo]: s3://{bucket}/{key} → {path} "
                    f"({handle.size} bytes, sha256={handle.checksum})"
                )
                metrics.rows_out = 1
                return ComponentResult(
                    rows=[{"_s3_bucket": bucket, "_s3_key": key, "_size": handle.size}],
                    metrics=metrics,
                    artifacts={
                        "path": str(path),
                        "bucket": bucket,
                        "key": key,
                        "artifact": handle.to_dict(),
                    },
                    artifact=handle,
                    side_effects={"mode": "demo", "local_path": str(path)},
                )

            # Real S3 via boto3 — default credential chain + bounded retries
            import boto3

            kwargs = boto3_client_kwargs(
                region=self.config.get("region", "us-east-1"),
                endpoint_url=self.config.get("endpoint_url"),
                connect_timeout=float(self.config.get("connect_timeout") or 10),
                read_timeout=float(self.config.get("read_timeout") or 60),
                max_attempts=int(self.config.get("max_attempts") or 5),
            )
            # Optional explicit keys from a Connection (prefer IAM/env chain otherwise)
            if self.config.get("access_key_id") and (
                self.config.get("secret_access_key") or self.config.get("aws_secret_access_key")
            ):
                kwargs["aws_access_key_id"] = self.config["access_key_id"]
                kwargs["aws_secret_access_key"] = (
                    self.config.get("secret_access_key")
                    or self.config.get("aws_secret_access_key")
                )
            client = boto3.client("s3", **kwargs)

            if list_only or (prefix is not None and not key):
                page_size = int(self.config.get("page_size") or 1000)
                max_keys = self.config.get("max_keys")
                max_keys_i = int(max_keys) if max_keys is not None else None
                listed_rows: list[dict[str, Any]] = []
                # Cap materialization for the ComponentResult adapter; pagination
                # still walks the API page-by-page (no single giant ListObjects).
                hard_cap = max_keys_i if max_keys_i is not None else 10_000

                def _list() -> list[dict[str, Any]]:
                    out: list[dict[str, Any]] = []
                    for item in iter_s3_keys(
                        client,
                        bucket=bucket,
                        prefix=prefix or "",
                        page_size=page_size,
                        max_keys=hard_cap,
                    ):
                        out.append(
                            {
                                "_s3_bucket": bucket,
                                "_s3_key": item["key"],
                                "_size": item.get("size"),
                                "_etag": item.get("etag"),
                                "_last_modified": item.get("last_modified"),
                            }
                        )
                    return out

                listed_rows = retry_call(
                    _list,
                    attempts=int(self.config.get("max_attempts") or 5),
                    label=f"S3 list s3://{bucket}/{prefix or ''}",
                    retry_on=(OSError, TimeoutError, ConnectionError),
                    on_retry=lambda i, e: ctx.emit(
                        f"S3Source: list retry {i}: {redact_secrets(str(e))}"
                    ),
                )
                metrics.rows_out = len(listed_rows)
                ctx.emit(
                    f"S3Source: listed {len(listed_rows)} object(s) under "
                    f"s3://{bucket}/{prefix or ''} (paginated, cap={hard_cap})"
                )
                return ComponentResult(
                    rows=listed_rows,
                    metrics=metrics,
                    side_effects={
                        "mode": "aws",
                        "list_only": True,
                        "capped_at": hard_cap,
                    },
                )

            if not key:
                raise ValueError("S3Source: 'key' is required for download")

            staging = ctx.temp_dir() / bucket / key.replace("/", "_")
            staging.parent.mkdir(parents=True, exist_ok=True)

            def _download() -> None:
                # download_file streams to disk (multipart under the hood for large objects)
                client.download_file(Bucket=bucket, Key=key, Filename=str(staging))

            try:
                retry_call(
                    _download,
                    attempts=int(self.config.get("max_attempts") or 5),
                    label=f"S3 download s3://{bucket}/{key}",
                    retry_on=(OSError, TimeoutError, ConnectionError),
                    on_retry=lambda i, e: ctx.emit(
                        f"S3Source: download retry {i}: {redact_secrets(str(e))}"
                    ),
                )
            except Exception as exc:
                raise RuntimeError(
                    f"S3Source: failed to download s3://{bucket}/{key}: "
                    f"{redact_secrets(str(exc))}"
                ) from exc

            handle = ArtifactHandle.from_path(staging, temp=True)
            ctx.emit(
                f"S3Source: downloaded s3://{bucket}/{key} → {staging} "
                f"({handle.size} bytes)"
            )
            metrics.rows_out = 1
            return ComponentResult(
                rows=[{"_s3_bucket": bucket, "_s3_key": key, "_size": handle.size}],
                metrics=metrics,
                artifacts={
                    "path": str(staging),
                    "bucket": bucket,
                    "key": key,
                    "artifact": handle.to_dict(),
                },
                artifact=handle,
                side_effects={"mode": "aws", "local_path": str(staging)},
            )
