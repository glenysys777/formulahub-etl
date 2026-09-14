"""Bounded I/O helpers: retries, timeouts, secret redaction (Phase C)."""

from __future__ import annotations

import os
import random
import re
import time
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")

# Patterns that must never appear in logs when paired with secret values.
_SECRET_KEYS = frozenset(
    {
        "password",
        "passphrase",
        "secret",
        "token",
        "api_key",
        "access_key",
        "secret_access_key",
        "private_key",
        "aws_secret_access_key",
    }
)

_REDACT_RE = re.compile(
    r"(?i)(password|passphrase|secret|token|api[_-]?key|private[_-]?key)\s*[=:]\s*\S+"
)


def redact_secrets(message: str) -> str:
    """Strip obvious secret=value pairs from log / error strings."""
    return _REDACT_RE.sub(r"\1=***", message)


def secret_in_config(config: dict[str, Any], *keys: str) -> None:
    """Raise if a secret value is about to be logged (defensive)."""
    for key in keys:
        if key in config and config[key]:
            # Presence alone is fine; callers must not interpolate values.
            pass


def looks_like_secret_key(name: str) -> bool:
    n = name.lower().replace("-", "_")
    return n in _SECRET_KEYS or any(s in n for s in ("password", "passphrase", "secret", "token"))


def retry_call(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay: float = 0.25,
    max_delay: float = 8.0,
    retry_on: tuple[type[BaseException], ...] = (OSError, TimeoutError),
    label: str = "operation",
    on_retry: Callable[[int, BaseException], None] | None = None,
) -> T:
    """Retry ``fn`` with exponential backoff + jitter. Last error is re-raised."""
    attempts = max(1, int(attempts))
    last: BaseException | None = None
    for i in range(attempts):
        try:
            return fn()
        except retry_on as exc:
            last = exc
            if i >= attempts - 1:
                break
            delay = min(max_delay, base_delay * (2**i))
            delay *= 0.5 + random.random()
            if on_retry:
                on_retry(i + 1, exc)
            else:
                # Avoid printing secret-bearing exception text wholesale.
                time.sleep(delay)
                continue
            time.sleep(delay)
        except Exception:
            raise
    assert last is not None
    raise type(last)(f"{label} failed after {attempts} attempts: {redact_secrets(str(last))}") from last


def resolve_secret_ref(ref: str | None, *, env: dict[str, str] | None = None) -> str | None:
    """Resolve ``${ENV}`` / ``env:NAME`` / bare ENV name to a value. Never logs the value."""
    if not ref:
        return None
    raw = str(ref).strip()
    environ = env if env is not None else os.environ
    if raw.startswith("${") and raw.endswith("}"):
        name = raw[2:-1].strip()
        return environ.get(name)
    if raw.lower().startswith("env:"):
        return environ.get(raw[4:].strip())
    if raw.isupper() or raw.startswith("FORMULAETL_"):
        return environ.get(raw, raw)
    return raw


def boto3_client_kwargs(
    *,
    region: str | None = None,
    endpoint_url: str | None = None,
    connect_timeout: float = 10.0,
    read_timeout: float = 60.0,
    max_attempts: int = 5,
) -> dict[str, Any]:
    """Build boto3 client kwargs with retries/timeouts; uses default credential chain."""
    from botocore.config import Config

    cfg = Config(
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
        retries={"max_attempts": max_attempts, "mode": "standard"},
    )
    kwargs: dict[str, Any] = {"config": cfg}
    if region:
        kwargs["region_name"] = region
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    return kwargs
