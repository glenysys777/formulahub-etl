"""Execution planner: capabilities → feed mode for each DAG node.

Used by ``PipelineRunner`` (not dead metadata). Linear row-wise hops are
fed bounded ``RowBatch``es; blocking / fan-out nodes materialize
``list[dict]`` via the adapter; file hops use ``ArtifactHandle``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from formulaetl.models.pipeline import EdgeDefinition, PipelineDefinition
from formulaetl.sdk.capabilities import ComponentCapabilities, LEGACY
from formulaetl.sdk.data import DEFAULT_BATCH_SIZE
from formulaetl.sdk.registry import create_component

Feed = Literal["none", "artifact", "batches", "materialized_rows"]


@dataclass
class NodePlan:
    node_id: str
    component_type: str
    capabilities: ComponentCapabilities
    feed: Feed
    reason: str
    batch_size: int
    inbound: int
    outbound: int
    output_kind: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "component_type": self.component_type,
            "capabilities": self.capabilities.to_dict(),
            "feed": self.feed,
            "reason": self.reason,
            "batch_size": self.batch_size,
            "inbound": self.inbound,
            "outbound": self.outbound,
            "output_kind": self.output_kind,
        }


@dataclass
class ExecutionPlan:
    order: list[str]
    nodes: dict[str, NodePlan] = field(default_factory=dict)
    batch_size: int = DEFAULT_BATCH_SIZE

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_size": self.batch_size,
            "order": list(self.order),
            "nodes": {nid: p.to_dict() for nid, p in self.nodes.items()},
        }


def _output_kind(caps: ComponentCapabilities) -> str:
    return "artifact" if caps.io_kind == "artifact" else "rows"


def decide_feed(
    caps: ComponentCapabilities,
    *,
    inbound: int,
    outbound: int,
    upstream_kind: str | None,
) -> tuple[Feed, str]:
    if inbound == 0:
        return "none", "source produces its own output"

    if caps.io_kind == "artifact" or (
        caps.io_kind == "mixed" and upstream_kind == "artifact"
    ):
        return "artifact", f"file hop (io_kind={caps.io_kind}, upstream={upstream_kind})"

    if outbound > 1:
        return (
            "materialized_rows",
            "fan-out: output must be replayable for multiple edges",
        )

    if caps.requires_materialization:
        return "materialized_rows", "requires_materialization (legacy list[dict])"

    if caps.blocking or not caps.streaming:
        return "materialized_rows", "blocking / non-streaming component"

    if caps.supports_batch:
        return "batches", "row-wise streaming component; bounded RowBatch feed"

    return "materialized_rows", "no supports_batch; list[dict] adapter"


def plan_pipeline(
    pipeline: PipelineDefinition,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> ExecutionPlan:
    batch_size = max(1, int(batch_size or DEFAULT_BATCH_SIZE))
    order = pipeline.topological_order()
    node_map = pipeline.node_map()

    inbound_edges: dict[str, list[EdgeDefinition]] = {n.id: [] for n in pipeline.nodes}
    outbound_count: dict[str, int] = {n.id: 0 for n in pipeline.nodes}
    for edge in pipeline.edges:
        inbound_edges[edge.target].append(edge)
        outbound_count[edge.source] = outbound_count.get(edge.source, 0) + 1

    output_kind: dict[str, str] = {}
    nodes: dict[str, NodePlan] = {}

    for nid in order:
        node = node_map[nid]
        try:
            component = create_component(node.type, node.config)
            caps = component.get_capabilities()
        except Exception:
            caps = LEGACY

        incoming = inbound_edges[nid]
        upstream_kind: str | None = None
        if incoming:
            kinds = {output_kind.get(e.source, "rows") for e in incoming}
            if kinds == {"artifact"}:
                upstream_kind = "artifact"
            elif "artifact" in kinds and caps.io_kind in ("artifact", "mixed"):
                upstream_kind = "artifact"
            else:
                upstream_kind = "rows"

        feed, reason = decide_feed(
            caps,
            inbound=len(incoming),
            outbound=outbound_count.get(nid, 0),
            upstream_kind=upstream_kind,
        )
        out_kind = _output_kind(caps)
        output_kind[nid] = out_kind
        nodes[nid] = NodePlan(
            node_id=nid,
            component_type=node.type,
            capabilities=caps,
            feed=feed,
            reason=reason,
            batch_size=batch_size,
            inbound=len(incoming),
            outbound=outbound_count.get(nid, 0),
            output_kind=out_kind,
        )

    return ExecutionPlan(order=order, nodes=nodes, batch_size=batch_size)
