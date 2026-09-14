"""PGP Encrypt — encrypt file/bytes with a public key (path/temp output)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.capabilities import ARTIFACT_BLOCKING
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.data import write_bytes_artifact
from formulaetl.sdk.io_util import redact_secrets, resolve_secret_ref
from formulaetl.sdk.registry import register

_CONTENT_PREVIEW_MAX = 64 * 1024


def _resolve_public_key_path(ctx: RunContext, config: dict[str, Any]) -> Path:
    ref = config.get("public_key_ref")
    if ref:
        resolved = resolve_secret_ref(str(ref))
        if not resolved:
            raise ValueError(
                f"PGPEncrypt: public_key_ref={ref!r} did not resolve to a path"
            )
        key_path = ctx.resolve(resolved)
    else:
        raw = config.get("public_key_path")
        if not raw:
            raise ValueError("PGPEncrypt: set public_key_path or public_key_ref")
        key_path = ctx.resolve(str(raw))
    if not key_path.exists():
        raise FileNotFoundError(f"PGPEncrypt: public key not found: {key_path}")
    return key_path


def _load_plaintext(ctx: RunContext, config: dict[str, Any], rows: list[dict[str, Any]] | None) -> bytes:
    input_path = config.get("input_path") or config.get("path")
    if input_path:
        ip = ctx.resolve(str(input_path))
        if ip.exists():
            return ip.read_bytes()
    if "bytes" in config:
        b = config["bytes"]
        return b if isinstance(b, bytes) else str(b).encode("utf-8")
    if "content" in config:
        return str(config["content"]).encode("utf-8")
    art = ctx.variables.get("upstream_artifact")
    if isinstance(art, dict) and art.get("path") and Path(art["path"]).exists():
        return Path(art["path"]).read_bytes()
    if ctx.variables.get("upstream_path"):
        p = Path(ctx.variables["upstream_path"])
        if p.exists():
            return p.read_bytes()
    if ctx.variables.get("upstream_bytes"):
        return ctx.variables["upstream_bytes"]
    if ctx.variables.get("upstream_content"):
        return str(ctx.variables["upstream_content"]).encode("utf-8")
    if rows and len(rows) == 1 and rows[0].get("content") is not None:
        return str(rows[0]["content"]).encode("utf-8")
    raise ValueError("PGPEncrypt: no plaintext input (path/bytes/content/upstream)")


@register
class PGPEncrypt(BaseComponent):
    component_type = "pgp_encrypt"
    display_name = "PGP Encrypt"
    category = "security"
    capabilities = ARTIFACT_BLOCKING
    config_schema = {
        "type": "object",
        "properties": {
            "public_key_path": {"type": "string"},
            "public_key_ref": {
                "type": "string",
                "description": "Env ref for public key path",
            },
            "input_path": {
                "type": "string",
                "description": "Optional; otherwise uses upstream artifact path/bytes/content",
            },
            "output_path": {"type": "string"},
            "armor": {
                "type": "boolean",
                "default": True,
                "description": "ASCII-armor the ciphertext",
            },
        },
    }
    parameters = [
        {
            "key": "public_key_path",
            "label": "Public key path",
            "type": "string",
            "required": False,
            "default": "fixtures/keys/demo_public.asc",
            "help": "Path to PGP public key (.asc)",
        },
        {
            "key": "public_key_ref",
            "label": "Public key ref",
            "type": "string",
            "required": False,
            "help": "Env var / ${VAR} resolving to public key path",
        },
        {
            "key": "input_path",
            "label": "Input path",
            "type": "string",
            "required": False,
            "help": "Optional plaintext file; else uses upstream bytes/content",
        },
        {
            "key": "output_path",
            "label": "Output path",
            "type": "string",
            "required": False,
            "help": "Optional path for encrypted output",
        },
        {
            "key": "armor",
            "label": "ASCII armor",
            "type": "boolean",
            "required": False,
            "default": True,
            "help": "Write ASCII-armored ciphertext",
        },
    ]

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            import pgpy

            key_path = _resolve_public_key_path(ctx, self.config)
            try:
                key, _ = pgpy.PGPKey.from_blob(key_path.read_text())
            except Exception as exc:
                raise ValueError(
                    f"PGPEncrypt: cannot load public key from {key_path}: "
                    f"{redact_secrets(str(exc))}"
                ) from exc

            armor = bool(self.config.get("armor", True))
            raw = _load_plaintext(ctx, self.config, rows)
            metrics.rows_in = 1

            try:
                msg = pgpy.PGPMessage.new(raw, file=True)
                cipher = key.encrypt(msg)
            except Exception as exc:
                raise ValueError(
                    f"PGPEncrypt: encryption failed: {redact_secrets(str(exc))}"
                ) from exc

            if armor:
                out_bytes = str(cipher).encode("utf-8")
                content = str(cipher)
            else:
                out_bytes = bytes(cipher)
                content = out_bytes.decode("utf-8", errors="replace")

            temp = True
            if self.config.get("output_path"):
                out_path = ctx.resolve(self.config["output_path"])
                temp = False
            else:
                out_path = ctx.temp_dir() / "pgp_encrypt.out"
            handle = write_bytes_artifact(out_path, out_bytes, temp=temp)

            ctx.emit(
                f"PGPEncrypt: encrypted {len(raw)} → {len(out_bytes)} bytes "
                f"(armor={armor}) → {out_path}"
            )
            metrics.rows_out = 1

            artifacts: dict[str, Any] = {
                "path": str(out_path),
                "artifact": handle.to_dict(),
            }
            # Tiny payloads may expose bytes for unit tests; large inputs stay path-only.
            if len(raw) <= _CONTENT_PREVIEW_MAX and len(out_bytes) <= _CONTENT_PREVIEW_MAX:
                artifacts["bytes"] = out_bytes
                artifacts["content"] = content

        return ComponentResult(
            rows=[{"_encrypted_size": len(out_bytes)}],
            metrics=metrics,
            artifacts=artifacts,
            artifact=handle,
        )
