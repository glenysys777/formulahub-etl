import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  BackgroundVariant,
  type Edge,
  type Node,
  type NodeTypes,
  useEdgesState,
  useNodesState,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import {
  api,
  API_BASE,
  type ComponentInfo,
  type Pipeline,
  type PipelineEdge,
  type PipelineNode,
  type RunStatus,
} from "./api";
import { EtlNode, type EtlNodeData, type RunVisual } from "./EtlNode";
import { NodeInspector, missingRequiredKeys } from "./NodeInspector";
import { SchemaMapper } from "./SchemaMapper";

const DEMO_ID = "demo-core-path";
const DEFAULT_PROMPT =
  "Read encrypted files from S3, decrypt using PGP, validate these 17 columns, reject invalid records, transform dates, load good records into Snowflake and archive processed files.";

function isMapperType(t: string): boolean {
  return t === "column_map" || t === "tmap";
}

const nodeTypes: NodeTypes = { etl: EtlNode };

function toFlow(
  pipeline: Pipeline,
  opts?: { running?: boolean; run?: RunStatus | null },
): { nodes: Node[]; edges: Edge[] } {
  const running = Boolean(opts?.running);
  const run = opts?.run;
  const nodeMetrics = run?.node_metrics || {};
  const rejected = Number(run?.metrics?.rows_rejected || 0) > 0;
  const status = run?.status;

  const nodes: Node[] = pipeline.nodes.map((n) => {
    let runVisual: RunVisual = "idle";
    if (running) {
      runVisual = "running";
    } else if (status === "success") {
      runVisual =
        rejected && (n.type === "schema_validate" || n.id === "rejects")
          ? "reject"
          : "success";
    } else if (status === "failed") {
      runVisual = nodeMetrics[n.id] ? "success" : "error";
    }
    return {
      id: n.id,
      type: "etl",
      position: n.position || { x: 0, y: 0 },
      data: {
        label: n.label || n.type,
        componentType: n.type,
        config: n.config || {},
        runVisual,
      } satisfies EtlNodeData,
    };
  });
  const edges: Edge[] = pipeline.edges.map((e) => {
    const isReject = e.sourceHandle === "rejects";
    const flowing = running;
    const classes = [
      isReject ? "edge-reject" : "edge-success",
      flowing ? "edge-flowing" : "",
      !flowing && status === "success" && !isReject ? "edge-done" : "",
      !flowing && isReject && rejected ? "edge-reject-pulse" : "",
    ]
      .filter(Boolean)
      .join(" ");
    return {
      id: e.id,
      source: e.source,
      target: e.target,
      sourceHandle: e.sourceHandle || "out",
      targetHandle: e.targetHandle || undefined,
      animated: flowing,
      className: classes,
      style: {
        stroke: isReject ? "#ff8a9b" : flowing ? "#0071e3" : "#c7c7cc",
        strokeWidth: flowing ? 2.25 : 1.75,
      },
    };
  });
  return { nodes, edges };
}

function fromFlow(pipeline: Pipeline, nodes: Node[], edges: Edge[]): Pipeline {
  return {
    ...pipeline,
    nodes: nodes.map((n) => {
      const d = n.data as EtlNodeData;
      return {
        id: n.id,
        type: d.componentType,
        label: d.label,
        config: d.config,
        position: n.position,
      };
    }),
    edges: edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      sourceHandle: e.sourceHandle,
      targetHandle: e.targetHandle,
    })),
  };
}

