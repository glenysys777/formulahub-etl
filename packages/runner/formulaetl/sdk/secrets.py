"""SecretProvider — Community/local secret refs (env + encrypted local store).

Pipeline JSON and connection records hold **references only** (``env:NAME``,
``${NAME}``, ``secret:<id>``). Values are resolved at runtime and must never be
logged or sent to the AI builder.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import threading
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from formulaetl.sdk.io_util import looks_like_secret_key, redact_secrets

# Well-known insecure key for DEMO=1 when FORMULAETL_SECRETS_KEY is unset.
# Documented as demo-only — not for customer credentials.
_DEMO_FERNET_MATERIAL = b"formulaetl-demo-secrets-key-v1!!"


@runtime_checkable
class SecretProvider(Protocol):
    def get(self, ref: str) -> str | None:
        """Resolve a secret reference to a plaintext value. Never log the result."""
        ...

    def put(self, name: str, value: str) -> str:
        """Store a secret; return a durable ref (e.g. ``secret:<id>``)."""
        ...

    def delete(self, ref: str) -> bool:
        ...


_REF_ENV = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")
_REF_ENV_PREFIX = re.compile(r"^env:([A-Za-z_][A-Za-z0-9_]*)$", re.I)
_REF_SECRET = re.compile(r"^secret:([A-Za-z0-9_-]+)$", re.I)


def is_secret_ref(value: Any) -> bool:
    """True if value looks like an env/secret reference (not a raw password)."""
    if not isinstance(value, str):
        return False
    raw = value.strip()
    if not raw:
        return False
    if _REF_ENV.match(raw) or _REF_ENV_PREFIX.match(raw) or _REF_SECRET.match(raw):
        return True
    if raw.isupper() or raw.startswith("FORMULAETL_"):
        return True
    return False


def is_masked(value: Any) -> bool:
    return value in ("***", "********", "[redacted]", "[REDACTED]")


def mask_value(value: Any = None) -> str:
    return "***"


def _fernet_from_material(material: bytes):
    from cryptography.fernet import Fernet

    digest = hashlib.sha256(material).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def load_fernet(*, work_dir: Path | None = None, demo_mode: bool = True):
    """Build a Fernet cipher for the local encrypted store.

    Precedence:
      1. ``FORMULAETL_SECRETS_KEY`` (url-safe base64 Fernet key, or any passphrase)
      2. ``data/.formulaetl_secrets_key`` under work_dir (created if missing when not demo)
      3. DEMO well-known material when ``demo_mode`` / ``FORMULAETL_DEMO=1``
    """
    from cryptography.fernet import Fernet

    env_key = os.environ.get("FORMULAETL_SECRETS_KEY", "").strip()
    if env_key:
        try:
            # Accept a real Fernet key
            return Fernet(env_key.encode("utf-8") if isinstance(env_key, str) else env_key)
        except Exception:
            return _fernet_from_material(env_key.encode("utf-8"))

    demo_env = demo_mode or os.environ.get("FORMULAETL_DEMO", "1") == "1"
    if work_dir is not None:
        key_path = Path(work_dir) / "data" / ".formulaetl_secrets_key"
        if key_path.exists():
            return _fernet_from_material(key_path.read_bytes().strip())
        if not demo_env:
            key_path.parent.mkdir(parents=True, exist_ok=True)
            material = os.urandom(32)
            key_path.write_bytes(material)
            try:
                key_path.chmod(0o600)
            except OSError:
                pass
            return _fernet_from_material(material)

    if demo_env:
        return _fernet_from_material(_DEMO_FERNET_MATERIAL)

    # Last resort — ephemeral (process-local); values won't survive restart.
    return _fernet_from_material(os.urandom(32))


class EnvSecretProvider:
    """Resolve ``env:NAME`` / ``${NAME}`` / bare ``FORMULAETL_*`` from the environment."""

    def __init__(self, environ: dict[str, str] | None = None):
        self._env = environ if environ is not None else os.environ

    def get(self, ref: str) -> str | None:
        if not ref:
            return None
        raw = str(ref).strip()
        m = _REF_ENV.match(raw)
        if m:
            return self._env.get(m.group(1))
        m = _REF_ENV_PREFIX.match(raw)
        if m:
            return self._env.get(m.group(1))
        if raw.isupper() or raw.startswith("FORMULAETL_"):
            return self._env.get(raw)
        return None

    def put(self, name: str, value: str) -> str:
        raise RuntimeError(
            "EnvSecretProvider is read-only; set the environment variable or use LocalEncryptedSecretStore"
        )

    def delete(self, ref: str) -> bool:
        return False


class MemorySecretStore:
    """In-memory store for unit tests (not durable)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._data: dict[str, str] = {}
        self._names: dict[str, str] = {}

    def get(self, ref: str) -> str | None:
        raw = str(ref).strip()
        m = _REF_SECRET.match(raw)
        if not m:
            return None
        with self._lock:
            return self._data.get(m.group(1))

    def put(self, name: str, value: str) -> str:
        import uuid

        sid = uuid.uuid4().hex
        with self._lock:
            self._data[sid] = value
            self._names[sid] = name
        return f"secret:{sid}"

    def delete(self, ref: str) -> bool:
        m = _REF_SECRET.match(str(ref).strip())
        if not m:
            return False
        with self._lock:
            self._data.pop(m.group(1), None)
            self._names.pop(m.group(1), None)
        return True


