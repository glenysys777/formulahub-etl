const API_BASE = import.meta.env.VITE_API_URL || "http://127.0.0.1:18765";

export type PipelineNode = {
  id: string;
  type: string;
  label?: string | null;
  config: Record<string, unknown>;
  position: { x: number; y: number };
};

export type PipelineEdge = {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
};

export type Pipeline = {
  id: string;
  name: string;
  description: string;
  nodes: PipelineNode[];
  edges: PipelineEdge[];
  metadata?: Record<string, unknown>;
  /** Absolute path to mirror JSON under work_dir/pipelines/ (when present). */
  saved_path?: string;
  pipeline_version_id?: string;
  version?: string;
};

export type RunStatus = {
  run_id: string;
  pipeline_id: string;
  status:
    | "pending"
    | "queued"
    | "running"
    | "success"
    | "failed"
    | "cancelled"
    | "retrying"
    | "timed_out"
    | string;
  pipeline_version_id?: string;
  node_runs?: Array<{
    node_id?: string;
    component_type?: string;
    status?: string;
    rows_in?: number;
    rows_out?: number;
    rows_rejected?: number;
    duration_ms?: number;
    error?: string | null;
    [key: string]: unknown;
  }>;
  events?: Array<{
    event_type?: string;
    from_status?: string | null;
    to_status?: string | null;
    message?: string | null;
    ts?: number;
    [key: string]: unknown;
  }>;
  summary?: {
    status?: string;
    nodes_total?: number;
    nodes_success?: number;
    nodes_failed?: number;
    rows_in?: number;
    rows_out?: number;
    rows_rejected?: number;
    duration_ms?: number;
    event_count?: number;
  };
  metrics: Record<string, number>;
  node_metrics: Record<string, Record<string, number>>;
  logs: string[];
  error?: string | null;
  duration_ms?: number;
};

export type ValidateCheck = {
  code: string;
  severity: "ok" | "warn" | "error" | string;
  symbol?: string;
  message: string;
  node_id?: string;
  edge_id?: string;
  keys?: string[];
  connection_id?: string;
};

export type ValidateResult = {
  ok: boolean;
  pipeline_id?: string;
  checks: ValidateCheck[];
  summary: { errors: number; warnings: number; ok: number };
};

export type ParamDef = {
  key: string;
  label: string;
  type: "string" | "number" | "boolean" | "secret" | "select" | "string_list" | string;
  required?: boolean;
  default?: unknown;
  help?: string;
  options?: string[];
  placeholder?: string;
};

export type ComponentInfo = {
  type: string;
  display_name: string;
  category: string;
  config_schema?: Record<string, unknown>;
  parameters: ParamDef[];
};

export type SchemaColumn = {
  name: string;
  type: string;
  nullable?: boolean;
};

export type SchemaDiscoverResult = {
  columns: SchemaColumn[];
  sample_rows?: Record<string, unknown>[];
};

export type PipelineSchedule = {
  pipeline_id: string;
  enabled: boolean;
  cron: string;
  timezone: string;
  /** Epoch seconds — next scheduled fire (persisted by the API). */
  next_run_at?: number | null;
  last_run_at?: number | null;
  last_run_id?: string | null;
  last_status?: string | null;
};

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export type HealthInfo = {
  status: string;
  demo_mode: boolean;
  version?: string;
  work_dir?: string;
  db_path?: string;
  readiness_level?: string;
  auth?: string;
};

export const api = {
  health: () => req<HealthInfo>("/health"),
  listComponents: () => req<ComponentInfo[]>("/api/components"),
  listPipelines: () => req<Pipeline[]>("/api/pipelines"),
  getPipeline: (id: string) => req<Pipeline>(`/api/pipelines/${id}`),
  createPipeline: (body: Partial<Pipeline>) =>
    req<Pipeline>("/api/pipelines", { method: "POST", body: JSON.stringify(body) }),
  updatePipeline: (id: string, body: Partial<Pipeline>) =>
    req<Pipeline>(`/api/pipelines/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  importPipeline: (body: Partial<Pipeline>) =>
    req<Pipeline>("/api/pipelines/import", { method: "POST", body: JSON.stringify(body) }),
  exportPipeline: async (id: string, format: "json" | "zip" = "json") => {
    const res = await fetch(
      `${API_BASE}/api/pipelines/${id}/export?format=${format}`,
    );
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || `${res.status} ${res.statusText}`);
    }
    const blob = await res.blob();
    const disposition = res.headers.get("Content-Disposition") || "";
    const match = /filename="([^"]+)"/i.exec(disposition);
    const filename =
      match?.[1] || (format === "zip" ? `${id}.zip` : `${id}.json`);
    return { blob, filename };
  },
  runPipeline: (id: string) =>
    req<{ run_id: string; status: string }>(`/api/pipelines/${id}/run`, { method: "POST" }),
  validatePipeline: (
    id: string,
    body?: Partial<Pick<Pipeline, "name" | "description" | "nodes" | "edges" | "metadata">>,
  ) =>
    req<ValidateResult>(`/api/pipelines/${id}/validate`, {
      method: "POST",
      body: body ? JSON.stringify(body) : undefined,
    }),
  getRun: (id: string) => req<RunStatus>(`/api/runs/${id}`),
  aiBuild: (description: string, name?: string) =>
    req<Pipeline>("/api/ai/build", {
      method: "POST",
      body: JSON.stringify({ description, name }),
    }),
  discoverSchema: (component_type: string, config: Record<string, unknown>) =>
    req<SchemaDiscoverResult>("/api/schema/discover", {
      method: "POST",
      body: JSON.stringify({ component_type, config }),
    }),
  getSchedule: (pipelineId: string) =>
    req<PipelineSchedule>(`/api/pipelines/${pipelineId}/schedule`),
  putSchedule: (
    pipelineId: string,
    body: { enabled: boolean; cron: string; timezone: string },
  ) =>
    req<PipelineSchedule>(`/api/pipelines/${pipelineId}/schedule`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
};

export { API_BASE };
