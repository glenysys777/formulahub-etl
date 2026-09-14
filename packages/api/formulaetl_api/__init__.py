"""FormulaETL FastAPI application."""

from __future__ import annotations

import os
import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from formulaetl.engine.runner import PipelineRunner, RunResult
from formulaetl.models.pipeline import PipelineDefinition
from formulaetl.sdk.registry import list_components
from formulaetl_api.ai_builder import build_pipeline_from_text
from formulaetl_api.scheduler import PipelineScheduler, ScheduleStore
from formulaetl_api.store import PipelineStore, RunStore

WORK_DIR = Path(os.environ.get("FORMULAETL_WORK_DIR", Path(__file__).resolve().parents[2]))
DEMO_MODE = os.environ.get("FORMULAETL_DEMO", "1") == "1"

app = FastAPI(
    title="FormulaETL API",
    description="Open-source visual ETL — pipeline CRUD, run, logs, AI builder, scheduler",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pipelines = PipelineStore(WORK_DIR / "data" / "pipelines")
schedules = ScheduleStore(WORK_DIR / "data" / "schedules")
runs = RunStore()
_runner_lock = threading.Lock()
_scheduler: PipelineScheduler | None = None


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
    run_id: str
    status: str


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


def _scheduled_run(pipeline_id: str) -> dict[str, Any]:
    """Callback used by the Community scheduler poll loop."""
    p = pipelines.get(pipeline_id)
    if not p:
        raise KeyError(f"Pipeline '{pipeline_id}' not found for schedule")
    run_id = str(uuid.uuid4())
    pending = RunResult(
        run_id=run_id,
        pipeline_id=pipeline_id,
        status="running",
        logs=[f"Scheduled run for pipeline '{p.name}'"],
    )
    runs.put(pending)
    with _runner_lock:
        _execute_run(run_id, p)
    final = runs.get(run_id)
    return {
        "run_id": run_id,
        "status": final.status if final else "unknown",
        "pipeline_id": pipeline_id,
    }


def get_scheduler() -> PipelineScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = PipelineScheduler(
            schedules,
            _scheduled_run,
            poll_interval_sec=float(os.environ.get("FORMULAETL_SCHEDULER_POLL", "5")),
        )
    return _scheduler


@app.on_event("startup")
def startup() -> None:
    pipelines.ensure()
    schedules.ensure()
    _ensure_demo_loaded(refresh=True)
    # Drop legacy demo id so product UI never lists Talend-named pipelines
    pipelines.delete("demo-talend-core-path")
    # Community self-hosted scheduler (in-process poll). HA / multi-node is Enterprise later.
    if os.environ.get("FORMULAETL_SCHEDULER", "1") != "0":
        get_scheduler().start()


@app.on_event("shutdown")
def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.stop()
        _scheduler = None


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "demo_mode": DEMO_MODE,
        "version": "0.1.0",
        "work_dir": str(WORK_DIR),
        "scheduler": os.environ.get("FORMULAETL_SCHEDULER", "1") != "0",
        # Honesty labels for operators (not a capability claim)
        "run_store": "memory",
        "data_path": "in_process_list_dict_and_bytes",
        "auth": "none",
        "readiness_level": "DEMO",
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
    pipelines.save(pipeline)
    return pipeline.model_dump()


@app.get("/api/pipelines/{pipeline_id}")
def get_pipeline(pipeline_id: str) -> dict[str, Any]:
    _ensure_demo_loaded()
    p = pipelines.get(pipeline_id)
    if not p:
        raise HTTPException(404, f"Pipeline '{pipeline_id}' not found")
    return p.model_dump()


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
    pipelines.save(pipeline)
    return pipeline.model_dump()


@app.delete("/api/pipelines/{pipeline_id}")
def delete_pipeline(pipeline_id: str) -> dict[str, str]:
    if not pipelines.delete(pipeline_id):
        raise HTTPException(404, f"Pipeline '{pipeline_id}' not found")
    return {"status": "deleted", "id": pipeline_id}


def _execute_run(run_id: str, pipeline: PipelineDefinition) -> None:
    runner = PipelineRunner(work_dir=WORK_DIR, demo_mode=DEMO_MODE)
    result = runner.run(pipeline, run_id=run_id)
    runs.update(result)


@app.post("/api/pipelines/{pipeline_id}/run", response_model=RunResponse)
def run_pipeline(pipeline_id: str) -> RunResponse:
    p = pipelines.get(pipeline_id)
    if not p:
        # try reload demo
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

    run_id = str(uuid.uuid4())
    pending = RunResult(
        run_id=run_id,
        pipeline_id=pipeline_id,
        status="running",
        logs=[f"Queued run for pipeline '{p.name}'"],
    )
    runs.put(pending)

    # For demo/MVP reliability: run synchronously under lock so poll gets final status.
    # Still returns run_id first-style via the stored result.
    with _runner_lock:
        _execute_run(run_id, p)

    final = runs.get(run_id)
    return RunResponse(run_id=run_id, status=final.status if final else "unknown")


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    r = runs.get(run_id)
    if not r:
        raise HTTPException(404, f"Run '{run_id}' not found")
    return {
        "run_id": r.run_id,
        "pipeline_id": r.pipeline_id,
        "status": r.status,
        "metrics": r.metrics,
        "node_metrics": r.node_metrics,
        "logs": r.logs,
        "error": r.error,
        "outputs": r.outputs,
        "duration_ms": r.duration_ms,
    }


@app.post("/api/ai/build")
def ai_build(body: AIBuildRequest) -> dict[str, Any]:
    pipeline = build_pipeline_from_text(body.description, name=body.name)
    pipelines.save(pipeline)
    return pipeline.model_dump()


@app.get("/api/runs")
def list_runs() -> list[dict[str, Any]]:
    return [
        {
            "run_id": r.run_id,
            "pipeline_id": r.pipeline_id,
            "status": r.status,
            "metrics": r.metrics,
            "duration_ms": r.duration_ms,
        }
        for r in runs.list()
    ]


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
