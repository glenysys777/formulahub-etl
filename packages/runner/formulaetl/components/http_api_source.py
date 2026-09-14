"""HTTP/REST API Source — fetch JSON and emit rows."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.connections import connection_id_param
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.registry import register

_RECORD_KEYS = ("records", "data", "items", "results", "rows")


def _parse_headers(raw: Any) -> dict[str, str]:
    """Accept dict, JSON string, or string_list of 'Key: Value' / 'Key=Value'."""
    if not raw:
        return {}
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return {}
        if s.startswith("{"):
            data = json.loads(s)
            return {str(k): str(v) for k, v in data.items()}
        lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
        return _headers_from_lines(lines)
    if isinstance(raw, list):
        return _headers_from_lines([str(x).strip() for x in raw if str(x).strip()])
    return {}


def _headers_from_lines(lines: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in lines:
        if ":" in line:
            k, v = line.split(":", 1)
        elif "=" in line:
            k, v = line.split("=", 1)
        else:
            continue
        out[k.strip()] = v.strip()
    return out


def _parse_query(raw: Any) -> dict[str, str]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return {}
        if s.startswith("{"):
            data = json.loads(s)
            return {str(k): str(v) for k, v in data.items()}
        lines = [ln.strip() for ln in s.replace("&", "\n").splitlines() if ln.strip()]
        return _headers_from_lines(lines)
    if isinstance(raw, list):
        return _headers_from_lines([str(x).strip() for x in raw if str(x).strip()])
    return {}


def _get_by_path(data: Any, path: str) -> Any:
    """Walk dotted path; supports list indices like items.0.name."""
    cur = data
    for part in path.split("."):
        if part == "":
            continue
        if isinstance(cur, dict):
            if part not in cur:
                raise KeyError(f"json_path segment '{part}' not found")
            cur = cur[part]
        elif isinstance(cur, list):
            idx = int(part)
            cur = cur[idx]
        else:
            raise KeyError(f"json_path cannot descend into {type(cur).__name__} at '{part}'")
    return cur


def _extract_rows(payload: Any, json_path: str | None) -> list[dict[str, Any]]:
    if json_path:
        payload = _get_by_path(payload, json_path)

    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        found = None
        for key in _RECORD_KEYS:
            val = payload.get(key)
            if isinstance(val, list):
                found = val
                break
            # nested e.g. data.items
            if isinstance(val, dict):
                for sub in _RECORD_KEYS:
                    if isinstance(val.get(sub), list):
                        found = val[sub]
                        break
            if found is not None:
                break
        rows = found if found is not None else [payload]
    else:
        raise ValueError(f"HTTP API response is not JSON object/array (got {type(payload).__name__})")

    out: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        if isinstance(row, dict):
            out.append(dict(row))
        else:
            out.append({"value": row, "_index": i})
    return out


@register
class HttpApiSource(BaseComponent):
    component_type = "http_api_source"
    display_name = "HTTP / REST API Source"
    category = "source"
    config_schema = {
        "type": "object",
        "required": ["url"],
        "properties": {
            "url": {"type": "string", "description": "Request URL"},
            "method": {"type": "string", "enum": ["GET", "POST"], "default": "GET"},
            "headers": {"description": "Headers as JSON, map, or Key: Value lines"},
            "query_params": {"description": "Query string params"},
            "body": {"type": "string", "description": "Request body (POST)"},
            "json_path": {
                "type": "string",
                "description": "Dotted path to array of objects, e.g. data.items",
            },
            "timeout_sec": {"type": "number", "default": 30},
            "auth_bearer": {"type": "string", "description": "Optional Bearer token"},
            "demo": {"type": "boolean", "default": False},
        },
    }
    parameters = [
        connection_id_param(),
        {"key": "url", "label": "URL", "type": "string", "required": True, "help": "HTTP(S) endpoint"},
        {
            "key": "method",
            "label": "Method",
            "type": "select",
            "required": False,
            "default": "GET",
            "options": ["GET", "POST"],
            "help": "HTTP method",
        },
        {
            "key": "headers",
            "label": "Headers",
            "type": "string_list",
            "required": False,
            "help": "One Key: Value per line (or JSON object string)",
        },
        {
            "key": "query_params",
            "label": "Query params",
            "type": "string_list",
            "required": False,
            "help": "One key=value per line",
        },
        {"key": "body", "label": "Body", "type": "string", "required": False, "help": "POST body (JSON text)"},
        {
            "key": "json_path",
            "label": "JSON path",
            "type": "string",
            "required": False,
            "help": "Path to array in response, e.g. data.items",
            "placeholder": "data.items",
        },
        {
            "key": "timeout_sec",
            "label": "Timeout (sec)",
            "type": "number",
            "required": False,
            "default": 30,
            "help": "Request timeout seconds",
        },
        {
            "key": "auth_bearer",
            "label": "Bearer token",
            "type": "secret",
            "required": False,
            "help": "Optional Authorization: Bearer token",
        },
        {
            "key": "demo",
            "label": "Demo fixture",
            "type": "boolean",
            "required": False,
            "default": False,
            "help": "Force demo fixture instead of live HTTP",
        },
    ]

    def _use_demo(self, ctx: RunContext) -> bool:
        if self.config.get("demo") is True:
            return True
        url = str(self.config.get("url") or "")
        demo_env = ctx.demo_mode or os.environ.get("FORMULAETL_DEMO") == "1"
        return demo_env and ("example.com" in url.lower())

    def _load_fixture(self, ctx: RunContext) -> Any:
        candidates = [
            ctx.resolve("fixtures/sample/api_orders.json"),
            Path(__file__).resolve().parents[4] / "fixtures" / "sample" / "api_orders.json",
        ]
        for path in candidates:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        raise FileNotFoundError(
            "HttpApiSource (demo): fixtures/sample/api_orders.json not found under work_dir"
        )

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            url = self.config["url"]
            method = str(self.config.get("method") or "GET").upper()
            json_path = self.config.get("json_path") or None
            if json_path == "":
                json_path = None

            if self._use_demo(ctx):
                payload = self._load_fixture(ctx)
                ctx.emit(f"HttpApiSource [demo]: fixture for {url} (json_path={json_path})")
                mode = "demo"
            else:
                import httpx

                headers = _parse_headers(self.config.get("headers"))
                params = _parse_query(self.config.get("query_params"))
                token = self.config.get("auth_bearer")
                if token:
                    headers.setdefault("Authorization", f"Bearer {token}")
                timeout = float(self.config.get("timeout_sec") or 30)
                body = self.config.get("body")
                kwargs: dict[str, Any] = {
                    "method": method,
                    "url": url,
                    "headers": headers or None,
                    "params": params or None,
                    "timeout": timeout,
                }
                if method == "POST" and body not in (None, ""):
                    # Prefer JSON body when it parses
                    try:
                        kwargs["json"] = json.loads(body) if isinstance(body, str) else body
                    except (json.JSONDecodeError, TypeError):
                        kwargs["content"] = body if isinstance(body, (bytes, bytearray)) else str(body).encode()

                with httpx.Client() as client:
                    resp = client.request(**kwargs)
                    resp.raise_for_status()
                    payload = resp.json()
                ctx.emit(f"HttpApiSource: {method} {url} → {resp.status_code}")
                mode = "http"

            out_rows = _extract_rows(payload, json_path)
            metrics.rows_in = 0
            metrics.rows_out = len(out_rows)
            ctx.emit(f"HttpApiSource: emitted {len(out_rows)} rows")

        return ComponentResult(
            rows=out_rows,
            metrics=metrics,
            side_effects={"mode": mode, "url": url, "method": method},
            artifacts={"payload_keys": list(payload.keys()) if isinstance(payload, dict) else None},
        )
