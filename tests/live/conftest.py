"""Live tests: do not force DEMO=1 for this package; skip by default via marker."""

from __future__ import annotations

# Intentionally minimal — root conftest still loads, but live tests override
# FORMULAETL_DEMO=0 only when RUN_LIVE_WEDGE=1 and credentials exist.
