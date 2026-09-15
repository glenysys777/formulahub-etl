"""FormulaETL FastAPI application.

Phase D/E control plane:
  - POST /api/pipelines/{id}/run returns **202** with ``status=queued`` (async)
  - Durable SQLite ledger for pipelines, versions, runs, node_runs, events, schedules
  - Embedded worker thread by default; standalone ``python -m formulaetl_api.worker``
  - No global run lock — concurrent claimed jobs execute independently

Phase F:
  - Reusable Connections + SecretProvider (env + encrypted local store)
  - Optional ``FORMULAETL_API_KEY`` gate (Community open when unset)
  - Pipeline/connection GET responses mask secret material

Phase G:
  - POST /api/pipelines/{id}/validate — structured preflight (graph, params, refs)
  - GET /api/runs/{id} includes ``summary`` + clear node_runs / events
  - Pipeline mirror JSON under ``{work_dir}/pipelines/``; export JSON/zip; import
"""

from __future__ import annotations

import io
import json
import os
import re
import uuid
import zipfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from formulaetl.models.pipeline import PipelineDefinition
from formulaetl.sdk.connections import CONNECTION_KINDS
from formulaetl.sdk.registry import list_components
from formulaetl.sdk.secrets import (
    CompositeSecretProvider,
    EnvSecretProvider,
    mask_config,
    strip_secrets_for_ai,
)
from formulaetl_api.ai_builder import build_pipeline_from_text
from formulaetl_api.db import STATUS_QUEUED, Database
from formulaetl_api.scheduler import PipelineScheduler, ScheduleStore
from formulaetl_api.store import ConnectionStore, PipelineStore, RunStore
from formulaetl_api.validate import run_summary_from_detail, validate_pipeline_definition
from formulaetl_api.worker import RunWorker
from formulaetl_api.workspace import (
    DEFAULT_MY_PIPELINES,
    apply_demo_workspace_folder,
    folder_from_metadata,
    load_workspace,
    resolve_pipeline_folder,
    save_workspace,
    stamp_workspace_folder,
    sync_workspace_from_pipelines,
)

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
        "connections + secret refs, AI builder, scheduler"
    ),
    version="0.3.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Optional gate: when FORMULAETL_API_KEY is set, require matching header.

    Accepts ``X-API-Key: <key>`` or ``Authorization: Bearer <key>``.
    ``/health`` stays open for probes. When the env var is unset, Community stays open.
    """

    async def dispatch(self, request: Request, call_next):
        expected = os.environ.get("FORMULAETL_API_KEY", "").strip()
        if not expected:
            return await call_next(request)
        path = request.url.path
        if path == "/health" or path == "/docs" or path == "/openapi.json" or path == "/redoc":
            return await call_next(request)
        provided = request.headers.get("x-api-key") or ""
        if not provided:
            auth = request.headers.get("authorization") or ""
            if auth.lower().startswith("bearer "):
                provided = auth[7:].strip()
        if provided != expected:
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
        return await call_next(request)


app.add_middleware(ApiKeyMiddleware)

db = Database(DB_PATH)
pipelines = PipelineStore(db, legacy_json_root=WORK_DIR / "data" / "pipelines")
schedules = ScheduleStore(db, legacy_json_root=WORK_DIR / "data" / "schedules")
runs = RunStore(db)
connections = ConnectionStore(db, work_dir=WORK_DIR, demo_mode=DEMO_MODE)
_scheduler: PipelineScheduler | None = None
_worker: RunWorker | None = None


def _auth_mode() -> str:
    return "api_key" if os.environ.get("FORMULAETL_API_KEY", "").strip() else "none"


def _secret_provider() -> CompositeSecretProvider:
    return CompositeSecretProvider(EnvSecretProvider(), connections.secret_store)


def configure(
    *,
    work_dir: Path | None = None,
    db_path: Path | None = None,
    demo_mode: bool | None = None,
    embedded_worker: bool | None = None,
) -> None:
    """Rebind module-level stores (tests / process boot)."""
    global WORK_DIR, DEMO_MODE, DB_PATH, EMBEDDED_WORKER
    global db, pipelines, schedules, runs, connections, _scheduler, _worker

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
    connections = ConnectionStore(db, work_dir=WORK_DIR, demo_mode=DEMO_MODE)


def _mask_pipeline_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Mask secret-typed node config values for API responses."""
    out = dict(data)
    nodes = []
    for node in out.get("nodes") or []:
        n = dict(node)
        cfg = n.get("config") or {}
        n["config"] = mask_config(dict(cfg), component_type=n.get("type"))
        nodes.append(n)
    out["nodes"] = nodes
    return out


