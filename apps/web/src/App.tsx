import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  MiniMap,
  BackgroundVariant,
  type Edge,
  type Node,
  type NodeTypes,
  useEdgesState,
  useNodesState,
  useReactFlow,
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
import { EtlNode, ComponentGlyph, categoryForType, CAT_COLORS, type EtlNodeData, type RunVisual } from "./EtlNode";
import { NodeInspector, missingRequiredKeys } from "./NodeInspector";
import { SchemaMapper } from "./SchemaMapper";

const DEMO_ID = "demo-api-kafka-databricks";
const DEFAULT_PROMPT =
  "Read orders from a Kafka topic, map fields, and trigger a Databricks notebook job.";

function isMapperType(t: string): boolean {
  return t === "column_map" || t === "tmap";
}

const PALETTE_ORDER = [
  "kafka_source",
  "s3_source",
  "http_api_source",
  "excel_source",
  "sftp_source",
  "local_file_source",
  "postgres_source",
  "mysql_source",
  "sqlite_source",
  "csv_parser",
  "json_parser",
  "xml_parser",
  "column_map",
  "tmap",
  "transform",
  "schema_validate",
  "filter",
  "sort",
  "aggregate",
  "dedupe",
  "lookup_join",
  "python_row",
  "pgp_decrypt",
  "pgp_encrypt",
  "databricks_job",
  "snowflake_destination",
  "local_file_destination",
  "excel_destination",
  "sftp_destination",
  "postgres_destination",
  "mysql_destination",
  "sqlite_destination",
  "archive_files",
  "logger_metrics",
];

function defaultConfigFor(type: string): Record<string, unknown> {
  if (type === "kafka_source")
    return {
      brokers: "demo",
      topic: "orders",
      group_id: "formulaetl",
      auto_offset_reset: "earliest",
      max_messages: 100,
      security: "plain",
      format: "json",
      demo: true,
    };
  if (type === "databricks_job")
    return {
      workspace_host: "demo",
      job_id: "1001",
      notebook_params: ["source=formulaetl"],
      wait_for_completion: true,
      demo: true,
    };
  if (type === "s3_source") return { bucket: "demo", key: "demo/orders_encrypted.csv.pgp" };
  if (type === "http_api_source")
    return { url: "https://api.example.com/v1/orders", method: "GET", json_path: "data.items", demo: true };
  if (type === "local_file_destination") return { path: "data/out/output.csv", format: "csv" };
  return {};
}


const CATEGORY_GROUP_ORDER = [
  "source",
  "stream",
  "file",
  "db",
  "transform",
  "quality",
  "security",
  "orch",
  "destination",
  "utility",
] as const;

const CATEGORY_GROUP_LABELS: Record<string, string> = {
  source: "Sources",
  stream: "Streams",
  file: "Files",
  db: "Databases",
  transform: "Transform",
  quality: "Quality",
  security: "Security",
  orch: "Orchestration",
  destination: "Destinations",
  utility: "Utility",
};

const DND_MIME = "application/formulaetl-component";

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

