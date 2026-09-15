import { useEffect, useMemo, useState } from "react";
import type { ComponentInfo, ParamDef, Pipeline } from "./api";
import { api } from "./api";
import { VariablesPanel } from "./VariablesPanel";

function friendlyNodeId(nodeId: string, componentType: string, _label?: string): string {
  const raw = (nodeId || "").trim();
  const lower = raw.toLowerCase();
  if (lower === "tmap" || lower.includes("tmap")) return "field_mapper";
  if (componentType === "tmap") return "field_mapper";
  return raw;
}

function friendlyTypeLabel(componentType: string, label?: string, displayName?: string): string {
  if (displayName) return displayName;
  if (componentType === "tmap") return "Field Mapper";
  if (componentType === "column_map") return "Schema Map";
  return label || componentType;
}


type Props = {
  nodeId: string;
  componentType: string;
  label: string;
  config: Record<string, unknown>;
  component?: ComponentInfo;
  metadata?: Record<string, unknown> | null;
  onChange: (key: string, value: unknown) => void;
  onConfigReplace: (config: Record<string, unknown>) => void;
  onMetadataChange?: (metadata: Record<string, unknown>) => void;
  /** Double-click on Lookup Join focuses join fields in this inspector. */
  focusJoin?: boolean;
  /** Open another pipeline in Studio (Run Pipeline → Open child). */
  onOpenPipeline?: (pipelineId: string) => void | Promise<void>;
};

function isEmpty(value: unknown): boolean {
  if (value === undefined || value === null) return true;
  if (typeof value === "string" && value.trim() === "") return true;
  if (Array.isArray(value) && value.length === 0) return true;
  return false;
}

function displayValue(param: ParamDef, config: Record<string, unknown>): string | number | boolean {
  const raw = config[param.key];
  if (raw === undefined || raw === null) {
    if (param.default !== undefined && param.default !== null) {
      return param.default as string | number | boolean;
    }
    if (param.type === "boolean") return false;
    if (param.type === "number") return "";
    if (param.type === "string_list") return "";
    return "";
  }
  if (param.type === "string_list") {
    if (Array.isArray(raw)) return raw.map(String).join("\n");
    return String(raw);
  }
  if (param.type === "string" && (typeof raw === "object")) {
    try {
      return JSON.stringify(raw, null, 2);
    } catch {
      return String(raw);
    }
  }
  if (param.type === "boolean") return Boolean(raw);
  if (param.type === "number") return typeof raw === "number" ? raw : Number(raw);
  return String(raw);
}

function parseFieldValue(param: ParamDef, input: string | boolean, previous: unknown): unknown {
  if (param.type === "boolean") return Boolean(input);
  if (param.type === "number") {
    const s = String(input).trim();
    if (s === "") return undefined;
    const n = Number(s);
    return Number.isFinite(n) ? n : previous;
  }
  if (param.type === "string_list") {
    const s = String(input);
    const parts = s
      .split(/[\n,]+/)
      .map((x) => x.trim())
      .filter(Boolean);
    return parts;
  }
  if (param.type === "string") {
    const s = String(input);
    // If previous value was object/array, try to keep JSON semantics
    if (previous !== undefined && typeof previous === "object") {
      try {
        return JSON.parse(s);
      } catch {
        return s;
      }
    }
    // Heuristic: looks like JSON object/array
    const trimmed = s.trim();
    if (
      (trimmed.startsWith("{") && trimmed.endsWith("}")) ||
      (trimmed.startsWith("[") && trimmed.endsWith("]"))
    ) {
      try {
        return JSON.parse(trimmed);
      } catch {
        return s;
      }
    }
    return s;
  }
  return String(input);
}



export function missingRequiredKeys(
  config: Record<string, unknown>,
  parameters: ParamDef[],
): string[] {
  return parameters
    .filter((p) => p.required)
    .filter((p) => {
      const v = config[p.key];
      if (!isEmpty(v)) return false;
      // default satisfies required for run-time fill, but UI still hints if unset in config
      return isEmpty(p.default);
    })
    .map((p) => p.key);
}