class CompositeSecretProvider:
    """Try env refs first, then encrypted/local store for ``secret:`` ids."""

    def __init__(self, *providers: SecretProvider):
        self.providers = list(providers)

    def get(self, ref: str) -> str | None:
        if not ref:
            return None
        raw = str(ref).strip()
        # Prefer env resolution for env-shaped refs
        for p in self.providers:
            if isinstance(p, EnvSecretProvider):
                val = p.get(raw)
                if val is not None:
                    return val
        for p in self.providers:
            if isinstance(p, EnvSecretProvider):
                continue
            val = p.get(raw)
            if val is not None:
                return val
        # Literal passthrough only when it is clearly not a ref
        if is_secret_ref(raw):
            return None
        return raw

    def put(self, name: str, value: str) -> str:
        for p in self.providers:
            if not isinstance(p, EnvSecretProvider):
                return p.put(name, value)
        raise RuntimeError("No writable SecretProvider configured")

    def delete(self, ref: str) -> bool:
        ok = False
        for p in self.providers:
            try:
                ok = p.delete(ref) or ok
            except Exception:
                continue
        return ok


def resolve_secret_value(
    ref_or_value: str | None,
    provider: SecretProvider | None = None,
    *,
    env: dict[str, str] | None = None,
) -> str | None:
    """Resolve a secret ref or return a literal. Compatible with legacy ``resolve_secret_ref``."""
    if ref_or_value is None:
        return None
    raw = str(ref_or_value).strip()
    if not raw or is_masked(raw):
        return None
    if provider is not None:
        if is_secret_ref(raw):
            return provider.get(raw)
        # Writable store may hold secret: ids; literals pass through
        got = provider.get(raw)
        if got is not None and is_secret_ref(raw):
            return got
        return raw
    # Fallback: env-only (legacy)
    from formulaetl.sdk.io_util import resolve_secret_ref

    return resolve_secret_ref(raw, env=env)


def secret_keys_for_component(component_type: str | None = None) -> frozenset[str]:
    """Known secret config keys (plus registry lookup when available)."""
    base = {
        "password",
        "passphrase",
        "token",
        "api_key",
        "auth_bearer",
        "secret",
        "access_key",
        "secret_access_key",
        "aws_secret_access_key",
        "private_key",
    }
    if component_type:
        try:
            from formulaetl.sdk.registry import get_component

            cls = get_component(component_type)
            for p in cls.get_parameters():
                key = p.get("key")
                if not key:
                    continue
                if p.get("type") == "secret" or looks_like_secret_key(key):
                    # python_row.code is typed secret for UI masking but is not a credential
                    if component_type == "python_row" and key == "code":
                        continue
                    base.add(key)
        except Exception:
            pass
    return frozenset(base)


def mask_config(
    config: dict[str, Any],
    *,
    component_type: str | None = None,
    keep_refs: bool = True,
) -> dict[str, Any]:
    """Return a copy of config with secret values masked for API responses."""
    keys = secret_keys_for_component(component_type)
    out: dict[str, Any] = {}
    for k, v in config.items():
        if k in keys or looks_like_secret_key(k):
            if component_type == "python_row" and k == "code":
                out[k] = v
            elif keep_refs and is_secret_ref(v):
                out[k] = v  # refs are safe to return
            elif v in (None, "", False):
                out[k] = v
            else:
                out[k] = mask_value()
        else:
            out[k] = v
    return out


def strip_secrets_for_ai(config: dict[str, Any], *, component_type: str | None = None) -> dict[str, Any]:
    """Remove secret material before any AI / LLM payload."""
    keys = secret_keys_for_component(component_type)
    out: dict[str, Any] = {}
    for k, v in config.items():
        if k in keys or looks_like_secret_key(k):
            if is_secret_ref(v):
                out[k] = v
            elif v:
                out[k] = "[omitted]"
            else:
                out[k] = ""
        else:
            out[k] = v
    return out


def safe_log(message: str) -> str:
    return redact_secrets(message)
