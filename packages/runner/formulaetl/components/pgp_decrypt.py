"""PGP Decrypt — decrypt .pgp/.gpg files with a private key."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.registry import register


@register
class PGPDecrypt(BaseComponent):
    component_type = "pgp_decrypt"
    display_name = "PGP Decrypt"
    category = "security"
    config_schema = {
        "type": "object",
        "required": ["private_key_path"],
        "properties": {
            "private_key_path": {"type": "string"},
            "passphrase": {"type": "string", "default": ""},
            "input_path": {
                "type": "string",
                "description": "Optional; otherwise uses upstream artifact path/bytes",
            },
            "output_path": {"type": "string"},
        },
    }
    parameters = [
        {"key": "private_key_path", "label": "Private key path", "type": "string", "required": True, "help": "Path to PGP private key file"},
        {"key": "passphrase", "label": "Passphrase", "type": "secret", "required": False, "default": "", "help": "Key passphrase if protected"},
        {"key": "input_path", "label": "Input path", "type": "string", "required": False, "help": "Optional; otherwise uses upstream artifact"},
        {"key": "output_path", "label": "Output path", "type": "string", "required": False, "help": "Optional decrypted output path"},
    ]

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            import pgpy

            key_path = ctx.resolve(self.config["private_key_path"])
            if not key_path.exists():
                raise FileNotFoundError(f"PGPDecrypt: private key not found: {key_path}")

            key, _ = pgpy.PGPKey.from_blob(key_path.read_text())
            passphrase = self.config.get("passphrase") or ""

            # Resolve ciphertext
            raw: bytes | None = None
            if self.config.get("input_path"):
                ip = ctx.resolve(self.config["input_path"])
                raw = ip.read_bytes()
            elif "bytes" in self.config:
                b = self.config["bytes"]
                raw = b if isinstance(b, bytes) else b.encode("utf-8")
            elif ctx.variables.get("upstream_bytes"):
                raw = ctx.variables["upstream_bytes"]
            elif ctx.variables.get("upstream_path"):
                raw = Path(ctx.variables["upstream_path"]).read_bytes()
            else:
                raise ValueError("PGPDecrypt: no encrypted input (path/bytes/upstream)")

            metrics.rows_in = 1
            msg = pgpy.PGPMessage.from_blob(raw)

            if key.is_protected and passphrase:
                with key.unlock(passphrase):
                    decrypted = key.decrypt(msg)
            elif key.is_protected:
                # Try empty passphrase
                with key.unlock(""):
                    decrypted = key.decrypt(msg)
            else:
                decrypted = key.decrypt(msg)

            plaintext = decrypted.message
            if isinstance(plaintext, str):
                out_bytes = plaintext.encode("utf-8")
                content = plaintext
            else:
                out_bytes = bytes(plaintext)
                content = out_bytes.decode("utf-8", errors="replace")

            out_path = None
            if self.config.get("output_path"):
                out_path = ctx.resolve(self.config["output_path"])
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(out_bytes)

            ctx.emit(f"PGPDecrypt: decrypted {len(raw)} → {len(out_bytes)} bytes")
            metrics.rows_out = 1

            artifacts: dict[str, Any] = {
                "bytes": out_bytes,
                "content": content,
            }
            if out_path:
                artifacts["path"] = str(out_path)

        return ComponentResult(
            rows=[{"_decrypted_size": len(out_bytes)}],
            metrics=metrics,
            artifacts=artifacts,
        )