export function NodeInspector({
  nodeId,
  componentType,
  label,
  config,
  component,
  metadata,
  onChange,
  onConfigReplace,
  onMetadataChange,
  focusJoin = false,
  onOpenPipeline,
}: Props) {
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [jsonDraft, setJsonDraft] = useState("");
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [pipelineOptions, setPipelineOptions] = useState<Pipeline[]>([]);
  const [openBusy, setOpenBusy] = useState(false);

  const parameters = component?.parameters || [];
  const missing = useMemo(
    () => missingRequiredKeys(config, parameters),
    [config, parameters],
  );

  useEffect(() => {
    if (!focusJoin || componentType !== "lookup_join") return;
    const el =
      (document.getElementById("inspector-join-how") as HTMLElement | null) ||
      (document.querySelector("[data-testid='join-config'] select, [data-testid='join-config'] input:not([readonly])") as HTMLElement | null);
    el?.focus();
  }, [focusJoin, componentType, nodeId]);

  useEffect(() => {
    if (componentType !== "run_pipeline") return;
    let cancelled = false;
    api
      .listPipelines()
      .then((list) => {
        if (!cancelled) setPipelineOptions(list);
      })
      .catch(() => {
        if (!cancelled) setPipelineOptions([]);
      });
    return () => {
      cancelled = true;
    };
  }, [componentType, nodeId]);

  const openAdvanced = () => {
    setJsonDraft(JSON.stringify(config ?? {}, null, 2));
    setJsonError(null);
    setAdvancedOpen((v) => !v);
  };

  const applyJson = () => {
    try {
      const parsed = JSON.parse(jsonDraft);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        setJsonError("Config must be a JSON object");
        return;
      }
      onConfigReplace(parsed as Record<string, unknown>);
      setJsonError(null);
    } catch (e) {
      setJsonError(e instanceof Error ? e.message : "Invalid JSON");
    }
  };

  const typeLabel = friendlyTypeLabel(componentType, label, component?.display_name);

  const tip =
    componentType === "lookup_join"
      ? focusJoin
        ? "Join configuration — set type, match, and keys below. Wire Main (upper handle) for the primary stream and Lookup (lower handle) for enrichment — or set Lookup file."
        : "Lookup Join merges two streams: wire the primary row flow to Main and the enrichment flow to Lookup (or set Lookup file). Join keys below must match. Then map columns with Field Mapper."
      : componentType === "tmap"
        ? "Field Mapper is column logic on the input stream — Input columns, Variables (named expressions), and Output mappings. To merge two tables first, use Lookup Join (Main + Lookup handles)."
        : componentType === "column_map"
          ? "Schema Map renames columns on the input stream. For Variables and expressions, use Field Mapper."
          : componentType === "databricks_sql"
            ? "Run SQL on a Databricks SQL Warehouse. Use ${run_date}, ${context.env}, ${upstream.field} — preview resolves against the active Job Context without executing live. DEMO writes a local sidecar; LIVE is UNPROVEN until credentials."
            : componentType === "databricks_job"
              ? "Trigger a Databricks Job. Notebook/python param values accept ${…} variables. DEMO sidecar only until live token + workspace."
              : componentType === "run_pipeline"
                ? "Run a Child pipeline from this Master. Context mode inherit uses the Master active Job Context name and merges values (secrets never inherited). Later nodes can read ${child.<publish_as>.…}."
                : null;

  const childPipelineId = String(config.pipeline_id || "").trim();

  const openChild = async () => {
    if (!childPipelineId || !onOpenPipeline) return;
    setOpenBusy(true);
    try {
      await onOpenPipeline(childPipelineId);
    } finally {
      setOpenBusy(false);
    }
  };

  return (
    <div className="inspector">
      <div className="inspector-meta">
        <div className="field">
          <label>Node</label>
          <input value={label || typeLabel} readOnly />
        </div>
        <div className="field-row">
          <div className="field">
            <label>Id</label>
            <input value={friendlyNodeId(nodeId, componentType, label)} readOnly />
          </div>
          <div className="field">
            <label>Type</label>
            <input value={typeLabel} readOnly data-testid="inspector-type" />
          </div>
        </div>
      </div>

      {tip && (
        <div className="inspector-tip" data-testid="inspector-tip">
          {tip}
        </div>
      )}

      <VariablesPanel
        componentType={componentType}
        config={config}
        metadata={metadata}
        onMetadataChange={onMetadataChange}
      />

      {missing.length > 0 && (
        <div className="inspector-warn" data-testid="missing-params">
          Missing required: {missing.join(", ")}
        </div>
      )}

      <div
        className={`inspector-fields${componentType === "lookup_join" ? " join-config" : ""}${
          focusJoin ? " is-focused" : ""
        }`}
        data-testid={componentType === "lookup_join" ? "join-config" : undefined}
      >
        {parameters.length === 0 ? (
          <p className="empty-hint">No parameter schema for this component.</p>
        ) : (
          parameters.map((param) => {
            const requiredMissing = missing.includes(param.key);
            const value = displayValue(param, config);
            const fieldClass = `field${requiredMissing ? " field-missing" : ""}`;
            const fieldId =
              componentType === "lookup_join" && param.key === "how"
                ? "inspector-join-how"
                : undefined;

            if (componentType === "run_pipeline" && param.key === "pipeline_id") {
              const ids = new Set(pipelineOptions.map((p) => p.id));
              const current = String(value || "");
              return (
                <div className={fieldClass} key={param.key} data-testid="run-pipeline-picker">
                  <label>
                    {param.label}
                    {param.required ? " *" : ""}
                  </label>
                  <select
                    value={current}
                    onChange={(e) => onChange(param.key, e.target.value)}
                    data-testid="run-pipeline-select"
                  >
                    <option value="">Select a Child pipeline…</option>
                    {pipelineOptions.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name || p.id}
                      </option>
                    ))}
                    {current && !ids.has(current) ? (
                      <option value={current}>{current} (path / custom)</option>
                    ) : null}
                  </select>
                  <input
                    type="text"
                    value={current}
                    placeholder="Or paste pipeline id / relative JSON path"
                    onChange={(e) => onChange(param.key, e.target.value)}
                    data-testid="run-pipeline-id-input"
                    style={{ marginTop: 6 }}
                  />
                  {param.help ? <div className="field-help">{param.help}</div> : null}
                </div>
              );
            }

            if (param.type === "boolean") {
              return (
                <div className={fieldClass} key={param.key}>
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={Boolean(value)}
                      onChange={(e) => onChange(param.key, e.target.checked)}
                    />
                    <span>
                      {param.label}
                      {param.required ? " *" : ""}
                    </span>
                  </label>
                  {param.help ? <div className="field-help">{param.help}</div> : null}
                </div>
              );
            }

            if (param.type === "select") {
              return (
                <div className={fieldClass} key={param.key}>
                  <label htmlFor={fieldId}>
                    {param.label}
                    {param.required ? " *" : ""}
                  </label>
                  <select
                    id={fieldId}
                    value={String(value)}
                    onChange={(e) => onChange(param.key, e.target.value)}
                  >
                    {(param.options || []).map((opt) => (
                      <option key={opt} value={opt}>
                        {opt}
                      </option>
                    ))}
                  </select>
                  {param.help ? <div className="field-help">{param.help}</div> : null}
                </div>
              );
            }

            if (
              param.type === "string_list" ||
              param.key === "sql" ||
              (param.type === "string" && typeof config[param.key] === "object")
            ) {
              const isSql = param.key === "sql";
              return (
                <div className={fieldClass} key={param.key}>
                  <label>
                    {param.label}
                    {param.required ? " *" : ""}
                  </label>
                  <textarea
                    rows={isSql ? 6 : param.type === "string_list" ? 3 : 5}
                    value={String(value)}
                    placeholder={
                      isSql
                        ? param.placeholder || "SELECT … WHERE dt = '${run_date}'"
                        : param.type === "string_list"
                          ? "one per line · values may use ${…}"
                          : undefined
                    }
                    spellCheck={false}
                    data-testid={isSql ? "sql-editor" : undefined}
                    onChange={(e) =>
                      onChange(param.key, parseFieldValue(param, e.target.value, config[param.key]))
                    }
                  />
                  {param.help ? <div className="field-help">{param.help}</div> : null}
                </div>
              );
            }

            return (
              <div className={fieldClass} key={param.key}>
                <label>
                  {param.label}
                  {param.required ? " *" : ""}
                </label>
                <input
                  type={param.type === "secret" ? "password" : param.type === "number" ? "number" : "text"}
                  value={value === undefined || value === null ? "" : String(value)}
                  onChange={(e) =>
                    onChange(param.key, parseFieldValue(param, e.target.value, config[param.key]))
                  }
                />
                {param.help ? <div className="field-help">{param.help}</div> : null}
              </div>
            );
          })
        )}
      </div>

      {componentType === "run_pipeline" && (
        <div className="field" data-testid="open-child-pipeline">
          <button
            type="button"
            className="btn btn-sm"
            disabled={!childPipelineId || !onOpenPipeline || openBusy}
            onClick={() => void openChild()}
          >
            {openBusy ? "Opening…" : "Open child pipeline"}
          </button>
          <div className="field-help">
            Opens the selected Child pipeline in Studio. Use Job Contexts inherit on the Master so
            DEV/QA/PROD flows through Run Pipeline steps.
          </div>
        </div>
      )}

      <div className="inspector-advanced">
        <button type="button" className="btn-link" onClick={openAdvanced}>
          {advancedOpen ? "▾ Advanced (raw JSON)" : "▸ Advanced (raw JSON)"}
        </button>
        {advancedOpen && (
          <div className="advanced-panel">
            <textarea
              className="json-editor"
              rows={8}
              value={jsonDraft}
              onChange={(e) => setJsonDraft(e.target.value)}
              spellCheck={false}
            />
            {jsonError && <div className="field-error">{jsonError}</div>}
            <button type="button" className="btn btn-sm" onClick={applyJson}>
              Apply JSON
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