def _pipelines_mirror_dir() -> Path:
    """Community project files: ``{work_dir}/pipelines/{id}.json`` next to the workspace."""
    d = WORK_DIR / "pipelines"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_export_stem(name: str, pipeline_id: str) -> str:
    stem = re.sub(r"[^\w.\-]+", "-", (name or "").strip(), flags=re.UNICODE).strip("-")
    if not stem:
        stem = pipeline_id
    return stem[:80]


def _mirror_pipeline_to_disk(pipeline: PipelineDefinition) -> str:
    """Write pretty JSON mirror under work_dir/pipelines/ (SQLite remains source of truth)."""
    path = _pipelines_mirror_dir() / f"{pipeline.id}.json"
    dump = pipeline.model_dump(mode="json")
    path.write_text(
        json.dumps(dump, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    return str(path.resolve())


def _remove_pipeline_mirror(pipeline_id: str) -> None:
    path = WORK_DIR / "pipelines" / f"{pipeline_id}.json"
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        pass


def _export_readme(pipeline: PipelineDefinition, json_name: str) -> str:
    return (
        f"# {pipeline.name}\n\n"
        "Exported from FormulaHub ETL Studio.\n\n"
        "## Contents\n\n"
        f"- `{json_name}` — pipeline graph (nodes, edges, config)\n\n"
        "## Run elsewhere\n\n"
        "1. Place this folder under a FormulaHub ETL workspace (`FORMULAETL_WORK_DIR`).\n"
        "2. Import via Studio **or** `POST /api/pipelines/import` with the JSON body.\n"
        "3. Or copy the JSON into `{work_dir}/pipelines/` and open the pipeline by id.\n\n"
        "Secrets are not embedded — reconnect Connections / env secrets on the target machine.\n\n"
        "See `docs/studio/PROJECTS_AND_GIT.md` for Save → disk → Git workflow.\n"
    )


class PipelineCreate(BaseModel):
    name: str
    description: str = ""
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    id: str | None = None


class PipelineImport(BaseModel):
    """Full pipeline JSON (export / mirror file) for import."""

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
    connection_id: str | None = None


class RunResponse(BaseModel):
    """Accepted async run. ``status`` is initially ``queued`` (HTTP 202)."""

    run_id: str
    status: str
    pipeline_version_id: str | None = None


class ConnectionCreate(BaseModel):
    name: str
    kind: str
    description: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    secrets: dict[str, Any] = Field(default_factory=dict)
    id: str | None = None


class ConnectionUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    config: dict[str, Any] | None = None
    secrets: dict[str, Any] | None = None


class PipelineValidateBody(BaseModel):
    """Optional unsaved canvas graph. When omitted, validates the stored pipeline."""

    name: str | None = None
    description: str | None = None
    nodes: list[dict[str, Any]] | None = None
    edges: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] | None = None


class WorkspaceUpdate(BaseModel):
    folders: list[str] = Field(default_factory=list)
    pipelineFolders: dict[str, str] = Field(default_factory=dict)


class WorkspaceMove(BaseModel):
    pipeline_id: str
    folder: str


def _secret_exists(ref: str) -> bool:
    """True if a secret ref resolves — value is discarded (never returned)."""
    try:
        val = _secret_provider().get(ref)
    except Exception:
        return False
    return val is not None and str(val) != ""


def _index_pipeline_folder(pipeline: PipelineDefinition) -> None:
    """Keep data/workspace.json in sync with metadata.workspace_folder."""
    folder = folder_from_metadata(pipeline.metadata) or DEFAULT_MY_PIPELINES
    ws = load_workspace(WORK_DIR)
    pf = dict(ws.get("pipelineFolders") or {})
    pf[pipeline.id] = folder
    folders = list(ws.get("folders") or [])
    if folder not in folders:
        folders.append(folder)
    save_workspace(WORK_DIR, {"folders": folders, "pipelineFolders": pf})


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
        ("demos/api-databricks-sql/pipeline.json", "demo-api-databricks-sql"),
        ("demos/lookup-join-mapper/pipeline.json", "demo-lookup-join-mapper"),
        ("demos/master-file-to-databricks/pipeline.json", "demo-master-file-to-databricks"),
        ("demos/master-file-to-databricks/child-ingest.json", "demo-master-child-ingest"),
        ("demos/master-file-to-databricks/child-load.json", "demo-master-child-load"),
    ):
        demo_path = WORK_DIR / rel
        if not demo_path.exists():
            continue
        if not refresh and pipelines.get(pid) is not None:
            # Still stamp folder if an older install lacks metadata.workspace_folder.
            existing = pipelines.get(pid)
            if existing is not None and not folder_from_metadata(existing.metadata):
                stamped = apply_demo_workspace_folder(pid, existing.metadata)
                if stamped != (existing.metadata or {}):
                    existing.metadata = stamped
                    pipelines.save(existing)
            continue
        data = json.loads(demo_path.read_text(encoding="utf-8"))
        data["id"] = pid
        data["metadata"] = apply_demo_workspace_folder(pid, data.get("metadata") or {})
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
            connections=connections,
            secret_provider=_secret_provider(),
        )
    return _worker


