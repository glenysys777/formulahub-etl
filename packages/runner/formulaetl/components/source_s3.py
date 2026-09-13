"""S3 Source — boto3-compatible; demo mode reads ./data/s3 mock bucket."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.registry import register


@register
class S3Source(BaseComponent):
    component_type = "s3_source"
    display_name = "S3 Source"
    category = "source"
    config_schema = {
        "type": "object",
        "required": ["bucket", "key"],
        "properties": {
            "bucket": {"type": "string"},
            "key": {"type": "string", "description": "Object key / path within bucket"},
            "prefix": {"type": "string", "description": "Optional prefix to list"},
            "endpoint_url": {"type": "string"},
            "region": {"type": "string", "default": "us-east-1"},
        },
    }
    parameters = [
        {"key": "bucket", "label": "Bucket", "type": "string", "required": True, "help": "S3 bucket name"},
        {"key": "key", "label": "Object key", "type": "string", "required": True, "help": "Object key / path within bucket"},
        {"key": "prefix", "label": "Prefix", "type": "string", "required": False, "help": "Optional prefix to list"},
        {"key": "region", "label": "Region", "type": "string", "required": False, "default": "us-east-1", "help": "AWS region"},
        {"key": "endpoint_url", "label": "Endpoint URL", "type": "string", "required": False, "help": "Custom S3-compatible endpoint"},
    ]

    def _demo_path(self, ctx: RunContext) -> Path:
        bucket = self.config["bucket"]
        key = self.config["key"]
        # ./data/s3/<bucket>/<key> or ./data/s3/<key> if bucket is 'demo'
        base = ctx.data_dir / "s3"
        candidate = base / bucket / key
        if candidate.exists():
            return candidate
        # Fallback: treat key as path under data/s3
        alt = base / key
        if alt.exists():
            return alt
        # Also try data/s3/demo/key when bucket=demo
        return candidate

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            bucket = self.config["bucket"]
            key = self.config["key"]

            if ctx.demo_mode or os.environ.get("FORMULAETL_DEMO") == "1":
                path = self._demo_path(ctx)
                if not path.exists():
                    raise FileNotFoundError(
                        f"S3Source (demo): object not found at {path}. "
                        f"Expected mock object under data/s3/"
                    )
                raw = path.read_bytes()
                ctx.emit(f"S3Source [demo]: s3://{bucket}/{key} → {path} ({len(raw)} bytes)")
                metrics.rows_out = 1
                return ComponentResult(
                    rows=[{"_s3_bucket": bucket, "_s3_key": key, "_size": len(raw)}],
                    metrics=metrics,
                    artifacts={"path": str(path), "bytes": raw, "bucket": bucket, "key": key},
                    side_effects={"mode": "demo", "local_path": str(path)},
                )

            # Real S3 via boto3
            import boto3

            kwargs: dict[str, Any] = {"region_name": self.config.get("region", "us-east-1")}
            if self.config.get("endpoint_url"):
                kwargs["endpoint_url"] = self.config["endpoint_url"]
            client = boto3.client("s3", **kwargs)
            obj = client.get_object(Bucket=bucket, Key=key)
            raw = obj["Body"].read()
            ctx.emit(f"S3Source: downloaded s3://{bucket}/{key} ({len(raw)} bytes)")
            metrics.rows_out = 1
            return ComponentResult(
                rows=[{"_s3_bucket": bucket, "_s3_key": key, "_size": len(raw)}],
                metrics=metrics,
                artifacts={"bytes": raw, "bucket": bucket, "key": key},
                side_effects={"mode": "aws"},
            )