function AppCanvas() {
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
  const [scheduleEnabled, setScheduleEnabled] = useState(false);
  const [scheduleCron, setScheduleCron] = useState("*/5 * * * *");
  const [scheduleTz, setScheduleTz] = useState("UTC");
  const [scheduleInfo, setScheduleInfo] = useState<string | null>(null);
  const [scheduleBusy, setScheduleBusy] = useState(false);
  const persistTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const nodesRef = useRef(nodes);
  const edgesRef = useRef(edges);
  const pipelineRef = useRef(pipeline);
  const { screenToFlowPosition } = useReactFlow();

  nodesRef.current = nodes;
  edgesRef.current = edges;
  pipelineRef.current = pipeline;

  const componentByType = useMemo(() => {
    const map: Record<string, ComponentInfo> = {};
    for (const c of components) map[c.type] = c;
    return map;
  }, [components]);

  const paletteItems = useMemo(() => {
    const byType = new Map(components.map((c) => [c.type, c]));
    const ordered: ComponentInfo[] = [];
    for (const t of PALETTE_ORDER) {
      const c = byType.get(t);
      if (c) ordered.push(c);
    }
    for (const c of components) {
      if (!PALETTE_ORDER.includes(c.type)) ordered.push(c);
    }
    return ordered;
  }, [components]);

  const paletteGroups = useMemo(() => {
    const groups = new Map<string, ComponentInfo[]>();
    for (const c of paletteItems) {
      const cat = categoryForType(c.type);
      if (!groups.has(cat)) groups.set(cat, []);
      groups.get(cat)!.push(c);
    }
    const ordered: { id: string; label: string; items: ComponentInfo[] }[] = [];
    for (const id of CATEGORY_GROUP_ORDER) {
      const items = groups.get(id);
      if (items?.length) ordered.push({ id, label: CATEGORY_GROUP_LABELS[id] || id, items });
    }
    for (const [id, items] of groups) {
      if (!CATEGORY_GROUP_ORDER.includes(id as (typeof CATEGORY_GROUP_ORDER)[number])) {
        ordered.push({ id, label: CATEGORY_GROUP_LABELS[id] || id, items });
      }
    }
    return ordered;
  }, [paletteItems]);

  const loadPipeline = useCallback(
    async (p: Pipeline) => {
      setPipeline(p);
      const flow = toFlow(p);
      setNodes(flow.nodes);
      setEdges(flow.edges);
      setSelectedId(null);
      setRun(null);
      try {
        const sched = await api.getSchedule(p.id);
        setScheduleEnabled(Boolean(sched.enabled));
        setScheduleCron(sched.cron || "*/5 * * * *");
        setScheduleTz(sched.timezone || "UTC");
        setScheduleInfo(
          sched.enabled && sched.next_run_at
            ? `next_run_at: ${new Date(sched.next_run_at * 1000).toISOString()}`
            : sched.last_status
              ? `Last: ${sched.last_status}`
              : null,
        );
      } catch {
        setScheduleEnabled(false);
        setScheduleInfo(null);
      }
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

  const ensurePipeline = useCallback(async (): Promise<Pipeline> => {
    if (pipelineRef.current) return pipelineRef.current;
    const created = await api.createPipeline({
      name: "Untitled pipeline",
      description: "Built from the component palette (non-AI path)",
      nodes: [],
      edges: [],
      metadata: { created_via: "palette" },
    });
    await loadPipeline(created);
    return created;
  }, [loadPipeline]);

  const newBlankPipeline = useCallback(async () => {
    setError(null);
    setBusy(true);
    try {
      const created = await api.createPipeline({
        name: "Untitled pipeline",
        description: "Blank canvas — drag components from the palette",
        nodes: [],
        edges: [],
        metadata: { created_via: "blank" },
      });
      await loadPipeline(created);
      setMapperOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [loadPipeline]);

  const addComponentNode = useCallback(
    async (comp: ComponentInfo, position?: { x: number; y: number }) => {
      try {
        await ensurePipeline();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        return;
      }
      const id = `${comp.type.replace(/_/g, "")}-${Math.random().toString(36).slice(2, 7)}`;
      setNodes((nds) => {
        const x = position?.x ?? 80 + nds.length * 36;
        const y = position?.y ?? 120 + (nds.length % 4) * 40;
        const label =
          comp.type === "tmap" ? "Field Mapper" : comp.display_name || comp.type;
        const newNode: Node = {
          id,
          type: "etl",
          position: { x, y },
          data: {
            label,
            componentType: comp.type,
            config: defaultConfigFor(comp.type),
            runVisual: "idle",
          } satisfies EtlNodeData,
        };
        return [...nds, newNode];
      });
      setSelectedId(id);
      schedulePersist();
    },
    [ensurePipeline, setNodes, schedulePersist],
  );

  const onPaletteDragStart = (event: DragEvent, comp: ComponentInfo) => {
    event.dataTransfer.setData(DND_MIME, comp.type);
    event.dataTransfer.setData("text/plain", comp.type);
    event.dataTransfer.effectAllowed = "move";
  };

  const onCanvasDragOver = (event: DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  };

  const onCanvasDrop = async (event: DragEvent) => {
    event.preventDefault();
    const type = event.dataTransfer.getData(DND_MIME) || event.dataTransfer.getData("text/plain");
    if (!type) return;
    const comp = componentByType[type] || paletteItems.find((c) => c.type === type);
    if (!comp) return;
    const position = screenToFlowPosition({ x: event.clientX, y: event.clientY });
    await addComponentNode(comp, position);
  };

  const saveSchedule = async () => {
    if (!pipeline) return;
    setScheduleBusy(true);
    setError(null);
    try {
      const spec = await api.putSchedule(pipeline.id, {
        enabled: scheduleEnabled,
        cron: scheduleCron.trim() || "*/5 * * * *",
        timezone: scheduleTz.trim() || "UTC",
      });
      setScheduleInfo(
        spec.enabled && spec.next_run_at
          ? `next_run_at: ${new Date(spec.next_run_at * 1000).toISOString()}`
          : "Schedule saved (disabled)",
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setScheduleBusy(false);
    }
  };

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
      // Brief flowing animation, then poll until terminal (demo runs sync but stay resilient)
      await new Promise((r) => setTimeout(r, 450));
      let status = await api.getRun(run_id);
      for (let i = 0; i < 40 && (status.status === "pending" || status.status === "running"); i++) {
        await new Promise((r) => setTimeout(r, 150));
        status = await api.getRun(run_id);
      }
      setRun(status);
      applyRunVisuals(false, status);
      requestAnimationFrame(() => {
        document.querySelector(".logs-panel")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      });
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
            data-testid="new-blank"
            onClick={newBlankPipeline}
            disabled={busy}
            title="Start an empty pipeline and add components from the palette"
          >
            New blank
          </button>
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
        <aside className="palette" data-testid="component-palette" aria-label="Component palette">
          <h3>Components</h3>
          <p className="palette-hint">
            Drag onto the canvas or click to add. Primary non-AI build path.
          </p>
          <div className="palette-list">
            {paletteGroups.map((group) => (
              <div key={group.id} className="palette-group" data-testid={`palette-group-${group.id}`}>
                <div className="palette-group-label">{group.label}</div>
                {group.items.map((c) => {
                  const cat = categoryForType(c.type);
                  const label =
                    c.type === "tmap" ? "Field Mapper" : c.display_name || c.type;
                  return (
                    <button
                      key={c.type}
                      type="button"
                      className={`palette-item cat-${cat}`}
                      title={`${c.type} — drag or click to add`}
                      draggable={!busy}
                      data-testid={`palette-item-${c.type}`}
                      disabled={busy}
                      onDragStart={(e) => onPaletteDragStart(e, c)}
                      onClick={() => void addComponentNode(c)}
                    >
                      <span className="palette-icon">
                        <ComponentGlyph type={c.type} size={15} />
                      </span>
                      <span className="palette-label">{label}</span>
                    </button>
                  );
                })}
              </div>
            ))}
            {!paletteItems.length && (
              <p className="empty-hint">Connect API to load palette from /api/components.</p>
            )}
          </div>
        </aside>
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
            onDrop={(e) => void onCanvasDrop(e)}
            onDragOver={onCanvasDragOver}
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
                if (t.includes("databricks")) return CAT_COLORS.orch;
                if (t.includes("kafka")) return CAT_COLORS.stream;
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
              <p className="empty-hint">Use the palette, New blank, Load demo, or AI Build.</p>
            )}
          </div>

          <div className="sidebar-section">
            <h3>Schedule</h3>
            {pipeline ? (
              <div className="schedule-form" data-testid="schedule-form">
                <label className="schedule-row">
                  <input
                    type="checkbox"
                    checked={scheduleEnabled}
                    onChange={(e) => setScheduleEnabled(e.target.checked)}
                    data-testid="schedule-enabled"
                  />
                  <span>Enable schedule</span>
                </label>
                <label className="field-label">Cron expression</label>
                <input
                  className="schedule-input"
                  value={scheduleCron}
                  onChange={(e) => setScheduleCron(e.target.value)}
                  placeholder="*/5 * * * *"
                  data-testid="schedule-cron"
                />
                <label className="field-label">Timezone</label>
                <input
                  className="schedule-input"
                  value={scheduleTz}
                  onChange={(e) => setScheduleTz(e.target.value)}
                  placeholder="UTC"
                  data-testid="schedule-tz"
                />
                <button
                  type="button"
                  className="btn btn-sm"
                  disabled={scheduleBusy}
                  onClick={saveSchedule}
                  data-testid="schedule-save"
                >
                  {scheduleBusy ? "Saving…" : "Save schedule"}
                </button>
                {scheduleInfo && (
                  <p className="schedule-info" data-testid="schedule-next-run">
                    {scheduleInfo}
                  </p>
                )}
                <p className="schedule-note">
                  Community self-hosted scheduler. Cloud HA scheduling is a planned Enterprise lock.
                </p>
              </div>
            ) : (
              <p className="empty-hint">Open a pipeline (palette / blank / demo) to schedule runs.</p>
            )}
          </div>

          <div className="sidebar-section" data-testid="last-run-panel">
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

          <div className="sidebar-section logs-panel" data-testid="logs-panel">
            <h3>Logs</h3>
            <div className="logs" data-testid="run-logs">
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
                    <p className="mapper-hint">
                      Double-click the node — large Input · Variables · Output mapper. For merging two
                      sources first, use Lookup Join.
                    </p>
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

export default function App() {
  return (
    <ReactFlowProvider>
      <AppCanvas />
    </ReactFlowProvider>
  );
}