@app.on_event("startup")
def startup() -> None:
    pipelines.ensure()
    schedules.ensure()
    runs.ensure()
    connections.ensure()
    _ensure_demo_loaded(refresh=True)
    # Drop legacy demo id so product UI never lists competitor-named pipelines
    pipelines.delete("demo-talend-core-path")
    sync_workspace_from_pipelines(WORK_DIR, pipelines.list())
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
        "version": "0.3.0",
        "work_dir": str(WORK_DIR),
        "db_path": str(DB_PATH),
        "scheduler": os.environ.get("FORMULAETL_SCHEDULER", "1") != "0",
        "embedded_worker": EMBEDDED_WORKER,
        "queue_depth": runs.queue_depth(),
        # Honesty labels for operators
        "run_store": "sqlite",
        "data_path": "in_process_batches_and_artifact_handles",
        "auth": _auth_mode(),
        "secrets": "env_and_local_encrypted",
        "readiness_level": "ALPHA",
    }


@app.get("/api/components")
def api_components() -> list[dict[str, Any]]:
    return list_components()


@app.post("/api/schema/discover")
def schema_discover(body: SchemaDiscoverRequest) -> dict[str, Any]:
    """Infer columns + types from a source connection/sample."""
    from formulaetl.schema.discover import discover
    from formulaetl.sdk.connections import resolve_node_config

    cfg = dict(body.config)
    if body.connection_id:
        cfg["connection_id"] = body.connection_id
    try:
        resolved = resolve_node_config(
            cfg,
            component_type=body.component_type,
            get_connection=connections.get,
            provider=_secret_provider(),
        )
        return discover(
            body.component_type,
            resolved,
            work_dir=WORK_DIR,
            demo_mode=DEMO_MODE,
        )
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"Schema discovery failed: {exc}") from exc


# ── Connections (Phase F) ────────────────────────────────────────────────────


@app.get("/api/connections/kinds")
def list_connection_kinds() -> dict[str, Any]:
    return {"kinds": sorted(CONNECTION_KINDS)}


@app.get("/api/connections")
def list_connections(kind: str | None = None) -> list[dict[str, Any]]:
    connections.ensure()
    return [c.to_public_dict() for c in connections.list(kind=kind)]


