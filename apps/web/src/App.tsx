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
  type HealthInfo,
  type Pipeline,
  type PipelineEdge,
  type PipelineNode,
  type RunStatus,
  type ValidateResult,
} from "./api";
import { EtlNode, ComponentGlyph, categoryForType, CAT_COLORS, isMapperType, isLookupType, type EtlNodeData, type RunVisual } from "./EtlNode";
import { NodeInspector, missingRequiredKeys } from "./NodeInspector";
import { SchemaMapper } from "./SchemaMapper";
import { QuickAddPalette } from "./QuickAddPalette";
import { StudioNodeActionsContext, type StudioNodeActions } from "./studioActions";
import { JobContextsPanel } from "./JobContextsPanel";
import { parseContexts } from "./vars";
import {
  DEFAULT_MY_PIPELINES,
  WorkspacePanel,
  type WorkspaceState,
} from "./WorkspacePanel";

const DEMO_ID = "demo-api-kafka-databricks";
const DEFAULT_PROMPT =
  "Read orders from a Kafka topic, map fields, and trigger a Databricks notebook job.";
const SIDEBAR_COLLAPSE_KEY = "formulaetl.studio.sidebarCollapsed";
const WORKSPACE_FOCUS_KEY = "formulaetl.studio.workspaceFocus";

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
  "databricks_sql",
  "run_pipeline",
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
      notebook_params: ["source=formulaetl", "env=${context.env}"],
      wait_for_completion: true,
      demo: true,
    };
  if (type === "databricks_sql")
    return {
      workspace_host: "demo",
      warehouse_id: "demo-warehouse",
      sql: "SELECT * FROM orders WHERE dt = '${run_date}' AND env = '${context.env}'",
      wait_for_completion: true,
      demo: true,
    };
  if (type === "run_pipeline")
    return {
      pipeline_id: "",
      context_mode: "inherit",
      context_name: "",
      run_params: {},
      publish_as: "",
      on_failure: "fail_master",
      pass_rows: false,
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
      // Only pulse a few spine nodes — animating every node freezes large graphs.
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
  const edges: Edge[] = pipeline.edges.map((e, idx) => {
    const isReject = e.sourceHandle === "rejects";
    // Cap CSS flow animations — RF animated + CSS on every edge is expensive at 50+.
    const flowing = running && idx < 8 && !isReject;
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
      animated: false,
      className: classes,
      style: {
        stroke: isReject ? "#ff8a9b" : flowing || running ? "#0071e3" : "#c7c7cc",
        strokeWidth: flowing || running ? 2.25 : 1.75,
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
  const [validateResult, setValidateResult] = useState<ValidateResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [apiOk, setApiOk] = useState(false);
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [components, setComponents] = useState<ComponentInfo[]>([]);
  const [mapperOpen, setMapperOpen] = useState(false);
  const [inspectorFocus, setInspectorFocus] = useState<"inspector" | "join" | null>(null);
  const [discoverBusy, setDiscoverBusy] = useState(false);
  const [discoverMsg, setDiscoverMsg] = useState<string | null>(null);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const [saveBusy, setSaveBusy] = useState(false);
  const [scheduleEnabled, setScheduleEnabled] = useState(false);
  const [scheduleCron, setScheduleCron] = useState("*/5 * * * *");
  const [scheduleTz, setScheduleTz] = useState("UTC");
  const [scheduleInfo, setScheduleInfo] = useState<string | null>(null);
  const [scheduleBusy, setScheduleBusy] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try {
      return localStorage.getItem(SIDEBAR_COLLAPSE_KEY) === "1";
    } catch {
      return false;
    }
  });
  /** Secondary rail panels — collapsed by default so Node Inspector stays visible. */
  const [railOpen, setRailOpen] = useState<{
    pipeline: boolean;
    contexts: boolean;
    schedule: boolean;
    lastRun: boolean;
    logs: boolean;
    validate: boolean;
  }>({
    pipeline: false,
    contexts: false,
    schedule: false,
    lastRun: false,
    logs: false,
    validate: false,
  });
  const [fileMenuOpen, setFileMenuOpen] = useState(false);
  const fileMenuRef = useRef<HTMLDetailsElement | null>(null);
  const [quickAddOpen, setQuickAddOpen] = useState(false);
  const [quickAddQuery, setQuickAddQuery] = useState("");
  const [canvasFocused, setCanvasFocused] = useState(false);
  const [workspace, setWorkspace] = useState<WorkspaceState | null>(null);
  const [workspacePipelines, setWorkspacePipelines] = useState<Pipeline[]>([]);
  const [selectedFolder, setSelectedFolder] = useState<string>(DEFAULT_MY_PIPELINES);
  const workspacePanelRef = useRef<HTMLDivElement | null>(null);
  const persistTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const nodesRef = useRef(nodes);
  const edgesRef = useRef(edges);
  const pipelineRef = useRef(pipeline);
  const selectedIdRef = useRef(selectedId);
  const mapperOpenRef = useRef(mapperOpen);
  const keepMapperOpenRef = useRef(false);
  const quickAddOpenRef = useRef(quickAddOpen);
  const canvasFocusedRef = useRef(canvasFocused);
  const pointerFlowPos = useRef<{ x: number; y: number } | null>(null);
  const { screenToFlowPosition } = useReactFlow();

  nodesRef.current = nodes;
  edgesRef.current = edges;
  pipelineRef.current = pipeline;
  selectedIdRef.current = selectedId;
  mapperOpenRef.current = mapperOpen;
  quickAddOpenRef.current = quickAddOpen;
  canvasFocusedRef.current = canvasFocused;

  const toggleSidebar = useCallback(() => {
    setSidebarCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(SIDEBAR_COLLAPSE_KEY, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);

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
      setInspectorFocus(null);
      setRun(null);
      const hasContexts = Object.keys(parseContexts(p.metadata).sets).length > 0;
      setRailOpen((r) => ({ ...r, contexts: hasContexts }));
      const folder =
        typeof p.metadata?.workspace_folder === "string" && p.metadata.workspace_folder.trim()
          ? String(p.metadata.workspace_folder).trim()
          : null;
      if (folder) setSelectedFolder(folder);
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

  const refreshWorkspace = useCallback(async () => {
    try {
      const [ws, list] = await Promise.all([api.getWorkspace(), api.listPipelines()]);
      setWorkspace(ws);
      setWorkspacePipelines(list);
    } catch {
      /* non-fatal — tree refreshes on next open/create */
    }
  }, []);

  const openFromWorkspace = useCallback(
    async (pipelineId: string) => {
      setError(null);
      setBusy(true);
      try {
        const p = await api.getPipeline(pipelineId);
        await loadPipeline(p);
        setMapperOpen(false);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy(false);
      }
    },
    [loadPipeline],
  );

  const focusWorkspacePanel = useCallback(() => {
    try {
      sessionStorage.setItem(WORKSPACE_FOCUS_KEY, "1");
    } catch {
      /* ignore */
    }
    const wrap = workspacePanelRef.current;
    const el =
      (wrap?.querySelector(".workspace-panel") as HTMLElement | null) ||
      (document.querySelector('[data-testid="workspace-panel"]') as HTMLElement | null);
    el?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    el?.classList.add("workspace-flash");
    window.setTimeout(() => el?.classList.remove("workspace-flash"), 1200);
  }, []);

  const moveWorkspacePipeline = useCallback(
    async (pipelineId: string, folder: string) => {
      setError(null);
      try {
        const res = await api.movePipelineFolder(pipelineId, folder);
        setWorkspace(res.workspace);
        setWorkspacePipelines((prev) =>
          prev.map((p) => (p.id === pipelineId ? { ...p, ...res.pipeline } : p)),
        );
        if (pipelineRef.current?.id === pipelineId) {
          setPipeline((cur) =>
            cur
              ? {
                  ...cur,
                  metadata: {
                    ...(cur.metadata || {}),
                    ...(res.pipeline.metadata || {}),
                  },
                }
              : cur,
          );
        }
        setSelectedFolder(folder);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [],
  );

  /** Sync canvas run visuals when busy/run changes without wiping selection. */
  const applyRunVisuals = useCallback(
    (running: boolean, runStatus: RunStatus | null) => {
      const p = pipelineRef.current;
      if (!p) return;
      const base = fromFlow(p, nodesRef.current, edgesRef.current);
      const flow = toFlow(base, { running, run: runStatus });
      const freshNodes = new Map(flow.nodes.map((x) => [x.id, x]));
      const freshEdges = new Map(flow.edges.map((x) => [x.id, x]));
      setNodes((nds) =>
        nds.map((n) => {
          const fresh = freshNodes.get(n.id);
          if (!fresh) return n;
          const d = n.data as EtlNodeData;
          const fd = fresh.data as EtlNodeData;
          if (d.runVisual === fd.runVisual) return n;
          return { ...n, data: { ...d, runVisual: fd.runVisual } };
        }),
      );
      setEdges((eds) =>
        eds.map((e) => {
          const fresh = freshEdges.get(e.id);
          if (!fresh) return e;
          if (
            e.animated === fresh.animated &&
            e.className === fresh.className &&
            e.style === fresh.style
          ) {
            return e;
          }
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
      // Select Field Mapper so inspector/actions are ready — do not auto-open overlay
      // (founder audit: overlay blocked header/canvas until Close/Escape).
      const mapper =
        p.nodes.find((n) => n.id === "field_mapper") ||
        p.nodes.find((n) => isMapperType(n.type));
      if (mapper) {
        selectedIdRef.current = mapper.id;
        setSelectedId(mapper.id);
        setMapperOpen(false);
        setInspectorFocus("inspector");
        setSidebarCollapsed((prev) => {
          if (!prev) return prev;
          try {
            localStorage.setItem(SIDEBAR_COLLAPSE_KEY, "0");
          } catch {
            /* ignore */
          }
          return false;
        });
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
      .then(async (h) => {
        setApiOk(true);
        setHealth(h);
        try {
          const comps = await api.listComponents();
          setComponents(comps);
        } catch {
          /* non-fatal */
        }
        await refreshWorkspace();
        return loadDemo();
      })
      .catch(() => {
        setApiOk(false);
        setHealth(null);
        setError(`API unreachable at ${API_BASE}. Start with: make api`);
      });
  }, [loadDemo, refreshWorkspace]);

  useEffect(() => {
    if (!fileMenuOpen) return;
    const onDoc = (e: MouseEvent) => {
      const el = fileMenuRef.current;
      if (el && !el.contains(e.target as HTMLElement)) setFileMenuOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setFileMenuOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [fileMenuOpen]);

  useEffect(() => {
    if (validateResult) {
      setRailOpen((r) => ({ ...r, validate: true }));
    }
  }, [validateResult]);

  const selected = useMemo(
    () => nodes.find((n) => n.id === selectedId) || null,
    [nodes, selectedId],
  );

  const expandInspectorSidebar = useCallback(() => {
    setSidebarCollapsed((prev) => {
      if (!prev) return prev;
      try {
        localStorage.setItem(SIDEBAR_COLLAPSE_KEY, "0");
      } catch {
        /* ignore */
      }
      return false;
    });
  }, []);

  const scrollInspectorIntoView = useCallback((join?: boolean) => {
    requestAnimationFrame(() => {
      const section = document.querySelector(".inspector-section");
      section?.scrollIntoView({ behavior: "smooth", block: "start" });
      if (join) {
        document.querySelector("[data-testid='join-config']")?.scrollIntoView({
          behavior: "smooth",
          block: "nearest",
        });
      }
    });
  }, []);

  const openMapper = useCallback((nodeId: string) => {
    keepMapperOpenRef.current = true;
    selectedIdRef.current = nodeId;
    setSelectedId(nodeId);
    setDiscoverMsg(null);
    setInspectorFocus(null);
    setMapperOpen(true);
    queueMicrotask(() => {
      keepMapperOpenRef.current = false;
    });
  }, []);

  const activateNode = useCallback(
    (nodeId: string, componentType: string) => {
      selectedIdRef.current = nodeId;
      setSelectedId(nodeId);
      setDiscoverMsg(null);
      if (isMapperType(componentType)) {
        keepMapperOpenRef.current = true;
        setInspectorFocus(null);
        setMapperOpen(true);
        queueMicrotask(() => {
          keepMapperOpenRef.current = false;
        });
        return;
      }
      setMapperOpen(false);
      // Inspector lives in the right sidebar — expand if collapsed
      expandInspectorSidebar();
      if (isLookupType(componentType)) {
        setInspectorFocus("join");
        scrollInspectorIntoView(true);
        return;
      }
      setInspectorFocus("inspector");
      scrollInspectorIntoView(false);
    },
    [expandInspectorSidebar, scrollInspectorIntoView],
  );

  const studioActions = useMemo<StudioNodeActions>(
    () => ({ openMapper, activateNode }),
    [openMapper, activateNode],
  );

  const onNodeClick = useCallback(
    (_: unknown, n: Node) => {
      const prevId = selectedIdRef.current;
      selectedIdRef.current = n.id;
      setSelectedId(n.id);
      setDiscoverMsg(null);
      setCanvasFocused(true);
      if (keepMapperOpenRef.current) {
        keepMapperOpenRef.current = false;
        return;
      }
      if (n.id === prevId) {
        // Same already-selected node: do not close mapper (first click of a
        // double-click used to unmount the overlay and made open feel laggy).
        return;
      }
      setMapperOpen(false);
      expandInspectorSidebar();
      setInspectorFocus("inspector");
      scrollInspectorIntoView(false);
    },
    [expandInspectorSidebar, scrollInspectorIntoView],
  );

  const onNodeDoubleClick = useCallback(
    (_: unknown, n: Node) => {
      const d = n.data as EtlNodeData;
      activateNode(n.id, d.componentType);
    },
    [activateNode],
  );

  const onPaneClick = useCallback(() => {
    setSelectedId(null);
    setDiscoverMsg(null);
    setInspectorFocus(null);
    setMapperOpen(false);
    setCanvasFocused(true);
  }, []);

  const placePosition = useCallback(() => {
    if (pointerFlowPos.current) return { ...pointerFlowPos.current };
    const el = document.querySelector(".react-flow") as HTMLElement | null;
    const rect = el?.getBoundingClientRect();
    const cx = (rect?.left ?? 0) + (el?.clientWidth ?? 800) / 2;
    const cy = (rect?.top ?? 0) + (el?.clientHeight ?? 500) / 2;
    return screenToFlowPosition({ x: cx, y: cy });
  }, [screenToFlowPosition]);

  const closeQuickAdd = useCallback(() => {
    setQuickAddOpen(false);
    setQuickAddQuery("");
  }, []);

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
    const folder = selectedFolder || DEFAULT_MY_PIPELINES;
    const created = await api.createPipeline({
      name: "Untitled pipeline",
      description: "Built from the component palette (non-AI path)",
      nodes: [],
      edges: [],
      metadata: { created_via: "palette", workspace_folder: folder },
    });
    await loadPipeline(created);
    void refreshWorkspace();
    return created;
  }, [loadPipeline, refreshWorkspace, selectedFolder]);

  const newBlankPipeline = useCallback(async () => {
    setError(null);
    setBusy(true);
    try {
      const folder = selectedFolder || DEFAULT_MY_PIPELINES;
      const created = await api.createPipeline({
        name: "Untitled pipeline",
        description: "Blank canvas — drag components from the palette",
        nodes: [],
        edges: [],
        metadata: { created_via: "blank", workspace_folder: folder },
      });
      await loadPipeline(created);
      setMapperOpen(false);
      await refreshWorkspace();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [loadPipeline, refreshWorkspace, selectedFolder]);

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

  const onQuickAddPick = useCallback(
    async (comp: ComponentInfo) => {
      const pos = placePosition();
      closeQuickAdd();
      await addComponentNode(comp, pos);
    },
    [placePosition, closeQuickAdd, addComponentNode],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (mapperOpenRef.current) return;
      const el = e.target as HTMLElement | null;
      const tag = el?.tagName;
      const editing =
        tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || Boolean(el?.isContentEditable);

      // Sidebar collapse: ] or Ctrl/Cmd+\
      if (
        (e.key === "]" && !editing && !e.metaKey && !e.ctrlKey && !e.altKey) ||
        (e.key === "\\" && (e.metaKey || e.ctrlKey))
      ) {
        if (!quickAddOpenRef.current) {
          e.preventDefault();
          toggleSidebar();
          return;
        }
      }

      if (quickAddOpenRef.current) return;

      const id = selectedIdRef.current;
      if (id && e.key === "Enter") {
        const node = nodesRef.current.find((n) => n.id === id);
        if (node) {
          const d = node.data as EtlNodeData;
          if (isMapperType(d.componentType)) {
            if (editing && !e.metaKey && !e.ctrlKey) return;
            e.preventDefault();
            openMapper(id);
            return;
          }
        }
      }

      // Type-to-place when canvas focused and not editing a field
      if (editing) return;
      if (!canvasFocusedRef.current && document.activeElement?.closest?.(".react-flow") == null) {
        // Still allow if focus is on body/app after pane click
        if (document.activeElement !== document.body && !document.activeElement?.classList?.contains("react-flow__pane")) {
          return;
        }
      }
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key.length !== 1) return;
      if (!/[A-Za-z0-9_\- ]/.test(e.key)) return;
      e.preventDefault();
      setQuickAddQuery(e.key === " " ? "" : e.key);
      setQuickAddOpen(true);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [openMapper, toggleSidebar]);

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
      const folder = selectedFolder || DEFAULT_MY_PIPELINES;
      const meta = { ...(p.metadata || {}), workspace_folder: folder };
      const saved = await api.updatePipeline(p.id, {
        name: p.name,
        description: p.description,
        nodes: p.nodes,
        edges: p.edges,
        metadata: meta,
      });
      await loadPipeline({ ...p, ...saved, metadata: meta });
      await refreshWorkspace();
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
      const active = (s: string) =>
        s === "pending" || s === "queued" || s === "running" || s === "retrying";
      // Async control plane: POST returns 202 queued; poll until terminal.
      for (let i = 0; i < 200 && active(status.status); i++) {
        await new Promise((r) => setTimeout(r, 500));
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

  const onValidate = async () => {
    if (!pipeline) return;
    setBusy(true);
    setError(null);
    try {
      const updated = fromFlow(pipeline, nodes, edges);
      const result = await api.validatePipeline(pipeline.id, {
        name: updated.name,
        description: updated.description,
        nodes: updated.nodes,
        edges: updated.edges,
        metadata: updated.metadata,
      });
      setValidateResult(result);
      if (!result.ok) {
        const errs = result.checks
          .filter((c) => c.severity === "error")
          .slice(0, 5)
          .map((c) => `${c.symbol || "✗"} ${c.node_id ? c.node_id + ": " : ""}${c.message}`);
        setError(`Validate failed (${result.summary.errors} error(s)):\n${errs.join("\n")}`);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setValidateResult(null);
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

  const updatePipelineMetadata = useCallback(
    (metadata: Record<string, unknown>) => {
      setPipeline((p) => (p ? { ...p, metadata } : p));
      schedulePersist();
    },
    [schedulePersist],
  );

  const contextsRailOpen = railOpen.contexts;

  const onSavePipeline = async () => {
    setSaveBusy(true);
    setError(null);
    try {
      let p = pipelineRef.current;
      if (!p) {
        p = await ensurePipeline();
      }
      const updated = fromFlow(p, nodesRef.current, edgesRef.current);
      const folder =
        (typeof updated.metadata?.workspace_folder === "string" &&
          updated.metadata.workspace_folder.trim()) ||
        selectedFolder ||
        DEFAULT_MY_PIPELINES;
      updated.metadata = {
        ...(updated.metadata || {}),
        workspace_folder: folder,
      };
      const saved = await api.updatePipeline(p.id, updated);
      setPipeline({ ...updated, ...saved, nodes: updated.nodes, edges: updated.edges });
      const path =
        saved.saved_path ||
        (health?.work_dir ? `${health.work_dir}/pipelines/${p.id}.json` : `pipelines/${p.id}.json`);
      setSaveMsg(`Saved to ${path}`);
      window.setTimeout(() => setSaveMsg(null), 6000);
      void refreshWorkspace();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaveBusy(false);
    }
  };

  const downloadBlob = (blob: Blob, filename: string) => {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  const onExportPipeline = async (format: "json" | "zip" = "json") => {
    if (!pipeline) return;
    setBusy(true);
    setError(null);
    try {
      // Persist first so export matches canvas
      const updated = fromFlow(pipeline, nodes, edges);
      const saved = await api.updatePipeline(pipeline.id, updated);
      setPipeline({ ...updated, ...saved, nodes: updated.nodes, edges: updated.edges });
      const { blob, filename } = await api.exportPipeline(pipeline.id, format);
      downloadBlob(blob, filename);
      setSaveMsg(
        format === "zip"
          ? `Exported ${filename} (JSON + README)`
          : `Exported ${filename}`,
      );
      window.setTimeout(() => setSaveMsg(null), 5000);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const onCopyGitCommands = async () => {
    if (!pipeline) return;
    const wd = health?.work_dir || ".";
    const rel = `pipelines/${pipeline.id}.json`;
    const text = [
      `cd ${wd}`,
      "git init   # once per workspace",
      `git add ${rel}`,
      `git commit -m "Save pipeline ${pipeline.name.replace(/"/g, '\\"')}"`,
      "# optional remote (Pro one-click push/pull comes later):",
      "# git remote add origin <your-repo-url>",
      "# git push -u origin main",
    ].join("\n");
    try {
      await navigator.clipboard.writeText(text);
      setSaveMsg("Git commands copied — paste in a terminal at your workspace");
      window.setTimeout(() => setSaveMsg(null), 5000);
    } catch {
      setError("Could not copy to clipboard");
    }
  };

  const metrics = run?.metrics || {};
  const selectedData = selected ? (selected.data as EtlNodeData) : null;

  return (
    <StudioNodeActionsContext.Provider value={studioActions}>
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
            title={`Create blank pipeline in ${selectedFolder || DEFAULT_MY_PIPELINES}`}
          >
            New blank
          </button>
          <button
            type="button"
            className="btn"
            data-testid="load-demo"
            onClick={loadDemo}
            disabled={busy}
            title="Open the default Kafka → Databricks demo"
          >
            Load demo
          </button>
          <button
            type="button"
            className="btn"
            data-testid="save-pipeline"
            onClick={() => void onSavePipeline()}
            disabled={busy || saveBusy}
            title="Save canvas to control plane + work_dir/pipelines/{id}.json"
          >
            {saveBusy ? "Saving…" : "Save"}
          </button>
          <details
            className={`file-menu${fileMenuOpen ? " is-open" : ""}`}
            ref={fileMenuRef}
            open={fileMenuOpen}
            onToggle={(e) => {
              setFileMenuOpen((e.target as HTMLDetailsElement).open);
            }}
            data-testid="file-menu-details"
          >
            <summary
              className="btn"
              data-testid="file-menu"
              title="Workspace, export, or copy git commands"
            >
              File
            </summary>
            <div className="file-menu-dropdown" role="menu" data-testid="file-menu-dropdown">
              <button
                type="button"
                role="menuitem"
                className="file-menu-item"
                data-testid="open-from-workspace"
                title="Focus the left Workspace tree"
                onClick={() => {
                  setFileMenuOpen(false);
                  focusWorkspacePanel();
                }}
              >
                Open from Workspace
              </button>
              <button
                type="button"
                role="menuitem"
                className="file-menu-item"
                data-testid="export-pipeline-json"
                disabled={busy || !pipeline}
                title="Download pipeline JSON"
                onClick={() => {
                  setFileMenuOpen(false);
                  void onExportPipeline("json");
                }}
              >
                Export JSON
              </button>
              <button
                type="button"
                role="menuitem"
                className="file-menu-item"
                data-testid="export-pipeline-zip"
                disabled={busy || !pipeline}
                title="Download zip with JSON + README"
                onClick={() => {
                  setFileMenuOpen(false);
                  void onExportPipeline("zip");
                }}
              >
                Export zip
              </button>
              <button
                type="button"
                role="menuitem"
                className="file-menu-item"
                data-testid="copy-git-commands"
                disabled={!pipeline}
                title="Copy git add/commit commands for this pipeline file"
                onClick={() => {
                  setFileMenuOpen(false);
                  void onCopyGitCommands();
                }}
              >
                Copy git commands
              </button>
            </div>
          </details>
          <button
            type="button"
            className="btn"
            data-testid="validate-pipeline"
            onClick={onValidate}
            disabled={busy || !pipeline}
            title={pipeline ? "Preflight validate (graph, params, refs)" : "Load a pipeline first"}
          >
            Validate
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
      {saveMsg && (
        <div className="status-toast" data-testid="save-toast" role="status">
          {saveMsg}
        </div>
      )}

      <div className={`main${sidebarCollapsed ? " sidebar-collapsed" : ""}`}>
        <div className="left-rail" data-testid="left-rail">
          <div ref={workspacePanelRef}>
            <WorkspacePanel
              workspace={workspace}
              pipelines={workspacePipelines}
              activePipelineId={pipeline?.id || null}
              selectedFolder={selectedFolder}
              busy={busy}
              onSelectFolder={setSelectedFolder}
              onOpenPipeline={(id) => void openFromWorkspace(id)}
              onNewPipeline={() => void newBlankPipeline()}
              onMovePipeline={(id, folder) => void moveWorkspacePipeline(id, folder)}
              onRefresh={() => void refreshWorkspace()}
            />
          </div>
          <aside className="palette" data-testid="component-palette" aria-label="Component palette">
            <h3>Components</h3>
            <p className="palette-hint">
              Drag, click, or type on the canvas to place. Primary non-AI build path.
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
        </div>
        <div className={`canvas-wrap${busy ? " is-running" : ""}${!busy && run?.status === "success" ? " run-success" : ""}${!busy && run?.status === "failed" ? " run-failed" : ""}`}>
          <div className="ai-bar">
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="Describe your pipeline in English…"
              rows={1}
              onFocus={() => setCanvasFocused(false)}
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
          <button
            type="button"
            className={`sidebar-toggle${sidebarCollapsed ? " is-collapsed" : ""}`}
            data-testid="sidebar-toggle"
            title={sidebarCollapsed ? "Expand inspector (])" : "Collapse inspector (])"}
            aria-label={sidebarCollapsed ? "Expand right sidebar" : "Collapse right sidebar"}
            aria-pressed={sidebarCollapsed}
            onClick={toggleSidebar}
          >
            {sidebarCollapsed ? "‹" : "›"}
          </button>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            nodeTypes={nodeTypes}
            fitView
            onlyRenderVisibleElements
            nodesDraggable
            elementsSelectable
            selectNodesOnDrag={false}
            nodeDragThreshold={8}
            onDrop={(e) => void onCanvasDrop(e)}
            onDragOver={onCanvasDragOver}
            onNodeClick={onNodeClick}
            onNodeDoubleClick={onNodeDoubleClick}
            onPaneClick={onPaneClick}
            onPaneMouseMove={(e) => {
              pointerFlowPos.current = screenToFlowPosition({ x: e.clientX, y: e.clientY });
            }}
            onInit={() => setCanvasFocused(true)}
            proOptions={{ hideAttribution: true }}
            className={canvasFocused ? "canvas-focused" : undefined}
          >
            <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="#d2d2d7" />
            <Controls showInteractive={false} />
            <MiniMap
              pannable
              zoomable
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
              style={{ background: "#ffffff", border: "1px solid #d2d2d7", width: 120, height: 80 }}
            />
          </ReactFlow>
          {canvasFocused && !quickAddOpen && !mapperOpen && (
            <div className="canvas-type-hint" data-testid="canvas-type-hint">
              Type to place · ] collapses inspector
            </div>
          )}
        </div>

        <aside
          className={`sidebar${sidebarCollapsed ? " is-collapsed" : ""}${selected ? " has-node-selection" : ""}`}
          data-testid="right-sidebar"
          aria-hidden={sidebarCollapsed}
        >
          <div
            className={`sidebar-section inspector-section${selected ? " has-selection" : ""}`}
            data-testid="inspector-section"
          >
            <h3>Node inspector</h3>
            {selected && selectedData ? (
              <>
                {isMapperType(selectedData.componentType) && (
                  <div className="inspector-actions">
                    <button
                      type="button"
                      className="btn btn-primary btn-open-mapper"
                      data-testid="open-schema-mapper"
                      title={
                        selectedData.componentType === "tmap"
                          ? "Open Field Mapper (Enter or ⌘↵)"
                          : "Open Schema Map (Enter or ⌘↵)"
                      }
                      aria-keyshortcuts="Enter Meta+Enter Control+Enter"
                      onClick={() => openMapper(selected.id)}
                    >
                      <span className="btn-open-mapper-label">
                        {selectedData.componentType === "tmap"
                          ? "Open Field Mapper"
                          : "Open Schema Map"}
                      </span>
                      <span className="btn-open-mapper-keys">Enter · ⌘↵</span>
                    </button>
                    <p className="mapper-hint">
                      {selectedData.componentType === "tmap"
                        ? "Double-click or Enter — Input · Variables · Output. To merge two sources first, use Lookup Join (Main + Lookup)."
                        : "Double-click or Enter — map input columns to Output. For Variables and expressions, use Field Mapper."}
                    </p>
                  </div>
                )}
                {isLookupType(selectedData.componentType) && (
                  <div className="inspector-actions">
                    <p className="mapper-hint" data-testid="lookup-inspector-hint">
                      Wire <strong>Main</strong> (upper) for the primary stream and{" "}
                      <strong>Lookup</strong> (lower) for enrichment — or set Lookup file. Double-click
                      jumps to join type, match, and keys.
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
                {(selectedData.componentType.endsWith("_destination") ||
                  selectedData.componentType.startsWith("databricks") ||
                  selectedData.componentType.includes("snowflake")) && (
                  <div className="inspector-actions">
                    <button
                      type="button"
                      className="btn btn-sm"
                      data-testid="test-connection"
                      onClick={() => {
                        const params =
                          componentByType[selectedData.componentType]?.parameters || [];
                        const missing = missingRequiredKeys(
                          selectedData.config || {},
                          params,
                        );
                        if (missing.length) {
                          setDiscoverMsg(`Missing required: ${missing.join(", ")}`);
                          return;
                        }
                        const demo =
                          Boolean(selectedData.config?.demo) || Boolean(health?.demo_mode);
                        setDiscoverMsg(
                          demo
                            ? "Demo mode — params look complete; live connection not probed."
                            : "Params look complete — use Validate / Run to exercise the sink.",
                        );
                      }}
                    >
                      Test connection
                    </button>
                    <p className="mapper-hint" data-testid="sink-inspector-hint">
                      Configure params here — double-click Field Mapper for mapping.
                    </p>
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
                  metadata={pipeline?.metadata}
                  onChange={updateSelectedConfig}
                  onConfigReplace={replaceSelectedConfig}
                  onMetadataChange={updatePipelineMetadata}
                  focusJoin={inspectorFocus === "join"}
                  onOpenPipeline={async (pid) => {
                    const p = await api.getPipeline(pid);
                    await loadPipeline(p);
                  }}
                />
              </>
            ) : (
              <p className="empty-hint">Select a node on the canvas.</p>
            )}
          </div>

          <div
            className={`sidebar-section sidebar-pipeline rail-accordion${railOpen.pipeline || !selected ? " is-open" : ""}${selected ? " is-secondary" : ""}`}
            data-testid="pipeline-panel"
          >
            <button
              type="button"
              className="rail-accordion-toggle"
              data-testid="rail-pipeline-toggle"
              aria-expanded={railOpen.pipeline || !selected}
              onClick={() => setRailOpen((r) => ({ ...r, pipeline: !r.pipeline }))}
            >
              <h3>Pipeline</h3>
              <span className="rail-accordion-chevron" aria-hidden>
                {railOpen.pipeline || !selected ? "▾" : "▸"}
              </span>
            </button>
            {(railOpen.pipeline || !selected) && (
              pipeline ? (
                <>
                  <p className="pipeline-title">{pipeline.name}</p>
                  <p className="pipeline-desc">{pipeline.description || "No description"}</p>
                </>
              ) : (
                <p className="empty-hint">Use the palette, New blank, Load demo, or AI Build.</p>
              )
            )}
          </div>

          <div
            className={`sidebar-section rail-accordion${contextsRailOpen ? " is-open" : ""}`}
            data-testid="job-contexts-section"
          >
            <button
              type="button"
              className="rail-accordion-toggle"
              data-testid="rail-contexts-toggle"
              aria-expanded={contextsRailOpen}
              onClick={() => setRailOpen((r) => ({ ...r, contexts: !r.contexts }))}
            >
              <h3>Job Contexts</h3>
              <span className="rail-accordion-chevron" aria-hidden>
                {contextsRailOpen ? "▾" : "▸"}
              </span>
            </button>
            {contextsRailOpen &&
              (pipeline ? (
                <JobContextsPanel
                  pipelineId={pipeline.id}
                  metadata={pipeline.metadata}
                  onMetadataChange={updatePipelineMetadata}
                />
              ) : (
                <p className="empty-hint">Open a pipeline to edit Job Contexts.</p>
              ))}
          </div>

          <div className={`sidebar-section rail-accordion${railOpen.schedule ? " is-open" : ""}`}>
            <button
              type="button"
              className="rail-accordion-toggle"
              data-testid="rail-schedule-toggle"
              aria-expanded={railOpen.schedule}
              onClick={() => setRailOpen((r) => ({ ...r, schedule: !r.schedule }))}
            >
              <h3>Schedule</h3>
              <span className="rail-accordion-chevron" aria-hidden>
                {railOpen.schedule ? "▾" : "▸"}
              </span>
            </button>
            {railOpen.schedule && (
              pipeline ? (
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
              )
            )}
          </div>

          <div
            className={`sidebar-section rail-accordion${railOpen.lastRun ? " is-open" : ""}`}
            data-testid="last-run-panel"
          >
            <button
              type="button"
              className="rail-accordion-toggle"
              data-testid="rail-lastrun-toggle"
              aria-expanded={railOpen.lastRun}
              onClick={() => setRailOpen((r) => ({ ...r, lastRun: !r.lastRun }))}
            >
              <h3>Last run</h3>
              <span className="rail-accordion-chevron" aria-hidden>
                {railOpen.lastRun ? "▾" : "▸"}
              </span>
            </button>
            {railOpen.lastRun && (
              run ? (
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
                      <div className="metric-value accent">
                        {run.summary?.rows_in ?? metrics.rows_in ?? "—"}
                      </div>
                    </div>
                    <div className="metric">
                      <div className="metric-label">Rows out</div>
                      <div className="metric-value ok">
                        {run.summary?.rows_out ?? metrics.rows_out ?? "—"}
                      </div>
                    </div>
                    <div className="metric">
                      <div className="metric-label">Rejected</div>
                      <div className="metric-value warn">
                        {run.summary?.rows_rejected ?? metrics.rows_rejected ?? "—"}
                      </div>
                    </div>
                    <div className="metric">
                      <div className="metric-label">Duration</div>
                      <div className="metric-value">
                        {run.duration_ms != null ? `${Math.round(run.duration_ms)}` : "—"}
                      </div>
                    </div>
                  </div>
                  {run.node_runs && run.node_runs.length > 0 && (
                    <div className="node-runs" data-testid="node-runs" style={{ marginTop: "0.65rem" }}>
                      <div
                        style={{
                          fontSize: "0.68rem",
                          color: "var(--text-muted)",
                          marginBottom: 4,
                          textTransform: "uppercase",
                          letterSpacing: "0.04em",
                        }}
                      >
                        Nodes
                      </div>
                      {run.node_runs.map((nr, i) => (
                        <div
                          key={String(nr.node_id || i)}
                          style={{
                            fontSize: "0.72rem",
                            display: "grid",
                            gridTemplateColumns: "1fr auto",
                            gap: 4,
                            padding: "2px 0",
                            borderBottom: "1px solid var(--border, #e5e5e5)",
                          }}
                        >
                          <span>
                            <span className={`status-pill ${nr.status || ""}`} style={{ fontSize: "0.6rem" }}>
                              {nr.status || "—"}
                            </span>{" "}
                            {nr.node_id}
                            {nr.component_type ? (
                              <span style={{ color: "var(--text-muted)" }}> · {nr.component_type}</span>
                            ) : null}
                          </span>
                          <span style={{ color: "var(--text-muted)", whiteSpace: "nowrap" }}>
                            {nr.rows_in ?? 0}→{nr.rows_out ?? 0}
                            {(nr.rows_rejected ?? 0) > 0 ? ` ✗${nr.rows_rejected}` : ""}
                            {nr.duration_ms != null ? ` · ${Math.round(Number(nr.duration_ms))}ms` : ""}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                  {run.events && run.events.length > 0 && (
                    <div className="run-events" data-testid="run-events" style={{ marginTop: "0.55rem" }}>
                      <div
                        style={{
                          fontSize: "0.68rem",
                          color: "var(--text-muted)",
                          marginBottom: 4,
                          textTransform: "uppercase",
                          letterSpacing: "0.04em",
                        }}
                      >
                        Events ({run.summary?.event_count ?? run.events.length})
                      </div>
                      {run.events.slice(-6).map((ev, i) => (
                        <div key={i} style={{ fontSize: "0.7rem", color: "var(--text-muted)" }}>
                          {ev.from_status || "—"} → {ev.to_status || "—"}
                          {ev.message ? ` · ${ev.message}` : ""}
                        </div>
                      ))}
                    </div>
                  )}
                </>
              ) : (
                <p className="empty-hint">Run the pipeline to see metrics.</p>
              )
            )}
          </div>

          {validateResult && (
            <div
              className={`sidebar-section rail-accordion${railOpen.validate ? " is-open" : ""}`}
              data-testid="validate-panel"
            >
              <button
                type="button"
                className="rail-accordion-toggle"
                data-testid="rail-validate-toggle"
                aria-expanded={railOpen.validate}
                onClick={() => setRailOpen((r) => ({ ...r, validate: !r.validate }))}
              >
                <h3>Validate {validateResult.ok ? "✓" : "✗"}</h3>
                <span className="rail-accordion-chevron" aria-hidden>
                  {railOpen.validate ? "▾" : "▸"}
                </span>
              </button>
              {railOpen.validate && (
                <>
                  <p style={{ fontSize: "0.72rem", color: "var(--text-muted)", marginTop: 0 }}>
                    {validateResult.summary.errors} error(s), {validateResult.summary.warnings}{" "}
                    warning(s)
                  </p>
                  <div style={{ maxHeight: 180, overflow: "auto" }}>
                    {validateResult.checks
                      .filter((c) => c.severity !== "ok")
                      .concat(validateResult.checks.filter((c) => c.severity === "ok").slice(0, 3))
                      .map((c, i) => (
                        <div key={i} style={{ fontSize: "0.72rem", marginBottom: 4 }}>
                          {c.symbol || ""} {c.node_id ? `${c.node_id}: ` : ""}
                          {c.message}
                        </div>
                      ))}
                  </div>
                </>
              )}
            </div>
          )}

          <div
            className={`sidebar-section logs-panel rail-accordion${railOpen.logs ? " is-open" : ""}`}
            data-testid="logs-panel"
          >
            <button
              type="button"
              className="rail-accordion-toggle"
              data-testid="rail-logs-toggle"
              aria-expanded={railOpen.logs}
              onClick={() => setRailOpen((r) => ({ ...r, logs: !r.logs }))}
            >
              <h3>Logs</h3>
              <span className="rail-accordion-chevron" aria-hidden>
                {railOpen.logs ? "▾" : "▸"}
              </span>
            </button>
            {railOpen.logs && (
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

      <QuickAddPalette
        open={quickAddOpen}
        query={quickAddQuery}
        onQueryChange={setQuickAddQuery}
        components={paletteItems}
        onPick={(c) => void onQuickAddPick(c)}
        onClose={closeQuickAdd}
      />

      <footer className="footer status-bar" data-testid="status-bar">
        <span className="status-left">
          FormulaHub ETL · Apache-2.0 · demo {apiOk ? (health?.demo_mode ? "on" : "off") : "api offline"}
          {health?.readiness_level ? ` · ${health.readiness_level}` : ""}
        </span>
        <span
          className="status-workdir"
          data-testid="status-workdir"
          title="Local runner workspace on this machine"
        >
          {health?.work_dir
            ? `workspace on this machine · ${health.work_dir}`
            : apiOk
              ? "workspace on this machine · …"
              : API_BASE}
        </span>
        <span className="status-api">{API_BASE}</span>
      </footer>
    </div>
    </StudioNodeActionsContext.Provider>
  );
}

export default function App() {
  return (
    <ReactFlowProvider>
      <AppCanvas />
    </ReactFlowProvider>
  );
}
