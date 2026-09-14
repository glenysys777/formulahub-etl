"""Live wedge E2E — SKIP unless RUN_LIVE_WEDGE=1 and credentials present.

Classification: LIVE_CLOUD. Never claims PROVEN without a real successful run.
CI must not set RUN_LIVE_WEDGE; default collection skips via ``-m "not live"``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.live_wedge_e2e import check_credentials, run_wedge

pytestmark = pytest.mark.live


def test_live_wedge_e2e_s3_or_sftp_to_warehouse():
    """S3|SFTP → PGP → CSV → validate → map → Postgres|Snowflake → archive.

    Skips (UNPROVEN) unless RUN_LIVE_WEDGE=1 and credentials are present.
    """
    if os.environ.get("RUN_LIVE_WEDGE") != "1":
        pytest.skip(
            "UNPROVEN / LIVE_CLOUD: set RUN_LIVE_WEDGE=1 and live credentials "
            "(see docs/design-partner/LIVE_WEDGE.md)"
        )

    report = check_credentials()
    if not report.ok:
        pytest.skip(
            "UNPROVEN / LIVE_CLOUD: missing credentials: " + ", ".join(report.missing)
        )

    # Parent conftest forces DEMO=1; live run must override.
    os.environ["FORMULAETL_DEMO"] = "0"
    result = run_wedge(work_dir=ROOT)

    assert result.get("classification") == "LIVE_CLOUD"
    assert result.get("status") != "skipped", result
    assert result.get("status") == "success", (
        f"LIVE wedge FAILED (evidence=FAILED): {result.get('error')}\n{result}"
    )
    assert result.get("evidence") == "PROVEN"
    nm = result.get("node_metrics") or {}
    assert "src" in nm or "pgp" in nm