@app.post("/api/connections", status_code=201)
def create_connection(body: ConnectionCreate) -> dict[str, Any]:
    try:
        rec = connections.create(
            name=body.name,
            kind=body.kind,
            config=body.config,
            secrets=body.secrets,
            description=body.description,
            connection_id=body.id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return rec.to_public_dict()


@app.get("/api/connections/{connection_id}")
def get_connection(connection_id: str) -> dict[str, Any]:
    rec = connections.get(connection_id)
    if not rec:
        raise HTTPException(404, f"Connection '{connection_id}' not found")
    return rec.to_public_dict()


@app.put("/api/connections/{connection_id}")
def update_connection(connection_id: str, body: ConnectionUpdate) -> dict[str, Any]:
    rec = connections.update(
        connection_id,
        name=body.name,
        description=body.description,
        config=body.config,
        secrets=body.secrets,
    )
    if rec is None:
        raise HTTPException(404, f"Connection '{connection_id}' not found")
    return rec.to_public_dict()


@app.delete("/api/connections/{connection_id}")
def delete_connection(connection_id: str) -> dict[str, str]:
    if not connections.delete(connection_id):
        raise HTTPException(404, f"Connection '{connection_id}' not found")
    return {"status": "deleted", "id": connection_id}


@app.post("/api/connections/{connection_id}/test")
def test_connection(connection_id: str) -> dict[str, Any]:
    try:
        return connections.test_connection(connection_id, demo_mode=DEMO_MODE)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/pipelines")
def list_pipelines() -> list[dict[str, Any]]:
    _ensure_demo_loaded()
    return [_mask_pipeline_dict(p.model_dump()) for p in pipelines.list()]


@app.post("/api/pipelines", status_code=201)
def create_pipeline(body: PipelineCreate) -> dict[str, Any]:
    pid = body.id or str(uuid.uuid4())
    meta = dict(body.metadata or {})
    if not folder_from_metadata(meta):
        meta = stamp_workspace_folder(meta, DEFAULT_MY_PIPELINES)
    pipeline = PipelineDefinition(
        id=pid,
        name=body.name,
        description=body.description,
        nodes=body.nodes,
        edges=body.edges,
        metadata=meta,
    )
    version = pipelines.save(pipeline)
    saved_path = _mirror_pipeline_to_disk(pipeline)
    _index_pipeline_folder(pipeline)
    out = _mask_pipeline_dict(pipeline.model_dump())
    out["pipeline_version_id"] = version.id
    out["version"] = str(version.version_num)
    out["saved_path"] = saved_path
    return out


@app.post("/api/pipelines/import", status_code=201)
def import_pipeline(body: PipelineImport) -> dict[str, Any]:
    """Create a pipeline from exported / mirror JSON (new id unless ``id`` is set and unused)."""
    pid = body.id or str(uuid.uuid4())
    if body.id and pipelines.get(pid) is not None:
        # Avoid clobbering an existing head — assign a fresh id.
        pid = str(uuid.uuid4())
    meta = dict(body.metadata or {})
    meta.setdefault("imported", True)
    if not folder_from_metadata(meta):
        meta = stamp_workspace_folder(meta, DEFAULT_MY_PIPELINES)
    pipeline = PipelineDefinition(
        id=pid,
        name=body.name,
        description=body.description,
        nodes=body.nodes,
        edges=body.edges,
        metadata=meta,
    )
    version = pipelines.save(pipeline)
    saved_path = _mirror_pipeline_to_disk(pipeline)
    _index_pipeline_folder(pipeline)
    out = _mask_pipeline_dict(pipeline.model_dump())
    out["pipeline_version_id"] = version.id
    out["version"] = str(version.version_num)
    out["saved_path"] = saved_path
    return out


@app.get("/api/pipelines/{pipeline_id}")
def get_pipeline(pipeline_id: str) -> dict[str, Any]:
    _ensure_demo_loaded()
    p = pipelines.get(pipeline_id)
    if not p:
        raise HTTPException(404, f"Pipeline '{pipeline_id}' not found")
    out = _mask_pipeline_dict(p.model_dump())
    ver = pipelines.get_current_version(pipeline_id)
    if ver:
        out["pipeline_version_id"] = ver.id
        out["content_hash"] = ver.content_hash
    mirror = WORK_DIR / "pipelines" / f"{pipeline_id}.json"
    if mirror.is_file():
        out["saved_path"] = str(mirror.resolve())
    return out


@app.put("/api/pipelines/{pipeline_id}")
def update_pipeline(pipeline_id: str, body: PipelineCreate) -> dict[str, Any]:
    existing = pipelines.get(pipeline_id)
    meta = dict(body.metadata or {})
    # Preserve folder assignment across Save when client omits it.
    if not folder_from_metadata(meta) and existing is not None:
        prev = folder_from_metadata(existing.metadata)
        if prev:
            meta = stamp_workspace_folder(meta, prev)
        else:
            ws = load_workspace(WORK_DIR)
            meta = stamp_workspace_folder(
                meta,
                resolve_pipeline_folder(pipeline_id, existing.metadata, ws),
            )
    elif not folder_from_metadata(meta):
        meta = stamp_workspace_folder(meta, DEFAULT_MY_PIPELINES)
    pipeline = PipelineDefinition(
        id=pipeline_id,
        name=body.name,
        description=body.description,
        nodes=body.nodes,
        edges=body.edges,
        metadata=meta,
    )
    version = pipelines.save(pipeline)
    saved_path = _mirror_pipeline_to_disk(pipeline)
    _index_pipeline_folder(pipeline)
    out = _mask_pipeline_dict(pipeline.model_dump())
    out["pipeline_version_id"] = version.id
    out["version"] = str(version.version_num)
    out["saved_path"] = saved_path
    return out


# ── Workspace (Studio folder tree) ───────────────────────────────────────────


@app.get("/api/workspace")
def get_workspace() -> dict[str, Any]:
    """Folder list + pipeline→folder map for the Studio Workspace tree."""
    _ensure_demo_loaded()
    return sync_workspace_from_pipelines(WORK_DIR, pipelines.list())


@app.put("/api/workspace")
def put_workspace(body: WorkspaceUpdate) -> dict[str, Any]:
    """Replace workspace folder list / index (does not rewrite pipeline metadata)."""
    return save_workspace(
        WORK_DIR,
        {"folders": body.folders, "pipelineFolders": body.pipelineFolders},
    )


@app.post("/api/workspace/move")
def move_pipeline_folder(body: WorkspaceMove) -> dict[str, Any]:
    """Assign a pipeline to a Workspace folder (updates metadata + index)."""
    _ensure_demo_loaded()
    p = pipelines.get(body.pipeline_id)
    if not p:
        raise HTTPException(404, f"Pipeline '{body.pipeline_id}' not found")
    p.metadata = stamp_workspace_folder(p.metadata, body.folder)
    pipelines.save(p)
    _mirror_pipeline_to_disk(p)
    _index_pipeline_folder(p)
    ws = sync_workspace_from_pipelines(WORK_DIR, pipelines.list())
    return {
        "pipeline_id": p.id,
        "folder": folder_from_metadata(p.metadata),
        "workspace": ws,
        "pipeline": _mask_pipeline_dict(p.model_dump()),
    }


@app.get("/api/pipelines/{pipeline_id}/export")
def export_pipeline(
    pipeline_id: str,
    format: str = Query("json", pattern="^(json|zip)$"),
) -> Response:
    """Download pipeline JSON (or zip with README) for run-elsewhere / Git workflows."""
    _ensure_demo_loaded()
    p = pipelines.get(pipeline_id)
    if not p:
        raise HTTPException(404, f"Pipeline '{pipeline_id}' not found")
    dump = p.model_dump(mode="json")
    # Export unmasked graph for round-trip; secrets should be refs, not literals.
    payload = json.dumps(dump, indent=2, ensure_ascii=False, default=str) + "\n"
    stem = _safe_export_stem(p.name, pipeline_id)
    json_name = f"{stem}.json"
    if format == "zip":
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(json_name, payload)
            zf.writestr("README.md", _export_readme(p, json_name))
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{stem}.zip"',
            },
        )
    return Response(
        content=payload,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{json_name}"',
        },
    )


