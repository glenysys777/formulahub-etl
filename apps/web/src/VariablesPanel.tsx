import { useMemo, useState } from "react";
import {
  buildPreviewScope,
  collectTemplateText,
  parseContexts,
  previewRefs,
  resolveString,
  supportsVariables,
  type VarRow,
} from "./vars";

type Props = {
  componentType: string;
  config: Record<string, unknown>;
  metadata?: Record<string, unknown> | null;
  onMetadataChange?: (metadata: Record<string, unknown>) => void;
};

/**
 * Param-first variables panel for Databricks SQL / Job nodes.
 * Shows refs, active Job Context, and a resolved preview (no live execution).
 */
export function VariablesPanel({
  componentType,
  config,
  metadata,
  onMetadataChange,
}: Props) {
  const [previewOpen, setPreviewOpen] = useState(true);

  const { active, sets } = useMemo(() => parseContexts(metadata), [metadata]);
  const contextNames = useMemo(() => Object.keys(sets), [sets]);

  const scope = useMemo(
    () => buildPreviewScope(metadata, { activeOverride: active }),
    [metadata, active],
  );

  const templateText = useMemo(() => collectTemplateText(config), [config]);
  const rows: VarRow[] = useMemo(
    () => previewRefs(templateText, scope),
    [templateText, scope],
  );

  const resolvedSql = useMemo(() => {
    if (typeof config.sql !== "string" || !config.sql.trim()) return "";
    return resolveString(config.sql, scope);
  }, [config.sql, scope]);

  const resolvedParams = useMemo(() => {
    const out: string[] = [];
    for (const key of ["notebook_params", "python_params"] as const) {
      const raw = config[key];
      let lines: string[] = [];
      if (Array.isArray(raw)) lines = raw.map(String);
      else if (typeof raw === "string") lines = raw.split("\n");
      for (const line of lines) {
        if (!line.includes("${")) continue;
        out.push(resolveString(line, scope));
      }
    }
    return out;
  }, [config, scope]);

  if (!supportsVariables(componentType)) return null;

  const setActive = (name: string) => {
    if (!onMetadataChange) return;
    const next = { ...(metadata || {}) };
    const contexts = {
      ...((next.contexts as Record<string, unknown>) || {}),
      active: name,
      sets: sets,
    };
    next.contexts = contexts;
    onMetadataChange(next);
  };

  return (
    <div className="variables-panel" data-testid="variables-panel">
      <div className="variables-panel-head">
        <h4>Variables</h4>
        <span className="variables-hint">
          {"${context.*} · ${run.*} · ${env.*} · ${upstream.*}"}
        </span>
      </div>

      {contextNames.length > 0 && (
        <div className="field variables-context">
          <label>Job Context</label>
          <select
            value={active}
            onChange={(e) => setActive(e.target.value)}
            data-testid="context-select"
          >
            {contextNames.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
          <div className="field-help">
            Named DEV/QA/PROD sets on this pipeline. Switch without editing SQL.
          </div>
        </div>
      )}

      {contextNames.length === 0 && (
        <p className="empty-hint variables-empty">
          Open <strong>Job Contexts</strong> in the right rail to add DEV/QA/PROD parameters for this
          pipeline.
        </p>
      )}

      {rows.length === 0 ? (
        <p className="empty-hint">{"No ${…} refs in SQL / params yet."}</p>
      ) : (
        <table className="variables-table" data-testid="variables-table">
          <thead>
            <tr>
              <th>Key</th>
              <th>Value</th>
              <th>Source</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key} className={r.resolved ? "" : "unresolved"}>
                <td>
                  <code>${`{${r.key}}`}</code>
                </td>
                <td>{r.resolved ? r.value : "—"}</td>
                <td>{r.source}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <button
        type="button"
        className="btn-link"
        onClick={() => setPreviewOpen((v) => !v)}
        data-testid="toggle-resolved-preview"
      >
        {previewOpen ? "▾ Resolved preview" : "▸ Resolved preview"}
      </button>
      {previewOpen && (
        <div className="variables-preview" data-testid="resolved-preview">
          {resolvedSql ? (
            <>
              <div className="field-help">Resolved SQL (active context: {active || "—"})</div>
              <pre className="resolved-sql">{resolvedSql}</pre>
            </>
          ) : null}
          {resolvedParams.length > 0 ? (
            <>
              <div className="field-help">Resolved param lines</div>
              <pre className="resolved-sql">{resolvedParams.join("\n")}</pre>
            </>
          ) : null}
          {!resolvedSql && resolvedParams.length === 0 ? (
            <p className="empty-hint">Nothing to preview.</p>
          ) : null}
        </div>
      )}
    </div>
  );
}
