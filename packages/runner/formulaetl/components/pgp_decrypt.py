"""PGP Decrypt — decrypt .pgp/.gpg via path/temp (Phase C: bounded file hop).

pgpy still needs the ciphertext blob in-process to decrypt; we never put
plaintext ``bytes``/``content`` on the next hop when the output is large, never
log passphrases, and accept key *refs* (env) so private key material need not
live in pipeline JSON.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.capabilities import ARTIFACT_BLOCKING
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.data import ArtifactHandle, write_bytes_artifact
from formulaetl.sdk.io_util import redact_secrets, resolve_secret_ref
from formulaetl.sdk.registry import register

# Below this size we still attach a short content preview for tiny demo fixtures.
_CONTENT_PREVIEW_MAX = 64 * 1024


def _resolve_private_key_path(ctx: RunContext, config: dict[str, Any]) -> Path:
    """Prefer ``private_key_ref`` (env / ${VAR}) over an inline path in JSON."""
    ref = config.get("private_key_ref")
    if ref:
        resolved = resolve_secret_ref(str(ref))
        if not resolved:
            raise ValueError(
                f"PGPDecrypt: private_key_ref={ref!r} did not resolve to a path "
                "(set the env var to a filesystem path)"
            )
        key_path = ctx.resolve(resolved)
    else:
        raw = config.get("private_key_path")
        if not raw:
            raise ValueError(
                "PGPDecrypt: set private_key_path or private_key_ref "
                "(prefer ref so pipeline JSON has no key path for customers)"
            )
        key_path = ctx.resolve(str(raw))
    if not key_path.exists():
        raise FileNotFoundError(f"PGPDecrypt: private key not found: {key_path}")
    return key_path


def _resolve_passphrase(config: dict[str, Any]) -> str:
    ref = config.get("passphrase_ref")
    if ref:
        return resolve_secret_ref(str(ref)) or ""
    return str(config.get("passphrase") or "")


def _load_ciphertext(ctx: RunContext, config: dict[str, Any]) -> tuple[bytes, Path | None]:
    """Load ciphertext preferring a file path. Returns (bytes, source_path|None)."""
    input_path = config.get("input_path") or config.get("path")
    if input_path:
        ip = ctx.resolve(str(input_path))
        if ip.exists():
            return ip.read_bytes(), ip
    art = ctx.variables.get("upstream_artifact")
    if isinstance(art, dict) and art.get("path") and Path(art["path"]).exists():
        p = Path(art["path"])
        return p.read_bytes(), p
    if ctx.variables.get("upstream_path"):
        p = Path(ctx.variables["upstream_path"])
        if p.exists():
            return p.read_bytes(), p
    if "bytes" in config:
        b = config["bytes"]
        return (b if isinstance(b, bytes) else str(b).encode("utf-8")), None
    if ctx.variables.get("upstream_bytes"):
        return ctx.variables["upstream_bytes"], None
    raise ValueError("PGPDecrypt: no encrypted input (path/bytes/upstream)")


@register
class PGPDecrypt(BaseComponent):
    component_type = "pgp_decrypt"
    display_name = "PGP Decrypt"
    category = "security"
    capabilities = ARTIFACT_BLOCKING
    config_schema = {
        "type": "object",
        "properties": {
            "private_key_path": {
                "type": "string",
                "description": "Filesystem path to private key (demo). Prefer private_key_ref.",
            },
            "private_key_ref": {
                "type": "string",
                "description": "Env ref for key path, e.g. FORMULAETL_PGP_PRIVATE_KEY or ${VAR}",
            },
            "passphrase": {"type": "string", "default": ""},
            "passphrase_ref": {
                "type": "string",
                "description": "Env ref for passphrase — never logged",
            },
            "input_path": {
                "type": "string",
                "description": "Optional; otherwise uses upstream artifact path/bytes",
            },
            "output_path": {"type": "string"},
        },
    }
    parameters = [
        {"key": "private_key_path", "label": "Private key path", "type": "string", "required": False, "help": "Demo path; prefer private_key_ref for customers"},
        {"key": "private_key_ref", "label": "Private key ref", "type": "string", "required": False, "help": "Env var name / ${VAR} resolving to key path"},
        {"key": "passphrase", "label": "Passphrase", "type": "secret", "required": False, "default": "", "help": "Inline passphrase (prefer passphrase_ref)"},
        {"key": "passphrase_ref", "label": "Passphrase ref", "type": "string", "required": False, "help": "Env var for passphrase"},
        {"key": "input_path", "label": "Input path", "type": "string", "required": False, "help": "Optional; otherwise uses upstream artifact"},
        {"key": "output_path", "label": "Output path", "type": "string", "required": False, "help": "Optional decrypted output path"},
    ]

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            import pgpy
            from pgpy.errors import PGPError

            key_path = _resolve_private_key_path(ctx, self.config)
            passphrase = _resolve_passphrase(self.config)

            try:
                key, _ = pgpy.PGPKey.from_blob(key_path.read_text())
            except Exception as exc:
                raise ValueError(
                    f"PGPDecrypt: cannot load private key from {key_path}: "
                    f"{redact_secrets(str(exc))}"
                ) from exc

            raw, src_path = _load_ciphertext(ctx, self.config)
            metrics.rows_in = 1

            try:
                msg = pgpy.PGPMessage.from_blob(raw)
            except Exception as exc:
                raise ValueError(
                    f"PGPDecrypt: corrupt or non-PGP input"
                    f"{f' ({src_path})' if src_path else ''}: {redact_secrets(str(exc))}"
                ) from exc

            try:
                if key.is_protected:
                    with key.unlock(passphrase):
                        decrypted = key.decrypt(msg)
                else:
                    decrypted = key.decrypt(msg)
            except PGPError as exc:
                raise ValueError(
                    "PGPDecrypt: decryption failed (wrong key, wrong passphrase, "
                    f"or message not encrypted to this key): {redact_secrets(str(exc))}"
                ) from exc
            except Exception as exc:
                # Never include passphrase in the message
                raise ValueError(
                    f"PGPDecrypt: decryption failed: {redact_secrets(str(exc))}"
                ) from exc

            plaintext = decrypted.message
            if isinstance(plaintext, str):
                out_bytes = plaintext.encode("utf-8")
            else:
                out_bytes = bytes(plaintext)

            temp = True
            if self.config.get("output_path"):
                out_path = ctx.resolve(self.config["output_path"])
                temp = False
            else:
                out_path = ctx.temp_dir() / "pgp_decrypt.out"
            handle = write_bytes_artifact(out_path, out_bytes, temp=temp)

            ctx.emit(
                f"PGPDecrypt: decrypted {len(raw)} → {len(out_bytes)} bytes → {out_path}"
            )
            metrics.rows_out = 1

            artifacts: dict[str, Any] = {
                "path": str(out_path),
                "artifact": handle.to_dict(),
            }
            # Tiny demo fixtures may expose content for unit tests; large files stay path-only.
            if len(out_bytes) <= _CONTENT_PREVIEW_MAX and len(raw) <= _CONTENT_PREVIEW_MAX:
                try:
                    artifacts["content"] = out_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    artifacts["content"] = out_bytes.decode("utf-8", errors="replace")

        return ComponentResult(
            rows=[{"_decrypted_size": len(out_bytes)}],
            metrics=metrics,
            artifacts=artifacts,
            artifact=handle,
        )