@app.delete("/api/pipelines/{pipeline_id}")
def delete_pipeline(pipeline_id: str) -> dict[str, str]:
    if not pipelines.delete(pipeline_id):
        raise HTTPException(404, f"Pipeline '{pipeline_id}' not found")
    _remove_pipeline_mirror(pipeline_id)
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
    data = v.to_dict()
    if isinstance(data.get("definition"), dict):
        data["definition"] = _mask_pipeline_dict(data["definition"])
    return data


@app.post("/api/pipelines/{pipeline_id}/validate")
def validate_pipeline(
    pipeline_id: str, body: PipelineValidateBody | None = None
) -> dict[str, Any]:
    """Structured preflight: graph, required params, connection_id, secret refs, mappings.

    Pass an optional body with ``nodes``/``edges`` to validate the current canvas
    without saving. Never reveals secret values.
    """
    stored = pipelines.get(pipeline_id)
    if not stored:
        _ensure_demo_loaded()
        stored = pipelines.get(pipeline_id)

    if body is not None and body.nodes is not None:
        pipeline = PipelineDefinition(
            id=pipeline_id,
            name=body.name or (stored.name if stored else pipeline_id),
            description=body.description
            if body.description is not None
            else (stored.description if stored else ""),
            nodes=body.nodes,
            edges=body.edges if body.edges is not None else [],
            metadata=body.metadata
            if body.metadata is not None
            else (stored.metadata if stored else {}),
        )
    else:
        if not stored:
            raise HTTPException(404, f"Pipeline '{pipeline_id}' not found")
        pipeline = stored

    result = validate_pipeline_definition(
        pipeline,
        get_connection=connections.get,
        secret_exists=_secret_exists,
    )
    result["pipeline_id"] = pipeline_id
    return result


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
    node_runs = [n.to_dict() for n in runs.list_node_runs(run_id)]
    events = [e.to_dict() for e in runs.list_events(run_id)]
    out["node_runs"] = node_runs
    out["events"] = events
    # Ensure aggregate row counts / duration are always visible at top level
    metrics = dict(out.get("metrics") or {})
    if "rows_in" not in metrics and node_runs:
        metrics["rows_in"] = sum(int(n.get("rows_in") or 0) for n in node_runs)
        metrics["rows_out"] = sum(int(n.get("rows_out") or 0) for n in node_runs)
        metrics["rows_rejected"] = sum(int(n.get("rows_rejected") or 0) for n in node_runs)
    if out.get("duration_ms") in (None, 0) and metrics.get("duration_ms"):
        out["duration_ms"] = metrics["duration_ms"]
    out["metrics"] = metrics
    out["summary"] = run_summary_from_detail(
        status=out.get("status") or r.status,
        metrics=metrics,
        duration_ms=float(out.get("duration_ms") or 0.0),
        node_runs=node_runs,
        events=events,
    )
    return out


