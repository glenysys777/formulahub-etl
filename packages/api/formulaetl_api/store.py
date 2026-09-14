"""In-memory / file-backed stores for pipelines and runs."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from formulaetl.engine.runner import RunResult
from formulaetl.models.pipeline import PipelineDefinition


class PipelineStore:
    def __init__(self, root: Path):
        self.root = root
        self._lock = threading.Lock()

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, pid: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in pid)
        return self.root / f"{safe}.json"

    def save(self, pipeline: PipelineDefinition) -> None:
        self.ensure()
        with self._lock:
            self._path(pipeline.id).write_text(
                pipeline.model_dump_json(indent=2), encoding="utf-8"
            )

    def get(self, pid: str) -> PipelineDefinition | None:
        path = self._path(pid)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return PipelineDefinition.model_validate(data)

    def list(self) -> list[PipelineDefinition]:
        self.ensure()
        out: list[PipelineDefinition] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                out.append(PipelineDefinition.model_validate(data))
            except Exception:
                continue
        return out

    def delete(self, pid: str) -> bool:
        path = self._path(pid)
        if path.exists():
            path.unlink()
            return True
        return False


class RunStore:
    """In-process run history. Lost on restart — not a production run ledger."""

    def __init__(self) -> None:
        self._runs: dict[str, RunResult] = {}
        self._lock = threading.Lock()

    def put(self, result: RunResult) -> None:
        with self._lock:
            self._runs[result.run_id] = result

    def update(self, result: RunResult) -> None:
        with self._lock:
            self._runs[result.run_id] = result

    def get(self, run_id: str) -> RunResult | None:
        with self._lock:
            return self._runs.get(run_id)

    def list(self) -> list[RunResult]:
        with self._lock:
            return list(self._runs.values())
