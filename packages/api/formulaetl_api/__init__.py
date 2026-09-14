"""FormulaETL FastAPI application.

Phase D/E control plane:
  - POST /api/pipelines/{id}/run returns **202** with ``status=queued`` (async)
  - Durable SQLite ledger for pipelines, versions, runs, node_runs, events, schedules
  - Embedded worker thread by default; standalone ``python -m formulaetl_api.worker``
  - No global run lock — concurrent claimed jobs execute independently
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from formulaetl.models.pipeline import PipelineDefinition
from formulaetl.sdk.registry import list_components
from formulaetl_api.ai_builder import build_pipeline_from_text
from formulaetl_api.db import STATUS_QUEUED, Database
from formulaetl_api.scheduler import PipelineScheduler, ScheduleStore
from formulaetl_api.store import PipelineStore, RunStore
from formulaetl_api.worker import RunWorker

WORK_DIR = Path(os.environ.get("FORMULAETL_WORK_DIR", Path(__file__).resolve().parents[2]))
DEMO_MODE = os.environ.get("FORMULAETL_DEMO", "1") == "1"
DB_PATH = Path(
    os.environ.get("FORMULAETL_DB_PATH", str(WORK_DIR / "data" / "formulaetl.db"))
)
# Community default: embed a worker thread so ``make api`` works alone.
# Set FORMULAETL_EMBEDDED_WORKER=0 when running a separate worker process.
EMBEDDED_WORKER = os.environ.get("FORMULAETL_EMBEDDED_WORKER", "1") != "0"

app = FastAPI(
    title="FormulaETL API",
    description=(
        "Open-source visual ETL — pipeline CRUD, async run queue, durable history, "
        "AI builder, scheduler"
    ),
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

db = Database(DB_PATH)
pipelines = PipelineStore(db, legacy_json_root=WORK_DIR / "data" / "pipelines")
schedules = ScheduleStore(db, legacy_json_root=WORK_DIR / "data" / "schedules")
runs = RunStore(db)
_scheduler: PipelineScheduler | None = None
_worker: RunWorker | None = None


def configure(
    *,
    work_dir: Path | None = None,
    db_path: Path | None = None,
    demo_mode: bool | None = None,
    embedded_worker: bool | None = None,
) -> None:
    """Rebind module-level stores (tests / process boot)."""
    global WORK_DIR, DEMO_MODE, DB_PATH, EMBEDDED_WORKER
    global db, pipelines, schedules, runs, _scheduler, _worker

    if work_dir is not None:
        WORK_DIR = Path(work_dir)
    if db_path is not None:
        DB_PATH = Path(db_path)
    elif work_dir is not None and "FORMULAETL_DB_PATH" not in os.environ:
        DB_PATH = WORK_DIR / "data" / "formulaetl.db"
    if demo_mode is not None:
        DEMO_MODE = demo_mode
    if embedded_worker is not None:
        EMBEDDED_WORKER = embedded_worker

    if _worker is not None:
        _worker.stop()
        _worker = None
    if _scheduler is not None:
        _scheduler.stop()
        _scheduler = None

    db = Database(DB_PATH)
    pipelines = PipelineStore(db, legacy_json_root=WORK_DIR / "data" / "pipelines")
    schedules = ScheduleStore(db, legacy_json_root=WORK_DIR / "data" / "schedules")
    runs = RunStore(db)


class PipelineCreate(BaseModel):
    name: str
    description: str = ""
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    id: str | None = None


class ScheduleUpdate(BaseModel):
    enabled: bool = False
    cron: str = "*/5 * * * *"
    timezone: str = "UTC"


class AIBuildRequest(BaseModel):
    description: str
    name: str | None = None


class SchemaDiscoverRequest(BaseModel):
    component_type: str
    config: dict[str, Any] = Field(default_factory=dict)


class RunResponse(BaseModel):
    """Accepted async run. ``status`` is initially ``queued`` (HTTP 202)."""

    run_id: str
    status: str
    pipeline_version_id: str | None = None


def _ensure_demo_loaded(*, refresh: bool = False) -> None:
    """Load bundled demos from demos/*.json. With refresh=True, overwrite store (startup)."""
    import json

    for rel, pid in (
        ("demos/s3-pgp-snowflake/pipeline.json", "demo-s3-pgp-snowflake"),
        ("demos/api-map-transform/pipeline.json", "demo-api-map-transform"),
        ("demos/excel-to-file/pipeline.json", "demo-excel-to-file"),
        ("demos/sftp-excel-to-file/pipeline.json", "demo-sftp-excel-to-file"),
        ("demos/excel-sftp/pipeline.json", "demo-excel-sftp"),
        ("demos/db-to-file/pipeline.json", "demo-db-to-file"),
        ("demos/core-path/pipeline.json", "demo-core-path"),
        ("demos/python-row-flex/pipeline.json", "demo-python-row-flex"),
        ("demos/api-kafka-databricks/pipeline.json", "demo-api-kafka-databricks"),
        ("demos/s3-databricks/pipeline.json", "demo-s3-databricks"),
        ("demos/lookup-join-mapper/pipeline.json", "demo-lookup-join-mapper"),
    ):
        demo_path = WORK_DIR / rel
        if not demo_path.exists():
            continue
        if not refresh and pipelines.get(pid) is not None:
            continue
        data = json.loads(demo_path.read_text(encoding="utf-8"))
        data["id"] = pid
        pipelines.save(PipelineDefinition.model_validate(data))


def _enqueue_pipeline_run(pipeline_id: str, *, log_prefix: str = "Queued") -> dict[str, Any]:
    """Create a durable QUEUED run pinned to the current pipeline version."""
    p = pipelines.get(pipeline_id)
    if not p:
        raise KeyError(f"Pipeline '{pipeline_id}' not found")
    version = pipelines.get_current_version(pipeline_id)
    if version is None:
        # Ensure a version row exists
        version = pipelines.save(p)
    run_id = str(uuid.uuid4())
    runs.enqueue(
        run_id=run_id,
        pipeline_id=pipeline_id,
        pipeline_version_id=version.id,
        logs=[f"{log_prefix} run for pipeline '{p.name}' (version {version.version_num})"],
    )
    return {
        "run_id": run_id,
        "status": STATUS_QUEUED,
        "pipeline_id": pipeline_id,
        "pipeline_version_id": version.id,
    }


def _scheduled_run(pipeline_id: str) -> dict[str, Any]:
    """Scheduler callback — enqueue only (worker executes)."""
    return _enqueue_pipeline_run(pipeline_id, log_prefix="Scheduled")


def get_scheduler() -> PipelineScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = PipelineScheduler(
            schedules,
            _scheduled_run,
            poll_interval_sec=float(os.environ.get("FORMULAETL_SCHEDULER_POLL", "5")),
        )
    return _scheduler


def get_worker() -> RunWorker:
    global _worker
    if _worker is None:
        _worker = RunWorker(
            runs,
            pipelines,
            work_dir=WORK_DIR,
            demo_mode=DEMO_MODE,
            poll_interval_sec=float(os.environ.get("FORMULAETL_WORKER_POLL", "0.25")),
            max_concurrent=int(os.environ.get("FORMULAETL_WORKER_CONCURRENCY", "4")),
        )
    return _worker


@app.on_event("startup")
def startup() -> None:
    pipelines.ensure()
    schedules.ensure()
    runs.ensure()
    _ensure_demo_loaded(refresh=True)
    # Drop legacy demo id so product UI never lists Talend-named pipelines
    pipelines.delete("demo-talend-core-path")
    if os.environ.get("FORMULAETL_SCHEDULER", "1") != "0":
        get_scheduler().start()
    if EMBEDDED_WORKER:
        get_worker().start()


@app.on_event("shutdown")
def shutdown() -> None:
    global _scheduler, _worker
    if _scheduler is not None:
        _scheduler.stop()
        _scheduler = None
    if _worker is not None:
        _worker.stop()
        _worker = None


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "demo_mode": DEMO_MODE,
        "version": "0.2.0",
        "work_dir": str(WORK_DIR),
        "db_path": str(DB_PATH),
        "scheduler": os.environ.get("FORMULAETL_SCHEDULER", "1") != "0",
        "embedded_worker": EMBEDDED_WORKER,
        "queue_depth": runs.queue_depth(),
        # Honesty labels for operators
        "run_store": "sqlite",
        "data_path": "in_process_batches_and_artifact_handles",
        "auth": "none",
        "readiness_level": "ALPHA",
    }


@app.get("/api/components")
def api_components() -> list[dict[str, Any]]:
    return list_components()


@app.post("/api/schema/discover")
def schema_discover(body: SchemaDiscoverRequest) -> dict[str, Any]:
    """Infer columns + types from a source connection/sample (Talend-like schema)."""
    from formulaetl.schema.discover import discover

    try:
        return discover(
            body.component_type,
            body.config,
            work_dir=WORK_DIR,
            demo_mode=DEMO_MODE,
        )
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"Schema discovery failed: {exc}") from exc


@app.get("/api/pipelines")
def list_pipelines() -> list[dict[str, Any]]:
    _ensure_demo_loaded()
    return [p.model_dump() for p in pipelines.list()]


@app.post("/api/pipelines", status_code=201)
def create_pipeline(body: PipelineCreate) -> dict[str, Any]:
    pid = body.id or str(uuid.uuid4())
    pipeline = PipelineDefinition(
        id=pid,
        name=body.name,
        description=body.description,
        nodes=body.nodes,
        edges=body.edges,
        metadata=body.metadata,
    )
    version = pipelines.save(pipeline)
    out = pipeline.model_dump()
    out["pipeline_version_id"] = version.id
    out["version"] = str(version.version_num)
    return out


@app.get("/api/pipelines/{pipeline_id}")
def get_pipeline(pipeline_id: str) -> dict[str, Any]:
    _ensure_demo_loaded()
    p = pipelines.get(pipeline_id)
    if not p:
        raise HTTPException(404, f"Pipeline '{pipeline_id}' not found")
    out = p.model_dump()
    ver = pipelines.get_current_version(pipeline_id)
    if ver:
        out["pipeline_version_id"] = ver.id
        out["content_hash"] = ver.content_hash
    return out


@app.put("/api/pipelines/{pipeline_id}")
def update_pipeline(pipeline_id: str, body: PipelineCreate) -> dict[str, Any]:
    pipeline = PipelineDefinition(
        id=pipeline_id,
        name=body.name,
        description=body.description,
        nodes=body.nodes,
        edges=body.edges,
        metadata=body.metadata,
    )
    version = pipelines.save(pipeline)
    out = pipeline.model_dump()
    out["pipeline_version_id"] = version.id
    out["version"] = str(version.version_num)
    return out


@app.delete("/api/pipelines/{pipeline_id}")
def delete_pipeline(pipeline_id: str) -> dict[str, str]:
    if not pipelines.delete(pipeline_id):
        raise HTTPException(404, f"Pipeline '{pipeline_id}' not found")
    return {"status": "deleted", "id": pipeline_id}


@app.get("/api/pipelines/{pipeline_id}/versions")
def list_pipeline_versions(pipeline_id: str) -> list[dict[str, Any]]:
    _ensure_demo_loaded()
    if pipelines.get(pipeline_id) is None and not pipelines.list_versions(pipeline_id):
        raise HTTPException(404, f"Pipeline '{pipeline_id}' not found")
    return [
        {
            "id": v.id,
            "pipeline_id": v.pipeline_id,
            "version_num": v.version_num,
            "content_hash": v.content_hash,
            "created_at": v.created_at,
        }
        for v in pipelines.list_versions(pipeline_id)
    ]


@app.get("/api/pipelines/{pipeline_id}/versions/{version_id}")
def get_pipeline_version(pipeline_id: str, version_id: str) -> dict[str, Any]:
    v = pipelines.get_version(version_id)
    if v is None or v.pipeline_id != pipeline_id:
        raise HTTPException(404, f"Version '{version_id}' not found")
    return v.to_dict()


@app.post("/api/pipelines/{pipeline_id}/run", response_model=RunResponse, status_code=202)
def run_pipeline(pipeline_id: str, response: Response) -> RunResponse:
    """Enqueue a run. Returns quickly with 202 + ``queued``; worker executes async.

    Backward-compatible body fields: ``run_id``, ``status``. Added:
    ``pipeline_version_id`` (immutable snapshot pinned for this run).
    """
    p = pipelines.get(pipeline_id)
    if not p:
        _ensure_demo_loaded()
        p = pipelines.get(pipeline_id)
    if not p:
        raise HTTPException(404, f"Pipeline '{pipeline_id}' not found")

    # Restore demo encrypted object if a previous archive step moved it
    if DEMO_MODE:
        enc = WORK_DIR / "data" / "s3" / "demo" / "orders_encrypted.csv.pgp"
        if not enc.exists():
            try:
                import sys

                sys.path.insert(0, str(WORK_DIR))
                from scripts.seed_demo import main as seed_main

                seed_main()
            except Exception as exc:
                raise HTTPException(500, f"Failed to restore demo fixtures: {exc}") from exc

    try:
        accepted = _enqueue_pipeline_run(pipeline_id, log_prefix="Queued")
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc

    response.status_code = 202
    return RunResponse(
        run_id=accepted["run_id"],
        status=accepted["status"],
        pipeline_version_id=accepted["pipeline_version_id"],
    )


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    r = runs.get(run_id)
    if not r:
        raise HTTPException(404, f"Run '{run_id}' not found")
    out = r.to_dict(include_detail=True)
    out["node_runs"] = [n.to_dict() for n in runs.list_node_runs(run_id)]
    out["events"] = [e.to_dict() for e in runs.list_events(run_id)]
    return out


@app.post("/api/ai/build")
def ai_build(body: AIBuildRequest) -> dict[str, Any]:
    pipeline = build_pipeline_from_text(body.description, name=body.name)
    version = pipelines.save(pipeline)
    out = pipeline.model_dump()
    out["pipeline_version_id"] = version.id
    return out


@app.get("/api/runs")
def list_runs() -> list[dict[str, Any]]:
    return [r.to_dict(include_detail=False) for r in runs.list()]


@app.get("/api/schedules")
def list_schedules() -> list[dict[str, Any]]:
    return [s.to_dict() for s in schedules.list()]


@app.get("/api/pipelines/{pipeline_id}/schedule")
def get_pipeline_schedule(pipeline_id: str) -> dict[str, Any]:
    p = pipelines.get(pipeline_id)
    if not p:
        _ensure_demo_loaded()
        p = pipelines.get(pipeline_id)
    if not p:
        raise HTTPException(404, f"Pipeline '{pipeline_id}' not found")
    spec = schedules.get(pipeline_id)
    if not spec:
        return {
            "pipeline_id": pipeline_id,
            "enabled": False,
            "cron": "*/5 * * * *",
            "timezone": "UTC",
            "next_run_at": None,
            "last_run_at": None,
            "last_run_id": None,
            "last_status": None,
        }
    return spec.to_dict()


@app.put("/api/pipelines/{pipeline_id}/schedule")
def put_pipeline_schedule(pipeline_id: str, body: ScheduleUpdate) -> dict[str, Any]:
    p = pipelines.get(pipeline_id)
    if not p:
        _ensure_demo_loaded()
        p = pipelines.get(pipeline_id)
    if not p:
        raise HTTPException(404, f"Pipeline '{pipeline_id}' not found")
    try:
        spec = get_scheduler().upsert(
            pipeline_id,
            enabled=body.enabled,
            cron=body.cron,
            timezone=body.timezone or "UTC",
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return spec.to_dict()


@app.post("/api/scheduler/tick")
def scheduler_tick() -> dict[str, Any]:
    """Fire due schedules once (tests / manual). Community poller also calls this."""
    fired = get_scheduler().tick()
    return {"fired": fired, "count": len(fired)}


@app.post("/api/worker/tick")
def worker_tick() -> dict[str, Any]:
    """Process one queued job synchronously (tests / manual drain)."""
    did = get_worker().tick_once()
    return {"worked": did, "queue_depth": runs.queue_depth()}
