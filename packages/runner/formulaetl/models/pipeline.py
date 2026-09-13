"""Pipeline definition models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class NodeDefinition(BaseModel):
    id: str
    type: str
    label: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    position: dict[str, float] = Field(default_factory=lambda: {"x": 0, "y": 0})


class EdgeDefinition(BaseModel):
    id: str
    source: str
    target: str
    sourceHandle: str | None = None
    targetHandle: str | None = None


class PipelineDefinition(BaseModel):
    id: str
    name: str
    description: str = ""
    version: str = "1.0"
    nodes: list[NodeDefinition] = Field(default_factory=list)
    edges: list[EdgeDefinition] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def node_map(self) -> dict[str, NodeDefinition]:
        return {n.id: n for n in self.nodes}

    def topological_order(self) -> list[str]:
        """Return node ids in dependency order (sources first)."""
        indegree: dict[str, int] = {n.id: 0 for n in self.nodes}
        children: dict[str, list[str]] = {n.id: [] for n in self.nodes}
        for e in self.edges:
            if e.source not in indegree or e.target not in indegree:
                raise ValueError(f"Edge {e.id} references unknown node")
            indegree[e.target] += 1
            children[e.source].append(e.target)

        queue = [nid for nid, d in indegree.items() if d == 0]
        order: list[str] = []
        while queue:
            # Stable: sort for determinism
            queue.sort()
            nid = queue.pop(0)
            order.append(nid)
            for child in children[nid]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    queue.append(child)

        if len(order) != len(self.nodes):
            raise ValueError("Pipeline DAG has a cycle")
        return order