@app.post("/api/ai/build")
def ai_build(body: AIBuildRequest) -> dict[str, Any]:
    # Never forward secret material — description is user text only.
    # Heuristic/LLM builders must not embed passwords (see ai_builder).
    pipeline = build_pipeline_from_text(body.description, name=body.name)
    # Strip any accidental secret literals from generated nodes before save
    cleaned_nodes = []
    for node in pipeline.nodes:
        n = node.model_dump() if hasattr(node, "model_dump") else dict(node)
        n["config"] = strip_secrets_for_ai(
            dict(n.get("config") or {}), component_type=n.get("type")
        )
        # Prefer empty secrets over "[omitted]" markers in stored graph
        cfg = n["config"]
        for k, v in list(cfg.items()):
            if v == "[omitted]":
                cfg[k] = ""
        cleaned_nodes.append(n)
    pipeline = PipelineDefinition(
        id=pipeline.id,
        name=pipeline.name,
        description=pipeline.description,
        nodes=cleaned_nodes,
        edges=pipeline.edges,
        metadata=pipeline.metadata,
    )
    version = pipelines.save(pipeline)
    saved_path = _mirror_pipeline_to_disk(pipeline)
    out = _mask_pipeline_dict(pipeline.model_dump())
    out["pipeline_version_id"] = version.id
    out["saved_path"] = saved_path
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
