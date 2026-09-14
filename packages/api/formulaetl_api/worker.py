"""Async run worker — claims queued jobs and executes PipelineRunner.

Can run as:
  - embedded daemon thread inside the API process (Community default)
  - standalone process: ``python -m formulaetl_api.worker``

No global run lock: concurrent claimed jobs execute independently.
"""

from __future__ import annotations

import os
import socket
import threading
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from formulaetl.engine.runner import PipelineRunner
from formulaetl_api.db import STATUS_FAILED, STATUS_RUNNING

if TYPE_CHECKING:
    from formulaetl_api.store import ConnectionStore, PipelineStore, RunStore


def default_worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"


class RunWorker:
    """Poll the durable job queue and execute claimed runs."""

    def __init__(
        self,
        runs: "RunStore",
        pipelines: "PipelineStore",
        *,
        work_dir: Path,
        demo_mode: bool = True,
        worker_id: str | None = None,
        poll_interval_sec: float = 0.25,
        max_concurrent: int = 4,
        connections: "ConnectionStore | None" = None,
        secret_provider: object | None = None,
    ):
        self.runs = runs
        self.pipelines = pipelines
        self.work_dir = Path(work_dir)
        self.demo_mode = demo_mode
        self.worker_id = worker_id or default_worker_id()
        self.poll_interval_sec = poll_interval_sec
        self.max_concurrent = max(1, int(max_concurrent))
        self.connections = connections
        self.secret_provider = secret_provider
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._inflight = 0
        self._inflight_lock = threading.Lock()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="formulaetl-worker", daemon=True
        )
        self._thread.start()

    def stop(self, *, join_timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=join_timeout)

    def run_forever(self) -> None:
        """Blocking loop for the standalone process."""
        self._stop.clear()
        self._loop()

    def tick_once(self) -> bool:
        """Claim and execute at most one job synchronously. Returns True if work done."""
        with self._inflight_lock:
            if self._inflight >= self.max_concurrent:
                return False
        claimed = self.runs.claim_next(self.worker_id)
        if claimed is None:
            return False
        self._execute_claimed(claimed.run_id, claimed.pipeline_version_id)
        return True

    def drain(self, *, max_jobs: int = 100, timeout_sec: float = 60.0) -> int:
        """Process queued jobs until empty or limits hit. Useful in tests."""
        done = 0
        deadline = time.time() + timeout_sec
        while done < max_jobs and time.time() < deadline:
            if not self.tick_once():
                if self.runs.queue_depth() == 0:
                    break
                time.sleep(self.poll_interval_sec)
                continue
            done += 1
        return done

    def _loop(self) -> None:
        while not self._stop.is_set():
            progressed = False
            with self._inflight_lock:
                slots = self.max_concurrent - self._inflight
            for _ in range(max(0, slots)):
                claimed = self.runs.claim_next(self.worker_id)
                if claimed is None:
                    break
                progressed = True
                t = threading.Thread(
                    target=self._run_claimed_guarded,
                    args=(claimed.run_id, claimed.pipeline_version_id),
                    name=f"formulaetl-run-{claimed.run_id[:8]}",
                    daemon=True,
                )
                with self._inflight_lock:
                    self._inflight += 1
                t.start()
            if not progressed:
                self._stop.wait(self.poll_interval_sec)

    def _run_claimed_guarded(self, run_id: str, pipeline_version_id: str) -> None:
        try:
            self._execute_claimed(run_id, pipeline_version_id)
        finally:
            with self._inflight_lock:
                self._inflight = max(0, self._inflight - 1)

    def _execute_claimed(self, run_id: str, pipeline_version_id: str) -> None:
        version = self.pipelines.get_version(pipeline_version_id)
        if version is None:
            self.runs.transition(
                run_id,
                STATUS_FAILED,
                message="Pipeline version missing",
                error=f"pipeline_version '{pipeline_version_id}' not found",
            )
            return
        pipeline = version.as_pipeline()
        try:
            get_connection = None
            secret_provider = self.secret_provider
            if self.connections is not None:
                get_connection = self.connections.get
                if secret_provider is None:
                    secret_provider = self.connections._provider()
            runner = PipelineRunner(
                work_dir=self.work_dir,
                demo_mode=self.demo_mode,
                secret_provider=secret_provider,
                get_connection=get_connection,
            )
            result = runner.run(pipeline, run_id=run_id)
            # Ensure status reflects runner outcome
            if result.status == STATUS_RUNNING:
                result.status = "success"
            self.runs.complete_from_result(result, pipeline_version_id)
        except Exception as exc:
            self.runs.transition(
                run_id,
                STATUS_FAILED,
                message="Worker exception",
                error=str(exc),
            )


def main() -> None:
    """CLI entry: ``python -m formulaetl_api.worker``."""
    import os
    from pathlib import Path

    from formulaetl_api.db import Database
    from formulaetl_api.store import PipelineStore, RunStore

    work_dir = Path(os.environ.get("FORMULAETL_WORK_DIR", Path.cwd())).resolve()
    db_path = Path(
        os.environ.get("FORMULAETL_DB_PATH", str(work_dir / "data" / "formulaetl.db"))
    )
    demo = os.environ.get("FORMULAETL_DEMO", "1") == "1"
    poll = float(os.environ.get("FORMULAETL_WORKER_POLL", "0.25"))
    max_c = int(os.environ.get("FORMULAETL_WORKER_CONCURRENCY", "4"))

    db = Database(db_path)
    db.ensure()
    pipelines = PipelineStore(db, legacy_json_root=work_dir / "data" / "pipelines")
    runs = RunStore(db)
    from formulaetl_api.store import ConnectionStore
    from formulaetl.sdk.secrets import CompositeSecretProvider, EnvSecretProvider

    connections = ConnectionStore(db, work_dir=work_dir, demo_mode=demo)
    pipelines.ensure()
    runs.ensure()
    connections.ensure()
    secret_provider = CompositeSecretProvider(EnvSecretProvider(), connections.secret_store)

    worker = RunWorker(
        runs,
        pipelines,
        work_dir=work_dir,
        demo_mode=demo,
        poll_interval_sec=poll,
        max_concurrent=max_c,
        connections=connections,
        secret_provider=secret_provider,
    )
    print(
        f"FormulaETL worker {worker.worker_id} starting "
        f"(db={db_path}, concurrency={max_c})",
        flush=True,
    )
    try:
        worker.run_forever()
    except KeyboardInterrupt:
        print("Worker stopping…", flush=True)
        worker.stop()


if __name__ == "__main__":
    main()
