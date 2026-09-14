"""SQLite control-plane schema (Community / local). Postgres-ready shapes."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

SCHEMA_VERSION = 2

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pipelines (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  current_version_id TEXT,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS secrets (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  ciphertext TEXT NOT NULL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS connections (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  config_json TEXT NOT NULL DEFAULT '{}',
  secrets_json TEXT NOT NULL DEFAULT '{}',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS pipeline_versions (
  id TEXT PRIMARY KEY,
  pipeline_id TEXT NOT NULL,
  version_num INTEGER NOT NULL,
  content_hash TEXT NOT NULL,
  definition_json TEXT NOT NULL,
  created_at REAL NOT NULL,
  UNIQUE (pipeline_id, version_num),
  UNIQUE (pipeline_id, content_hash)
);

CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  pipeline_id TEXT NOT NULL,
  pipeline_version_id TEXT NOT NULL,
  status TEXT NOT NULL,
  metrics_json TEXT NOT NULL DEFAULT '{}',
  node_metrics_json TEXT NOT NULL DEFAULT '{}',
  logs_json TEXT NOT NULL DEFAULT '[]',
  error TEXT,
  outputs_json TEXT NOT NULL DEFAULT '{}',
  duration_ms REAL NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  started_at REAL,
  finished_at REAL,
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS node_runs (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  node_id TEXT NOT NULL,
  component_type TEXT NOT NULL,
  status TEXT NOT NULL,
  started_at REAL,
  finished_at REAL,
  rows_in INTEGER NOT NULL DEFAULT 0,
  rows_out INTEGER NOT NULL DEFAULT 0,
  rows_rejected INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  duration_ms REAL NOT NULL DEFAULT 0,
  extras_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE (run_id, node_id)
);

CREATE TABLE IF NOT EXISTS run_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  ts REAL NOT NULL,
  event_type TEXT NOT NULL,
  from_status TEXT,
  to_status TEXT,
  message TEXT,
  payload_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS schedules (
  pipeline_id TEXT PRIMARY KEY,
  enabled INTEGER NOT NULL DEFAULT 0,
  cron TEXT NOT NULL,
  timezone TEXT NOT NULL DEFAULT 'UTC',
  next_run_at REAL,
  last_run_at REAL,
  last_run_id TEXT,
  last_status TEXT,
  updated_at REAL
);

CREATE TABLE IF NOT EXISTS job_queue (
  run_id TEXT PRIMARY KEY,
  pipeline_id TEXT NOT NULL,
  pipeline_version_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  claimed_by TEXT,
  claimed_at REAL,
  created_at REAL NOT NULL,
  priority INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_runs_pipeline ON runs(pipeline_id, created_at);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS idx_node_runs_run ON node_runs(run_id);
CREATE INDEX IF NOT EXISTS idx_run_events_run ON run_events(run_id, ts);
CREATE INDEX IF NOT EXISTS idx_queue_status ON job_queue(status, priority, created_at);
CREATE INDEX IF NOT EXISTS idx_versions_pipeline ON pipeline_versions(pipeline_id, version_num);
CREATE INDEX IF NOT EXISTS idx_connections_kind ON connections(kind);
CREATE INDEX IF NOT EXISTS idx_secrets_name ON secrets(name);
"""

# Additive migrations when SCHEMA_VERSION increases (existing Community DBs).
_MIGRATE_V2_SQL = """
CREATE TABLE IF NOT EXISTS secrets (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  ciphertext TEXT NOT NULL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS connections (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  config_json TEXT NOT NULL DEFAULT '{}',
  secrets_json TEXT NOT NULL DEFAULT '{}',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_connections_kind ON connections(kind);
CREATE INDEX IF NOT EXISTS idx_secrets_name ON secrets(name);
"""

# Canonical run / node statuses (API uses lowercase for backward compatibility).
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"
STATUS_RETRYING = "retrying"
STATUS_TIMED_OUT = "timed_out"

TERMINAL_STATUSES = frozenset(
    {STATUS_SUCCESS, STATUS_FAILED, STATUS_CANCELLED, STATUS_TIMED_OUT}
)


class Database:
    """Thread-safe SQLite handle. Schema is Postgres-portable (no SQLite-only types)."""

    def __init__(self, path: Path | str):
        self._raw = str(path)
        self.path = Path(path) if self._raw != ":memory:" else Path(":memory:")
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None

    @property
    def is_memory(self) -> bool:
        return self._raw == ":memory:"

    def ensure(self) -> None:
        with self._lock:
            if not self.is_memory:
                self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = self.connect()
            conn.executescript(SCHEMA_SQL)
            row = conn.execute(
                "SELECT value FROM schema_meta WHERE key = 'version'"
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO schema_meta(key, value) VALUES ('version', ?)",
                    (str(SCHEMA_VERSION),),
                )
            else:
                try:
                    current = int(row["value"])
                except (TypeError, ValueError):
                    current = 0
                if current < 2:
                    conn.executescript(_MIGRATE_V2_SQL)
                if current < SCHEMA_VERSION:
                    conn.execute(
                        "UPDATE schema_meta SET value = ? WHERE key = 'version'",
                        (str(SCHEMA_VERSION),),
                    )
            conn.commit()

    def connect(self) -> sqlite3.Connection:
        with self._lock:
            if self._conn is None:
                if not self.is_memory:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                conn = sqlite3.connect(
                    self._raw,
                    check_same_thread=False,
                    timeout=60.0,
                    isolation_level=None,  # autocommit; we manage transactions
                )
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA foreign_keys=ON")
                conn.execute("PRAGMA busy_timeout=60000")
                self._conn = conn
            return self._conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def execute(self, sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
        with self._lock:
            return self.connect().execute(sql, params)

    def executemany(self, sql: str, seq: list) -> sqlite3.Cursor:
        with self._lock:
            return self.connect().executemany(sql, seq)

    def executescript(self, script: str) -> None:
        with self._lock:
            self.connect().executescript(script)

    def commit(self) -> None:
        with self._lock:
            self.connect().commit()

    def begin_immediate(self) -> sqlite3.Connection:
        with self._lock:
            conn = self.connect()
            conn.execute("BEGIN IMMEDIATE")
            return conn
