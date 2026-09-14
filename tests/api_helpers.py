"""Helpers shared by API / control-plane tests."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
TERMINAL = frozenset({"success", "failed", "cancelled", "timed_out"})


def boot_api(
    monkeypatch,
    *,
    work_dir: Path | None = None,
    db_path: Path | None = None,
    embedded_worker: bool = True,
    scheduler: bool = False,
):
    """Reload formulaetl_api bound to an isolated SQLite DB + work dir."""
    from scripts.seed_demo import main

    main()
    work = work_dir or ROOT
    monkeypatch.setenv("FORMULAETL_WORK_DIR", str(work))
    monkeypatch.setenv("FORMULAETL_DEMO", "1")
    monkeypatch.setenv("FORMULAETL_SCHEDULER", "1" if scheduler else "0")
    monkeypatch.setenv(
        "FORMULAETL_EMBEDDED_WORKER", "1" if embedded_worker else "0"
    )
    if db_path is not None:
        monkeypatch.setenv("FORMULAETL_DB_PATH", str(db_path))
    else:
        monkeypatch.delenv("FORMULAETL_DB_PATH", raising=False)

    import importlib
    import formulaetl_api

    importlib.reload(formulaetl_api)
    formulaetl_api.configure(
        work_dir=work,
        db_path=db_path or (work / "data" / "formulaetl-test.db"),
        demo_mode=True,
        embedded_worker=embedded_worker,
    )
    formulaetl_api._scheduler = None
    formulaetl_api._worker = None
    return formulaetl_api


def wait_run(
    client: TestClient,
    run_id: str,
    *,
    timeout_sec: float = 60.0,
    poll_sec: float = 0.05,
    formulaetl_api: Any | None = None,
) -> dict[str, Any]:
    """Poll GET /api/runs/{id} until terminal. Optionally drain embedded worker."""
    deadline = time.time() + timeout_sec
    last: dict[str, Any] = {}
    while time.time() < deadline:
        if formulaetl_api is not None and not formulaetl_api.EMBEDDED_WORKER:
            try:
                formulaetl_api.get_worker().tick_once()
            except Exception:
                pass
        r = client.get(f"/api/runs/{run_id}")
        assert r.status_code == 200, r.text
        last = r.json()
        if last.get("status") in TERMINAL:
            return last
        time.sleep(poll_sec)
    raise AssertionError(
        f"Run {run_id} did not finish within {timeout_sec}s; last={last}"
    )