export default function App() {
  const [pipeline, setPipeline] = useState<Pipeline | null>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [prompt, setPrompt] = useState(DEFAULT_PROMPT);
  const [run, setRun] = useState<RunStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [apiOk, setApiOk] = useState(false);
  const [components, setComponents] = useState<ComponentInfo[]>([]);
  const [mapperOpen, setMapperOpen] = useState(false);
  const [discoverBusy, setDiscoverBusy] = useState(false);
  const [discoverMsg, setDiscoverMsg] = useState<string | null>(null);
  const persistTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const nodesRef = useRef(nodes);
  const edgesRef = useRef(edges);
  const pipelineRef = useRef(pipeline);

  nodesRef.current = nodes;
  edgesRef.current = edges;
  pipelineRef.current = pipeline;

  const componentByType = useMemo(() => {
    const map: Record<string, ComponentInfo> = {};
    for (const c of components) map[c.type] = c;
    return map;
  }, [components]);

  const loadPipeline = useCallback(
    async (p: Pipeline) => {
      setPipeline(p);
      const flow = toFlow(p);
      setNodes(flow.nodes);
      setEdges(flow.edges);
      setSelectedId(null);
      setRun(null);
    },
    [setNodes, setEdges],
  );

  /** Sync canvas run visuals when busy/run changes without wiping selection. */
  const applyRunVisuals = useCallback(
    (running: boolean, runStatus: RunStatus | null) => {
      const p = pipelineRef.current;
      if (!p) return;
      const base = fromFlow(p, nodesRef.current, edgesRef.current);
      const flow = toFlow(base, { running, run: runStatus });
      setNodes((nds) =>
        nds.map((n) => {
          const fresh = flow.nodes.find((x) => x.id === n.id);
          if (!fresh) return n;
          const d = n.data as EtlNodeData;
          const fd = fresh.data as EtlNodeData;
          return { ...n, data: { ...d, runVisual: fd.runVisual } };
        }),
      );
      setEdges((eds) =>
        eds.map((e) => {
          const fresh = flow.edges.find((x) => x.id === e.id);
          if (!fresh) return e;
          return {
            ...e,
            animated: fresh.animated,
            className: fresh.className,
            style: fresh.style,
          };
        }),
      );
    },
    [setNodes, setEdges],
  );

  const loadDemo = useCallback(async () => {
    setError(null);
    setBusy(true);
    try {
      const p = await api.getPipeline(DEMO_ID);
      await loadPipeline(p);
      // Default demo: select Field Mapper and open with many arrows visible
      const mapper =
        p.nodes.find((n) => n.id === "field_mapper") ||
        p.nodes.find((n) => isMapperType(n.type));
      if (mapper) {
        setSelectedId(mapper.id);
        setMapperOpen(true);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [loadPipeline]);

  useEffect(() => {
    api
      .health()
      .then(async () => {
        setApiOk(true);
        try {
          const comps = await api.listComponents();
          setComponents(comps);
        } catch {
          /* non-fatal */
        }
        return loadDemo();
      })
      .catch(() => {
        setApiOk(false);
        setError(`API unreachable at ${API_BASE}. Start with: make api`);
      });
  }, [loadDemo]);

  const selected = useMemo(
    () => nodes.find((n) => n.id === selectedId) || null,
    [nodes, selectedId],
  );

  const schedulePersist = useCallback(() => {
    if (persistTimer.current) clearTimeout(persistTimer.current);
    persistTimer.current = setTimeout(async () => {
      const p = pipelineRef.current;
      if (!p) return;
      try {
        const updated = fromFlow(p, nodesRef.current, edgesRef.current);
        await api.updatePipeline(p.id, updated);
        setPipeline(updated);
      } catch {
        /* keep UI edits even if persist fails */
      }
    }, 600);
  }, []);

  const onAIBuild = async () => {
    if (!prompt.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const p = await api.aiBuild(prompt.trim());
      await loadPipeline(p);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const collectMissingAcrossPipeline = useCallback(() => {
    const issues: string[] = [];
    for (const n of nodes) {
      const d = n.data as EtlNodeData;
      const comp = componentByType[d.componentType];
      if (!comp?.parameters?.length) continue;
      const missing = missingRequiredKeys(d.config || {}, comp.parameters);
      if (missing.length) {
        issues.push(`${d.label || n.id}: ${missing.join(", ")}`);
      }
    }
    return issues;
  }, [nodes, componentByType]);

  const onRun = async () => {
    if (!pipeline) return;
    const issues = collectMissingAcrossPipeline();
    if (issues.length) {
      const proceed = window.confirm(
        `Some required parameters are missing:\n\n${issues.join("\n")}\n\nRun anyway?`,
      );
      if (!proceed) return;
    }
    setBusy(true);
    setError(null);
    setRun(null);
    applyRunVisuals(true, null);
    try {
      // Persist current canvas graph before run
      const updated = fromFlow(pipeline, nodes, edges);
      await api.updatePipeline(pipeline.id, updated);
      setPipeline(updated);
      const { run_id } = await api.runPipeline(pipeline.id);
      // Brief flowing animation even if the API returns instantly
      await new Promise((r) => setTimeout(r, 700));
      const status = await api.getRun(run_id);
      setRun(status);
      applyRunVisuals(false, status);
      if (status.status === "failed") {
        setError(status.error || "Pipeline run failed");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      applyRunVisuals(false, null);
    } finally {
      setBusy(false);
    }
  };

  const updateSelectedConfig = (key: string, value: unknown) => {
    if (!selected) return;
    setNodes((nds) =>
      nds.map((n) => {
        if (n.id !== selected.id) return n;
        const d = n.data as EtlNodeData;
        return {
          ...n,
          data: {
            ...d,
            config: { ...d.config, [key]: value },
          },
        };
      }),
    );
    schedulePersist();
  };

  const replaceSelectedConfig = (config: Record<string, unknown>) => {
    if (!selected) return;
    setNodes((nds) =>
      nds.map((n) => {
        if (n.id !== selected.id) return n;
        const d = n.data as EtlNodeData;
        return {
          ...n,
          data: {
            ...d,
            config,
          },
        };
      }),
    );
    schedulePersist();
  };

  const metrics = run?.metrics || {};
  const selectedData = selected ? (selected.data as EtlNodeData) : null;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">
            FormulaHub <span>ETL</span>
          </div>
          <div className="brand-tag">visual pipelines</div>
        </div>
        <div className="topbar-actions">
          <button
            type="button"
            className="btn"
            data-testid="load-demo"
            onClick={loadDemo}
            disabled={busy}
          >
            Load demo
          </button>
          <button
            type="button"
            className="btn btn-run"
            data-testid="run-pipeline"
            onClick={onRun}
            disabled={busy || !pipeline}
            title={pipeline ? "Run the current pipeline" : "Load a pipeline first"}
          >
            {busy ? "Working…" : "Run pipeline"}
          </button>
        </div>
      </header>

      {error && <div className="error-banner">{error}</div>}

      <div className="main">
        <div className={`canvas-wrap${busy ? " is-running" : ""}${!busy && run?.status === "success" ? " run-success" : ""}${!busy && run?.status === "failed" ? " run-failed" : ""}`}>
          <div className="ai-bar">
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="Describe your pipeline in English…"
              rows={2}
            />
            <button
              type="button"
              className="btn btn-primary"
              data-testid="ai-build"
              onClick={onAIBuild}
              disabled={busy || !prompt.trim()}
            >
              AI Build
            </button>
          </div>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            nodeTypes={nodeTypes}
            fitView
            onNodeClick={(_, n) => { setSelectedId(n.id); setDiscoverMsg(null); setMapperOpen(false); }}
            onNodeDoubleClick={(_, n) => {
              setSelectedId(n.id);
              setDiscoverMsg(null);
              const d = n.data as EtlNodeData;
              if (isMapperType(d.componentType)) setMapperOpen(true);
            }}
            onPaneClick={() => { setSelectedId(null); setDiscoverMsg(null); setMapperOpen(false); }}
            proOptions={{ hideAttribution: true }}
          >
            <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="#d2d2d7" />
            <Controls />
            <MiniMap
              nodeColor={(n) => {
                const t = (n.data as { componentType?: string })?.componentType || "";
                if (t.includes("pgp")) return "#9333ea";
                if (t.includes("schema_validate")) return "#eab308";
                if (t.includes("snowflake") || t.includes("postgres") || t.includes("mysql") || t.includes("sqlite")) return "#4f46e5";
                if (t.includes("file") || t.includes("excel") || t.includes("archive")) return "#0d9488";
                if (t.includes("destination") || t.includes("sftp_destination")) return "#16a34a";
                if (t.includes("source") || t.includes("s3") || t.includes("http") || t.includes("sftp_source")) return "#2563eb";
                return "#f59e0b";
              }}
              maskColor="rgba(245,245,247,0.78)"
              style={{ background: "#ffffff", border: "1px solid #d2d2d7" }}
            />
          </ReactFlow>
        </div>

        <aside className="sidebar">
          <div className="sidebar-section">
            <h3>Pipeline</h3>
            {pipeline ? (
              <>
                <p className="pipeline-title">{pipeline.name}</p>
                <p className="pipeline-desc">{pipeline.description || "No description"}</p>
              </>
            ) : (
              <p className="empty-hint">Load the demo or generate with AI.</p>
            )}
          </div>

          <div className="sidebar-section">
            <h3>Last run</h3>
            {run ? (
              <>
                <div style={{ marginBottom: "0.6rem" }}>
                  <span className={`status-pill ${run.status}`}>{run.status}</span>
                  <span style={{ marginLeft: 8, fontSize: "0.72rem", color: "var(--text-muted)" }}>
                    {run.duration_ms != null ? `${Math.round(run.duration_ms)} ms` : ""}
                  </span>
                </div>
                <div className="metrics-grid">
                  <div className="metric">
                    <div className="metric-label">Rows in</div>
                    <div className="metric-value accent">{metrics.rows_in ?? "—"}</div>
                  </div>
                  <div className="metric">
                    <div className="metric-label">Rows out</div>
                    <div className="metric-value ok">{metrics.rows_out ?? "—"}</div>
                  </div>
                  <div className="metric">
                    <div className="metric-label">Rejected</div>
                    <div className="metric-value warn">{metrics.rows_rejected ?? "—"}</div>
                  </div>
                  <div className="metric">
                    <div className="metric-label">Duration</div>
                    <div className="metric-value">
                      {run.duration_ms != null ? `${Math.round(run.duration_ms)}` : "—"}
                    </div>
                  </div>
                </div>
              </>
            ) : (
              <p className="empty-hint">Run the pipeline to see metrics.</p>
            )}
          </div>

          <div className="sidebar-section inspector-section">
            <h3>Node inspector</h3>
            {selected && selectedData ? (
              <>
                {isMapperType(selectedData.componentType) && (
                  <div className="inspector-actions">
                    <button
                      type="button"
                      className="btn btn-primary btn-open-mapper"
                      data-testid="open-schema-mapper"
                      title="Map source columns to targets"
                      onClick={() => setMapperOpen(true)}
                    >
                      Open Field Mapper
                    </button>
                    <p className="mapper-hint">Double-click the node on the canvas, or use this button.</p>
                  </div>
                )}
                {(selectedData.componentType.endsWith("_source") ||
                  selectedData.componentType === "csv_parser") && (
                  <div className="inspector-actions">
                    <button
                      type="button"
                      className="btn btn-sm"
                      data-testid="discover-schema"
                      disabled={discoverBusy}
                      onClick={async () => {
                        setDiscoverBusy(true);
                        setDiscoverMsg(null);
                        setError(null);
                        try {
                          const result = await api.discoverSchema(
                            selectedData.componentType,
                            selectedData.config || {},
                          );
                          replaceSelectedConfig({
                            ...(selectedData.config || {}),
                            discovered_schema: result,
                          });
                          const names = result.columns.map((c) => c.name).join(", ");
                          setDiscoverMsg(
                            `Schema: ${result.columns.length} cols — ${names.slice(0, 120)}${names.length > 120 ? "…" : ""}`,
                          );
                        } catch (e) {
                          setError(e instanceof Error ? e.message : String(e));
                        } finally {
                          setDiscoverBusy(false);
                        }
                      }}
                    >
                      {discoverBusy ? "Discovering…" : "Discover schema"}
                    </button>
                    {discoverMsg && (
                      <p className="discover-msg" data-testid="discover-msg">
                        {discoverMsg}
                      </p>
                    )}
                  </div>
                )}
                <NodeInspector
                  nodeId={selected.id}
                  componentType={selectedData.componentType}
                  label={selectedData.label}
                  config={selectedData.config || {}}
                  component={componentByType[selectedData.componentType]}
                  onChange={updateSelectedConfig}
                  onConfigReplace={replaceSelectedConfig}
                />
              </>
            ) : (
              <p className="empty-hint">Select a node on the canvas.</p>
            )}
          </div>

          <div className="sidebar-section logs-panel">
            <h3>Logs</h3>
            <div className="logs">
              {run?.logs?.length
                ? run.logs.map((line, i) => (
                    <div
                      key={i}
                      className={
                        line.includes("FAILED")
                          ? "err"
                          : line.includes("successfully") || line.includes("✓")
                            ? "ok-line"
                            : undefined
                      }
                    >
                      {line}
                    </div>
                  ))
                : "No logs yet."}
            </div>
          </div>
        </aside>
      </div>


      {mapperOpen && selected && selectedData && pipeline && (
        <SchemaMapper
          open={mapperOpen}
          onClose={() => setMapperOpen(false)}
          componentType={selectedData.componentType}
          nodeId={selected.id}
          config={selectedData.config || {}}
          nodes={fromFlow(pipeline, nodes, edges).nodes as PipelineNode[]}
          edges={fromFlow(pipeline, nodes, edges).edges as PipelineEdge[]}
          onApply={(cfg) => {
            replaceSelectedConfig(cfg);
            setMapperOpen(false);
          }}
        />
      )}

      <footer className="footer">
        <span>FormulaHub ETL · Apache-2.0 · demo mode {apiOk ? "on" : "api offline"}</span>
        <span>{API_BASE}</span>
      </footer>
    </div>
  );
}
