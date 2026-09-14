"""Regression: legacy JSON migration must not hang via ensure↔migrate recursion.

Without re-entrancy guards, PipelineStore/ScheduleStore.ensure → _migrate_legacy_json
→ get/save → ensure loops forever (RecursionError is swallowed per file, then
save re-enters migrate). That blocks FastAPI startup at \"Waiting for application
startup\" so /health never responds — the common Mac/Docker \"API unreachable\" symptom
when data/pipelines/*.json still exist after the SQLite cutover.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from formulaetl_api.db import Database
from formulaetl_api.store import (
    PipelineDefinition,
    PipelineStore,
    ScheduleSpec,
    ScheduleStore,
)

# Bound well under CI patience; unfixed code hangs until killed.
_MIGRATE_TIMEOUT_SEC = 5.0


def _run_with_timeout(fn, *, timeout_sec: float = _MIGRATE_TIMEOUT_SEC) -> None:
    """Run fn in a daemon thread; fail if it does not finish (hang regression)."""
    exc: list[BaseException] = []

    def target() -> None:
        try:
            fn()
        except BaseException as e:  # noqa: BLE001 — surface to parent thread
            exc.append(e)

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout_sec)
    if t.is_alive():
        pytest.fail(
            f"operation hung for >{timeout_sec}s "
            "(likely ensure↔_migrate_legacy_json recursion)"
        )
    if exc:
        raise exc[0]


def test_pipeline_legacy_migrate_no_hang(tmp_path: Path):
    legacy = tmp_path / "pipelines"
    legacy.mkdir()
    # Multiple files: single-file cases can appear to finish via RecursionError
    # swallowing; multi-file re-enters migrate from save and spins forever.
    for i in range(5):
        (legacy / f"legacy-{i}.json").write_text(
            json.dumps(
                {
                    "id": f"legacy-{i}",
                    "name": f"Legacy {i}",
                    "nodes": [],
                    "edges": [],
                }
            ),
            encoding="utf-8",
        )

    store = PipelineStore(Database(tmp_path / "p.db"), legacy_json_root=legacy)
    _run_with_timeout(store.ensure)

    for i in range(5):
        got = store.get(f"legacy-{i}")
        assert got is not None
        assert got.name == f"Legacy {i}"

    # Normal CRUD after migrate
    store.save(
        PipelineDefinition.model_validate(
            {
                "id": "new-pipe",
                "name": "New",
                "nodes": [],
                "edges": [],
            }
        )
    )
    assert store.get("new-pipe") is not None
    assert store.delete("new-pipe") is True


def test_schedule_legacy_migrate_no_hang(tmp_path: Path):
    legacy = tmp_path / "schedules"
    legacy.mkdir()
    for i in range(5):
        (legacy / f"sched-{i}.json").write_text(
            json.dumps(
                {
                    "pipeline_id": f"pipe-{i}",
                    "enabled": True,
                    "cron": "*/5 * * * *",
                    "timezone": "UTC",
                }
            ),
            encoding="utf-8",
        )

    store = ScheduleStore(Database(tmp_path / "s.db"), legacy_json_root=legacy)
    _run_with_timeout(store.ensure)

    for i in range(5):
        got = store.get(f"pipe-{i}")
        assert got is not None
        assert got.enabled is True
        assert got.cron == "*/5 * * * *"

    store.save(
        ScheduleSpec(
            pipeline_id="pipe-new",
            enabled=False,
            cron="0 * * * *",
            timezone="UTC",
        )
    )
    assert store.get("pipe-new") is not None
    assert store.delete("pipe-new") is True


def test_api_startup_with_legacy_pipelines_loads_demos(
    monkeypatch, tmp_path: Path
):
    """Startup must finish with legacy JSON present; demos still load in DEMO mode."""
    from fastapi.testclient import TestClient

    from tests.api_helpers import ROOT, boot_api

    # Demos resolve under repo ROOT; isolate DB + legacy JSON under tmp_path.
    legacy = tmp_path / "legacy_pipelines"
    legacy.mkdir()
    for i in range(3):
        (legacy / f"old-{i}.json").write_text(
            json.dumps(
                {
                    "id": f"old-{i}",
                    "name": f"Old {i}",
                    "nodes": [],
                    "edges": [],
                }
            ),
            encoding="utf-8",
        )

    api = boot_api(
        monkeypatch,
        work_dir=ROOT,
        db_path=tmp_path / "startup.db",
        embedded_worker=False,
        scheduler=False,
    )
    # Attach legacy root after configure (stores already constructed).
    api.pipelines.legacy_json_root = legacy
    api.pipelines._legacy_migrated = False
    api.pipelines._legacy_migrating = False

    def boot_client() -> None:
        with TestClient(api.app) as client:
            r = client.get("/health")
            assert r.status_code == 200
            pipes = client.get("/api/pipelines").json()
            ids = {p["id"] for p in pipes}
            assert "old-0" in ids and "old-1" in ids and "old-2" in ids
            # DEMO mode demos loaded on startup
            assert "demo-excel-to-file" in ids
            assert "demo-core-path" in ids

    _run_with_timeout(boot_client, timeout_sec=30.0)
