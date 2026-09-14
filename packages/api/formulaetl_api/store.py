"""Durable SQLite stores for pipelines, versions, runs, schedules, and the job queue.

Local/Community default is SQLite under ``data/formulaetl.db``. Table shapes avoid
SQLite-only types so a later Postgres backend can reuse the same entity model.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from formulaetl.engine.runner import RunResult
from formulaetl.models.pipeline import PipelineDefinition
from formulaetl_api.db import (
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    STATUS_SUCCESS,
    TERMINAL_STATUSES,
    Database,
)


def _now() -> float:
    return time.time()


def pipeline_content_hash(definition: dict[str, Any]) -> str:
    """Stable hash of the executable graph (not cosmetic metadata alone)."""
    payload = {
        "name": definition.get("name", ""),
        "description": definition.get("description", ""),
        "nodes": definition.get("nodes", []),
        "edges": definition.get("edges", []),
        "metadata": definition.get("metadata", {}),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class PipelineVersion:
    id: str
    pipeline_id: str
    version_num: int
    content_hash: str
    definition: dict[str, Any]
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "pipeline_id": self.pipeline_id,
            "version_num": self.version_num,
            "content_hash": self.content_hash,
            "definition": self.definition,
            "created_at": self.created_at,
        }

    def as_pipeline(self) -> PipelineDefinition:
        data = dict(self.definition)
        data["id"] = self.pipeline_id
        data["version"] = str(self.version_num)
        return PipelineDefinition.model_validate(data)


@dataclass
class NodeRunRecord:
    id: str
    run_id: str
    node_id: str
    component_type: str
    status: str
    started_at: float | None = None
    finished_at: float | None = None
    rows_in: int = 0
    rows_out: int = 0
    rows_rejected: int = 0
    error: str | None = None
    duration_ms: float = 0.0
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RunEvent:
    id: int | None
    run_id: str
    ts: float
    event_type: str
    from_status: str | None = None
    to_status: str | None = None
    message: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "ts": self.ts,
            "event_type": self.event_type,
            "from_status": self.from_status,
            "to_status": self.to_status,
            "message": self.message,
            "payload": self.payload,
        }


@dataclass
class DurableRun:
    """Run record returned by the durable store (superset of RunResult fields)."""

    run_id: str
    pipeline_id: str
    pipeline_version_id: str
    status: str
    metrics: dict[str, Any] = field(default_factory=dict)
    node_metrics: dict[str, dict[str, Any]] = field(default_factory=dict)
    logs: list[str] = field(default_factory=list)
    error: str | None = None
    outputs: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    created_at: float = 0.0
    started_at: float | None = None
    finished_at: float | None = None
    updated_at: float = 0.0

    def to_run_result(self) -> RunResult:
        return RunResult(
            run_id=self.run_id,
            pipeline_id=self.pipeline_id,
            status=self.status,
            metrics=dict(self.metrics),
            node_metrics=dict(self.node_metrics),
            logs=list(self.logs),
            error=self.error,
            outputs=dict(self.outputs),
            duration_ms=self.duration_ms,
        )

    def to_dict(self, *, include_detail: bool = True) -> dict[str, Any]:
        base = {
            "run_id": self.run_id,
            "pipeline_id": self.pipeline_id,
            "pipeline_version_id": self.pipeline_version_id,
            "status": self.status,
            "metrics": self.metrics,
            "duration_ms": self.duration_ms,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }
        if include_detail:
            base.update(
                {
                    "node_metrics": self.node_metrics,
                    "logs": self.logs,
                    "error": self.error,
                    "outputs": self.outputs,
                    "updated_at": self.updated_at,
                }
            )
        return base


def _as_database(db: Database | Path | str, *, default_name: str) -> tuple[Database, Path | None]:
    """Accept a Database or a legacy directory/file path."""
    if isinstance(db, Database):
        return db, None
    path = Path(db)
    if path.suffix == ".db" or str(db) == ":memory:":
        return Database(path if str(db) != ":memory:" else ":memory:"), None
    # Legacy directory → SQLite file beside / inside it
    path.mkdir(parents=True, exist_ok=True)
    return Database(path / default_name), path


class PipelineStore:
    """SQLite pipeline + immutable version store (JSON files migrated on ensure)."""

    def __init__(
        self,
        db: Database | Path | str,
        legacy_json_root: Path | None = None,
    ):
        resolved, inferred_legacy = _as_database(db, default_name="pipelines.db")
        self.db = resolved
        self.legacy_json_root = (
            legacy_json_root if legacy_json_root is not None else inferred_legacy
        )
        self._lock = threading.Lock()

    def ensure(self) -> None:
        self.db.ensure()
        if self.legacy_json_root is not None:
            self._migrate_legacy_json()

    def _migrate_legacy_json(self) -> None:
        root = self.legacy_json_root
        if root is None or not root.exists():
            return
        for path in sorted(root.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                pid = str(data.get("id") or path.stem)
                if self.get(pid) is not None:
                    continue
                data["id"] = pid
                self.save(PipelineDefinition.model_validate(data))
            except Exception:
                continue

    def save(self, pipeline: PipelineDefinition) -> PipelineVersion:
        """Upsert pipeline head and create a new immutable version when content changes."""
        self.ensure()
        now = _now()
        dump = pipeline.model_dump(mode="json")
        content_hash = pipeline_content_hash(dump)
        with self._lock:
            existing = self.db.execute(
                "SELECT id, current_version_id, created_at FROM pipelines WHERE id = ?",
                (pipeline.id,),
            ).fetchone()
            same = self.db.execute(
                "SELECT id, pipeline_id, version_num, content_hash, definition_json, created_at "
                "FROM pipeline_versions WHERE pipeline_id = ? AND content_hash = ?",
                (pipeline.id, content_hash),
            ).fetchone()
            meta_json = json.dumps(pipeline.metadata, default=str)
            if same is not None:
                version = self._row_to_version(same)
                if existing is None:
                    self.db.execute(
                        "INSERT INTO pipelines(id, name, description, current_version_id, "
                        "created_at, updated_at, metadata_json) VALUES (?,?,?,?,?,?,?)",
                        (
                            pipeline.id,
                            pipeline.name,
                            pipeline.description,
                            version.id,
                            now,
                            now,
                            meta_json,
                        ),
                    )
                else:
                    self.db.execute(
                        "UPDATE pipelines SET name=?, description=?, current_version_id=?, "
                        "updated_at=?, metadata_json=? WHERE id=?",
                        (
                            pipeline.name,
                            pipeline.description,
                            version.id,
                            now,
                            meta_json,
                            pipeline.id,
                        ),
                    )
                return version

            row = self.db.execute(
                "SELECT COALESCE(MAX(version_num), 0) AS m FROM pipeline_versions "
                "WHERE pipeline_id = ?",
                (pipeline.id,),
            ).fetchone()
            next_num = int(row["m"]) + 1
            version_id = str(uuid.uuid4())
            dump["version"] = str(next_num)
            self.db.execute(
                "INSERT INTO pipeline_versions(id, pipeline_id, version_num, content_hash, "
                "definition_json, created_at) VALUES (?,?,?,?,?,?)",
                (
                    version_id,
                    pipeline.id,
                    next_num,
                    content_hash,
                    json.dumps(dump, default=str),
                    now,
                ),
            )
            if existing is None:
                self.db.execute(
                    "INSERT INTO pipelines(id, name, description, current_version_id, "
                    "created_at, updated_at, metadata_json) VALUES (?,?,?,?,?,?,?)",
                    (
                        pipeline.id,
                        pipeline.name,
                        pipeline.description,
                        version_id,
                        now,
                        now,
                        meta_json,
                    ),
                )
            else:
                self.db.execute(
                    "UPDATE pipelines SET name=?, description=?, current_version_id=?, "
                    "updated_at=?, metadata_json=? WHERE id=?",
                    (
                        pipeline.name,
                        pipeline.description,
                        version_id,
                        now,
                        meta_json,
                        pipeline.id,
                    ),
                )
            return PipelineVersion(
                id=version_id,
                pipeline_id=pipeline.id,
                version_num=next_num,
                content_hash=content_hash,
                definition=dump,
                created_at=now,
            )

    def get(self, pid: str) -> PipelineDefinition | None:
        self.ensure()
        row = self.db.execute(
            "SELECT p.id, v.definition_json FROM pipelines p "
            "LEFT JOIN pipeline_versions v ON v.id = p.current_version_id "
            "WHERE p.id = ?",
            (pid,),
        ).fetchone()
        if row is None or row["definition_json"] is None:
            return None
        data = json.loads(row["definition_json"])
        data["id"] = pid
        return PipelineDefinition.model_validate(data)

    def get_current_version(self, pid: str) -> PipelineVersion | None:
        self.ensure()
        row = self.db.execute(
            "SELECT v.id, v.pipeline_id, v.version_num, v.content_hash, "
            "v.definition_json, v.created_at FROM pipelines p "
            "JOIN pipeline_versions v ON v.id = p.current_version_id "
            "WHERE p.id = ?",
            (pid,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_version(row)

    def get_version(self, version_id: str) -> PipelineVersion | None:
        self.ensure()
        row = self.db.execute(
            "SELECT id, pipeline_id, version_num, content_hash, definition_json, created_at "
            "FROM pipeline_versions WHERE id = ?",
            (version_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_version(row)

    def list_versions(self, pipeline_id: str) -> list[PipelineVersion]:
        self.ensure()
        rows = self.db.execute(
            "SELECT id, pipeline_id, version_num, content_hash, definition_json, created_at "
            "FROM pipeline_versions WHERE pipeline_id = ? ORDER BY version_num DESC",
            (pipeline_id,),
        ).fetchall()
        return [self._row_to_version(r) for r in rows]

    def list(self) -> list[PipelineDefinition]:
        self.ensure()
        rows = self.db.execute(
            "SELECT p.id, v.definition_json FROM pipelines p "
            "LEFT JOIN pipeline_versions v ON v.id = p.current_version_id "
            "ORDER BY p.updated_at DESC"
        ).fetchall()
        out: list[PipelineDefinition] = []
        for row in rows:
            if row["definition_json"] is None:
                continue
            try:
                data = json.loads(row["definition_json"])
                data["id"] = row["id"]
                out.append(PipelineDefinition.model_validate(data))
            except Exception:
                continue
        return out

    def delete(self, pid: str) -> bool:
        self.ensure()
        with self._lock:
            cur = self.db.execute("DELETE FROM pipelines WHERE id = ?", (pid,))
            # Keep historical versions + runs for audit; only drop head pointer row.
            return cur.rowcount > 0

    @staticmethod
    def _row_to_version(row: Any) -> PipelineVersion:
        return PipelineVersion(
            id=row["id"],
            pipeline_id=row["pipeline_id"],
            version_num=int(row["version_num"]),
            content_hash=row["content_hash"],
            definition=json.loads(row["definition_json"]),
            created_at=float(row["created_at"]),
        )


class RunStore:
    """Durable run ledger + state transitions + node_runs + events."""

    def __init__(self, db: Database | Path | str | None = None):
        if db is None:
            self.db = Database(":memory:")
        elif isinstance(db, Database):
            self.db = db
        else:
            self.db, _ = _as_database(db, default_name="runs.db")
        self._lock = threading.Lock()

    def ensure(self) -> None:
        self.db.ensure()

    def enqueue(
        self,
        *,
        run_id: str,
        pipeline_id: str,
        pipeline_version_id: str,
        logs: list[str] | None = None,
    ) -> DurableRun:
        """Create a QUEUED run and queue row. Returns quickly."""
        self.ensure()
        now = _now()
        logs = list(logs or [])
        with self._lock, self.db._lock:
            conn = self.db.connect()
            conn.execute(
                "INSERT INTO runs(run_id, pipeline_id, pipeline_version_id, status, "
                "metrics_json, node_metrics_json, logs_json, error, outputs_json, "
                "duration_ms, created_at, started_at, finished_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    pipeline_id,
                    pipeline_version_id,
                    STATUS_QUEUED,
                    "{}",
                    "{}",
                    json.dumps(logs),
                    None,
                    "{}",
                    0.0,
                    now,
                    None,
                    None,
                    now,
                ),
            )
            conn.execute(
                "INSERT INTO job_queue(run_id, pipeline_id, pipeline_version_id, "
                "status, claimed_by, claimed_at, created_at, priority) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    pipeline_id,
                    pipeline_version_id,
                    "queued",
                    None,
                    None,
                    now,
                    0,
                ),
            )
            conn.execute(
                "INSERT INTO run_events(run_id, ts, event_type, from_status, to_status, "
                "message, payload_json) VALUES (?,?,?,?,?,?,?)",
                (
                    run_id,
                    now,
                    "state_transition",
                    None,
                    STATUS_QUEUED,
                    "Run queued",
                    "{}",
                ),
            )
        return self.get(run_id)  # type: ignore[return-value]

    def claim_next(self, worker_id: str) -> DurableRun | None:
        """Atomically claim the next queued job (no global run lock)."""
        self.ensure()
        now = _now()
        with self._lock, self.db._lock:
            conn = self.db.connect()
            cur = conn.execute(
                "UPDATE job_queue SET status='claimed', claimed_by=?, claimed_at=? "
                "WHERE run_id = ("
                "  SELECT run_id FROM job_queue WHERE status = 'queued' "
                "  ORDER BY priority DESC, created_at ASC LIMIT 1"
                ") AND status = 'queued'",
                (worker_id, now),
            )
            if cur.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT run_id FROM job_queue WHERE claimed_by=? AND status='claimed' "
                "ORDER BY claimed_at DESC LIMIT 1",
                (worker_id,),
            ).fetchone()
            if row is None:
                return None
            run_id = row["run_id"]
            cur = conn.execute(
                "UPDATE runs SET status=?, started_at=?, updated_at=? "
                "WHERE run_id=? AND status=?",
                (STATUS_RUNNING, now, now, run_id, STATUS_QUEUED),
            )
            if cur.rowcount == 0:
                return None
            conn.execute(
                "INSERT INTO run_events(run_id, ts, event_type, from_status, to_status, "
                "message, payload_json) VALUES (?,?,?,?,?,?,?)",
                (
                    run_id,
                    now,
                    "state_transition",
                    STATUS_QUEUED,
                    STATUS_RUNNING,
                    f"Claimed by worker {worker_id}",
                    "{}",
                ),
            )
        return self.get(run_id)

    def transition(
        self,
        run_id: str,
        to_status: str,
        *,
        message: str | None = None,
        error: str | None = None,
    ) -> DurableRun | None:
        self.ensure()
        now = _now()
        with self._lock:
            current = self.get(run_id)
            if current is None:
                return None
            from_status = current.status
            finished = to_status in TERMINAL_STATUSES
            self.db.execute(
                "UPDATE runs SET status=?, error=COALESCE(?, error), updated_at=?, "
                "finished_at=CASE WHEN ? THEN ? ELSE finished_at END WHERE run_id=?",
                (to_status, error, now, 1 if finished else 0, now if finished else None, run_id),
            )
            self._insert_event(
                run_id,
                now,
                "state_transition",
                from_status=from_status,
                to_status=to_status,
                message=message or f"{from_status} → {to_status}",
            )
            if finished:
                self.db.execute(
                    "UPDATE job_queue SET status='done' WHERE run_id=?",
                    (run_id,),
                )
        return self.get(run_id)

    def complete_from_result(self, result: RunResult, pipeline_version_id: str) -> DurableRun:
        """Persist final runner result + node_runs. Status from result."""
        self.ensure()
        now = _now()
        status = result.status
        if status not in TERMINAL_STATUSES and status not in (
            STATUS_RUNNING,
            STATUS_QUEUED,
            STATUS_RETRYING,
        ):
            # Normalize legacy / unexpected
            status = STATUS_FAILED if result.error else STATUS_SUCCESS
        with self._lock:
            prev = self.get(result.run_id)
            from_status = prev.status if prev else STATUS_RUNNING
            self.db.execute(
                "UPDATE runs SET status=?, metrics_json=?, node_metrics_json=?, "
                "logs_json=?, error=?, outputs_json=?, duration_ms=?, updated_at=?, "
                "finished_at=?, pipeline_version_id=COALESCE(pipeline_version_id, ?) "
                "WHERE run_id=?",
                (
                    status,
                    json.dumps(result.metrics, default=str),
                    json.dumps(result.node_metrics, default=str),
                    json.dumps(result.logs, default=str),
                    result.error,
                    json.dumps(result.outputs, default=str),
                    float(result.duration_ms or 0.0),
                    now,
                    now if status in TERMINAL_STATUSES else None,
                    pipeline_version_id,
                    result.run_id,
                ),
            )
            self._insert_event(
                result.run_id,
                now,
                "state_transition",
                from_status=from_status,
                to_status=status,
                message=result.error or "Run finished",
            )
            if status in TERMINAL_STATUSES:
                self.db.execute(
                    "UPDATE job_queue SET status='done' WHERE run_id=?",
                    (result.run_id,),
                )
            self._upsert_node_runs(result, started_at=prev.started_at if prev else now)
        return self.get(result.run_id)  # type: ignore[return-value]

    def append_log(self, run_id: str, line: str) -> None:
        self.ensure()
        with self._lock:
            row = self.db.execute(
                "SELECT logs_json FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if row is None:
                return
            logs = json.loads(row["logs_json"] or "[]")
            logs.append(line)
            self.db.execute(
                "UPDATE runs SET logs_json=?, updated_at=? WHERE run_id=?",
                (json.dumps(logs), _now(), run_id),
            )

    def put(self, result: RunResult) -> None:
        """Compatibility shim — prefer enqueue / complete_from_result."""
        self.ensure()
        existing = self.get(result.run_id)
        if existing is None:
            # Legacy path: treat as already-running insert without queue row.
            now = _now()
            with self._lock:
                self.db.execute(
                    "INSERT INTO runs(run_id, pipeline_id, pipeline_version_id, status, "
                    "metrics_json, node_metrics_json, logs_json, error, outputs_json, "
                    "duration_ms, created_at, started_at, finished_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        result.run_id,
                        result.pipeline_id,
                        "",
                        result.status,
                        json.dumps(result.metrics, default=str),
                        json.dumps(result.node_metrics, default=str),
                        json.dumps(result.logs, default=str),
                        result.error,
                        json.dumps(result.outputs, default=str),
                        float(result.duration_ms or 0.0),
                        now,
                        now,
                        now if result.status in TERMINAL_STATUSES else None,
                        now,
                    ),
                )
        else:
            self.update(result)

    def update(self, result: RunResult) -> None:
        self.ensure()
        existing = self.get(result.run_id)
        version_id = existing.pipeline_version_id if existing else ""
        self.complete_from_result(result, version_id)

    def get(self, run_id: str) -> DurableRun | None:
        self.ensure()
        row = self.db.execute(
            "SELECT run_id, pipeline_id, pipeline_version_id, status, metrics_json, "
            "node_metrics_json, logs_json, error, outputs_json, duration_ms, "
            "created_at, started_at, finished_at, updated_at FROM runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_run(row)

    def list(self) -> list[DurableRun]:
        self.ensure()
        rows = self.db.execute(
            "SELECT run_id, pipeline_id, pipeline_version_id, status, metrics_json, "
            "node_metrics_json, logs_json, error, outputs_json, duration_ms, "
            "created_at, started_at, finished_at, updated_at FROM runs "
            "ORDER BY created_at DESC"
        ).fetchall()
        return [self._row_to_run(r) for r in rows]

    def list_events(self, run_id: str) -> list[RunEvent]:
        self.ensure()
        rows = self.db.execute(
            "SELECT id, run_id, ts, event_type, from_status, to_status, message, "
            "payload_json FROM run_events WHERE run_id=? ORDER BY id ASC",
            (run_id,),
        ).fetchall()
        return [
            RunEvent(
                id=r["id"],
                run_id=r["run_id"],
                ts=float(r["ts"]),
                event_type=r["event_type"],
                from_status=r["from_status"],
                to_status=r["to_status"],
                message=r["message"],
                payload=json.loads(r["payload_json"] or "{}"),
            )
            for r in rows
        ]

    def list_node_runs(self, run_id: str) -> list[NodeRunRecord]:
        self.ensure()
        rows = self.db.execute(
            "SELECT id, run_id, node_id, component_type, status, started_at, finished_at, "
            "rows_in, rows_out, rows_rejected, error, duration_ms, extras_json "
            "FROM node_runs WHERE run_id=? ORDER BY started_at ASC",
            (run_id,),
        ).fetchall()
        return [
            NodeRunRecord(
                id=r["id"],
                run_id=r["run_id"],
                node_id=r["node_id"],
                component_type=r["component_type"],
                status=r["status"],
                started_at=r["started_at"],
                finished_at=r["finished_at"],
                rows_in=int(r["rows_in"] or 0),
                rows_out=int(r["rows_out"] or 0),
                rows_rejected=int(r["rows_rejected"] or 0),
                error=r["error"],
                duration_ms=float(r["duration_ms"] or 0.0),
                extras=json.loads(r["extras_json"] or "{}"),
            )
            for r in rows
        ]

    def queue_depth(self) -> int:
        self.ensure()
        row = self.db.execute(
            "SELECT COUNT(*) AS c FROM job_queue WHERE status='queued'"
        ).fetchone()
        return int(row["c"]) if row else 0

    def _insert_event(
        self,
        run_id: str,
        ts: float,
        event_type: str,
        *,
        from_status: str | None,
        to_status: str | None,
        message: str | None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.db.execute(
            "INSERT INTO run_events(run_id, ts, event_type, from_status, to_status, "
            "message, payload_json) VALUES (?,?,?,?,?,?,?)",
            (
                run_id,
                ts,
                event_type,
                from_status,
                to_status,
                message,
                json.dumps(payload or {}, default=str),
            ),
        )

    def _upsert_node_runs(self, result: RunResult, *, started_at: float | None) -> None:
        base_t = started_at or _now()
        cursor_t = base_t
        # Prefer explicit plan order when present
        order: list[str] = []
        plan = result.plan or {}
        if isinstance(plan, dict) and plan.get("order"):
            order = list(plan["order"])
        else:
            order = list(result.node_metrics.keys())
        for nid in order:
            metrics = result.node_metrics.get(nid) or {}
            duration_ms = float(metrics.get("duration_ms") or 0.0)
            node_start = cursor_t
            node_end = cursor_t + (duration_ms / 1000.0)
            cursor_t = node_end
            status = STATUS_SUCCESS
            if result.status == STATUS_FAILED and nid == order[-1] and result.error:
                status = STATUS_FAILED
            # component_type from outputs or metrics extras
            component_type = (
                (result.outputs.get(nid) or {}).get("component_type")
                or metrics.get("component_type")
                or metrics.get("type")
                or "unknown"
            )
            extras = {
                k: v
                for k, v in metrics.items()
                if k
                not in {
                    "rows_in",
                    "rows_out",
                    "rows_rejected",
                    "duration_ms",
                    "component_type",
                    "type",
                }
            }
            nr_id = f"{result.run_id}:{nid}"
            self.db.execute(
                "INSERT INTO node_runs(id, run_id, node_id, component_type, status, "
                "started_at, finished_at, rows_in, rows_out, rows_rejected, error, "
                "duration_ms, extras_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(run_id, node_id) DO UPDATE SET "
                "component_type=excluded.component_type, status=excluded.status, "
                "started_at=excluded.started_at, finished_at=excluded.finished_at, "
                "rows_in=excluded.rows_in, rows_out=excluded.rows_out, "
                "rows_rejected=excluded.rows_rejected, error=excluded.error, "
                "duration_ms=excluded.duration_ms, extras_json=excluded.extras_json",
                (
                    nr_id,
                    result.run_id,
                    nid,
                    str(component_type),
                    status,
                    node_start,
                    node_end,
                    int(metrics.get("rows_in") or 0),
                    int(metrics.get("rows_out") or 0),
                    int(metrics.get("rows_rejected") or 0),
                    result.error if status == STATUS_FAILED else None,
                    duration_ms,
                    json.dumps(extras, default=str),
                ),
            )

    @staticmethod
    def _row_to_run(row: Any) -> DurableRun:
        return DurableRun(
            run_id=row["run_id"],
            pipeline_id=row["pipeline_id"],
            pipeline_version_id=row["pipeline_version_id"] or "",
            status=row["status"],
            metrics=json.loads(row["metrics_json"] or "{}"),
            node_metrics=json.loads(row["node_metrics_json"] or "{}"),
            logs=json.loads(row["logs_json"] or "[]"),
            error=row["error"],
            outputs=json.loads(row["outputs_json"] or "{}"),
            duration_ms=float(row["duration_ms"] or 0.0),
            created_at=float(row["created_at"] or 0.0),
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            updated_at=float(row["updated_at"] or 0.0),
        )


# --- Schedule store (SQLite) -------------------------------------------------

@dataclass
class ScheduleSpec:
    pipeline_id: str
    enabled: bool = False
    cron: str = "*/5 * * * *"
    timezone: str = "UTC"
    next_run_at: float | None = None
    last_run_at: float | None = None
    last_run_id: str | None = None
    last_status: str | None = None
    updated_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScheduleSpec":
        return cls(
            pipeline_id=str(data["pipeline_id"]),
            enabled=bool(data.get("enabled", False)),
            cron=str(data.get("cron") or "*/5 * * * *"),
            timezone=str(data.get("timezone") or "UTC"),
            next_run_at=data.get("next_run_at"),
            last_run_at=data.get("last_run_at"),
            last_run_id=data.get("last_run_id"),
            last_status=data.get("last_status"),
            updated_at=data.get("updated_at"),
        )


class ScheduleStore:
    def __init__(
        self,
        db: Database | Path | str,
        legacy_json_root: Path | None = None,
    ):
        resolved, inferred_legacy = _as_database(db, default_name="schedules.db")
        self.db = resolved
        self.legacy_json_root = (
            legacy_json_root if legacy_json_root is not None else inferred_legacy
        )
        self._lock = threading.Lock()

    def ensure(self) -> None:
        self.db.ensure()
        if self.legacy_json_root is not None:
            self._migrate_legacy_json()

    def _migrate_legacy_json(self) -> None:
        root = self.legacy_json_root
        if root is None or not root.exists():
            return
        for path in sorted(root.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                spec = ScheduleSpec.from_dict(data)
                if self.get(spec.pipeline_id) is None:
                    self.save(spec)
            except Exception:
                continue

    def get(self, pipeline_id: str) -> ScheduleSpec | None:
        self.ensure()
        row = self.db.execute(
            "SELECT pipeline_id, enabled, cron, timezone, next_run_at, last_run_at, "
            "last_run_id, last_status, updated_at FROM schedules WHERE pipeline_id=?",
            (pipeline_id,),
        ).fetchone()
        if row is None:
            return None
        return ScheduleSpec(
            pipeline_id=row["pipeline_id"],
            enabled=bool(row["enabled"]),
            cron=row["cron"],
            timezone=row["timezone"],
            next_run_at=row["next_run_at"],
            last_run_at=row["last_run_at"],
            last_run_id=row["last_run_id"],
            last_status=row["last_status"],
            updated_at=row["updated_at"],
        )

    def save(self, spec: ScheduleSpec) -> None:
        self.ensure()
        with self._lock:
            self.db.execute(
                "INSERT INTO schedules(pipeline_id, enabled, cron, timezone, next_run_at, "
                "last_run_at, last_run_id, last_status, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(pipeline_id) DO UPDATE SET "
                "enabled=excluded.enabled, cron=excluded.cron, timezone=excluded.timezone, "
                "next_run_at=excluded.next_run_at, last_run_at=excluded.last_run_at, "
                "last_run_id=excluded.last_run_id, last_status=excluded.last_status, "
                "updated_at=excluded.updated_at",
                (
                    spec.pipeline_id,
                    1 if spec.enabled else 0,
                    spec.cron,
                    spec.timezone,
                    spec.next_run_at,
                    spec.last_run_at,
                    spec.last_run_id,
                    spec.last_status,
                    spec.updated_at,
                ),
            )

    def list(self) -> list[ScheduleSpec]:
        self.ensure()
        rows = self.db.execute(
            "SELECT pipeline_id, enabled, cron, timezone, next_run_at, last_run_at, "
            "last_run_id, last_status, updated_at FROM schedules ORDER BY pipeline_id"
        ).fetchall()
        return [
            ScheduleSpec(
                pipeline_id=r["pipeline_id"],
                enabled=bool(r["enabled"]),
                cron=r["cron"],
                timezone=r["timezone"],
                next_run_at=r["next_run_at"],
                last_run_at=r["last_run_at"],
                last_run_id=r["last_run_id"],
                last_status=r["last_status"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]

    def delete(self, pipeline_id: str) -> bool:
        self.ensure()
        cur = self.db.execute(
            "DELETE FROM schedules WHERE pipeline_id=?", (pipeline_id,)
        )
        return cur.rowcount > 0
