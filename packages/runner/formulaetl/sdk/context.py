"""Runtime context and component result types."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from formulaetl.sdk.data import ArtifactHandle, DatasetHandle


@dataclass
class Metrics:
    rows_in: int = 0
    rows_out: int = 0
    rows_rejected: int = 0
    duration_ms: float = 0.0
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows_in": self.rows_in,
            "rows_out": self.rows_out,
            "rows_rejected": self.rows_rejected,
            "duration_ms": round(self.duration_ms, 2),
            **self.extras,
        }


@dataclass
class ComponentResult:
    rows: list[dict[str, Any]] = field(default_factory=list)
    rejects: list[dict[str, Any]] = field(default_factory=list)
    side_effects: dict[str, Any] = field(default_factory=dict)
    metrics: Metrics = field(default_factory=Metrics)
    artifacts: dict[str, Any] = field(default_factory=dict)
    # Optional parallel output streams keyed by port name
    streams: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    # Phase B handles (optional). Legacy components leave these None;
    # the runner wraps ``rows`` / ``artifacts["path"]`` via the adapter.
    dataset: DatasetHandle | None = None
    artifact: ArtifactHandle | None = None
    # Spill-backed named streams (fan-out without full list[dict] in RAM).
    stream_datasets: dict[str, "DatasetHandle"] = field(default_factory=dict)


LogFn = Callable[[str], None]


@dataclass
class RunContext:
    """Shared runtime context passed to every component."""

    run_id: str
    pipeline_id: str
    demo_mode: bool = True
    work_dir: Path = field(default_factory=lambda: Path("."))
    data_dir: Path = field(default_factory=lambda: Path("./data"))
    variables: dict[str, Any] = field(default_factory=dict)
    log: LogFn = field(default=lambda msg: print(msg))
    batch_size: int = 16384
    _node_metrics: dict[str, Metrics] = field(default_factory=dict)
    # Phase F: optional connection + secret resolution (set by PipelineRunner)
    secret_provider: Any | None = None
    get_connection: Callable[[str], Any] | None = None
    # Master / Child nesting (see docs/architecture/MASTER_CHILD_PIPELINES.md)
    pipeline_stack: list[str] = field(default_factory=list)
    parent_run_id: str | None = None
    master_node_id: str | None = None
    get_pipeline: Callable[[str], Any] | None = None
    record_child_run: Callable[..., Any] | None = None
    complete_child_run: Callable[..., Any] | None = None

    def temp_dir(self) -> Path:
        """Per-run scratch directory for ArtifactHandle temp files."""
        path = self.data_dir / "tmp" / self.run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def resolve(self, path: str | Path) -> Path:
        p = Path(path)
        if p.is_absolute():
            return p
        return (self.work_dir / p).resolve()

    def emit(self, message: str) -> None:
        from formulaetl.sdk.io_util import redact_secrets

        self.log(redact_secrets(message))

    def record_metrics(self, node_id: str, metrics: Metrics) -> None:
        self._node_metrics[node_id] = metrics

    def all_metrics(self) -> dict[str, dict[str, Any]]:
        return {k: v.to_dict() for k, v in self._node_metrics.items()}

    def resolve_config(
        self, node_config: dict[str, Any], *, component_type: str | None = None
    ) -> dict[str, Any]:
        """Merge ``connection_id`` + secret refs for a node (runtime only)."""
        from formulaetl.sdk.connections import resolve_node_config

        return resolve_node_config(
            node_config,
            component_type=component_type,
            get_connection=self.get_connection,
            provider=self.secret_provider,
        )

class timed:
    """Context manager that fills Metrics.duration_ms."""

    def __init__(self, metrics: Metrics):
        self.metrics = metrics
        self._start = 0.0

    def __enter__(self) -> Metrics:
        self._start = time.perf_counter()
        return self.metrics

    def __exit__(self, *args: object) -> None:
        self.metrics.duration_ms = (time.perf_counter() - self._start) * 1000
