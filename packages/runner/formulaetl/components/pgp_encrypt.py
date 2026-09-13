"""PGP Encrypt — encrypt bytes/file with a public key (pairs with pgp_decrypt)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.registry import register


@register
class PGPEncrypt(BaseComponent):
    component_type = "pgp_encrypt"
    display_name = "PGP Encrypt"
    category = "security"
    config_schema = {
        "type": "object",
        "required": ["public_key_path"],
        "properties": {
            "public_key_path": {"type": "string"},
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
            "required": True,
            "default": "fixtures/keys/demo_public.asc",
            "help": "Path to PGP public key (.asc)",
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

            key_path = ctx.resolve(self.config["public_key_path"])
            if not key_path.exists():
                raise FileNotFoundError(f"PGPEncrypt: public key not found: {key_path}")

            key, _ = pgpy.PGPKey.from_blob(key_path.read_text())
            armor = bool(self.config.get("armor", True))

            raw: bytes | None = None
            if self.config.get("input_path"):
                ip = ctx.resolve(self.config["input_path"])
                raw = ip.read_bytes()
            elif "bytes" in self.config:
                b = self.config["bytes"]
                raw = b if isinstance(b, bytes) else str(b).encode("utf-8")
            elif "content" in self.config:
                raw = str(self.config["content"]).encode("utf-8")
            elif ctx.variables.get("upstream_bytes"):
                raw = ctx.variables["upstream_bytes"]
            elif ctx.variables.get("upstream_content"):
                raw = str(ctx.variables["upstream_content"]).encode("utf-8")
            elif ctx.variables.get("upstream_path"):
                raw = Path(ctx.variables["upstream_path"]).read_bytes()
            elif rows and len(rows) == 1 and rows[0].get("content") is not None:
                raw = str(rows[0]["content"]).encode("utf-8")
            else:
                raise ValueError("PGPEncrypt: no plaintext input (path/bytes/content/upstream)")

            metrics.rows_in = 1
            msg = pgpy.PGPMessage.new(raw, file=True)
            # Prefer key's advertised algorithms when present
            cipher = key.encrypt(msg)
            if armor:
                out_bytes = str(cipher).encode("utf-8")
                content = str(cipher)
            else:
                out_bytes = bytes(cipher)
                content = out_bytes.decode("utf-8", errors="replace")

            out_path = None
            if self.config.get("output_path"):
                out_path = ctx.resolve(self.config["output_path"])
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(out_bytes)

            ctx.emit(f"PGPEncrypt: encrypted {len(raw)} → {len(out_bytes)} bytes (armor={armor})")
            metrics.rows_out = 1

            artifacts: dict[str, Any] = {
                "bytes": out_bytes,
                "content": content,
            }
            if out_path:
                artifacts["path"] = str(out_path)

        return ComponentResult(
            rows=[{"_encrypted_size": len(out_bytes)}],
            metrics=metrics,
            artifacts=artifacts,
        )
