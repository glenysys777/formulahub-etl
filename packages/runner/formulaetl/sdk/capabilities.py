"""Component capability flags used by the execution planner.

These are not decorative: ``engine.planner`` chooses ``batches`` vs
``materialized_rows`` vs ``artifact`` from this record. Default is the
legacy ``list[dict]`` path (blocking + full materialization).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

IoKind = Literal["rows", "artifact", "mixed"]


@dataclass(frozen=True)
class ComponentCapabilities:
    """How a component consumes and produces data.

    * streaming — can emit/consume incrementally (row or file stream)
    * blocking — needs the full input before any output (sort, agg, join, PGP)
    * supports_batch — runner may call ``run`` once per ``RowBatch``
    * requires_materialization — needs a complete ``list[dict]`` (legacy adapter)
    * io_kind — ``rows`` | ``artifact`` (files) | ``mixed`` (file in, rows out)
    """

    streaming: bool = False
    blocking: bool = True
    supports_batch: bool = False
    requires_materialization: bool = True
    io_kind: IoKind = "rows"

    def to_dict(self) -> dict[str, Any]:
        return {
            "streaming": self.streaming,
            "blocking": self.blocking,
            "supports_batch": self.supports_batch,
            "requires_materialization": self.requires_materialization,
            "io_kind": self.io_kind,
        }


# Conservative default: existing components keep working via list[dict].
LEGACY = ComponentCapabilities()

ROWWISE = ComponentCapabilities(
    streaming=True,
    blocking=False,
    supports_batch=True,
    requires_materialization=False,
    io_kind="rows",
)

BLOCKING_ROWS = ComponentCapabilities(
    streaming=False,
    blocking=True,
    supports_batch=False,
    requires_materialization=True,
    io_kind="rows",
)

ARTIFACT_SOURCE = ComponentCapabilities(
    streaming=True,
    blocking=False,
    supports_batch=False,
    requires_materialization=False,
    io_kind="artifact",
)

ARTIFACT_BLOCKING = ComponentCapabilities(
    streaming=False,
    blocking=True,
    supports_batch=False,
    requires_materialization=False,
    io_kind="artifact",
)

TABULAR_FROM_FILE = ComponentCapabilities(
    streaming=True,
    blocking=False,
    supports_batch=True,
    requires_materialization=False,
    io_kind="mixed",
)

# Destinations that append per RowBatch and do not echo the full row set.
STREAMING_SINK = ComponentCapabilities(
    streaming=True,
    blocking=False,
    supports_batch=True,
    requires_materialization=False,
    io_kind="rows",
)

# Stateful row-wise (e.g. dedupe keep=first): same component instance across batches.
STREAMING_STATEFUL = ComponentCapabilities(
    streaming=True,
    blocking=False,
    supports_batch=True,
    requires_materialization=False,
    io_kind="rows",
)
