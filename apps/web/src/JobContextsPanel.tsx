import { useEffect, useMemo, useRef, useState } from "react";
import {
  addContextSet,
  contextEntriesToRows,
  deleteContextSet,
  duplicateContextSet,
  ensureContextsMetadata,
  parseContexts,
  renameContextSet,
  rowsToContextEntries,
  setActiveContext,
  setContextEntries,
  setRunParam,
} from "./vars";

type Props = {
  pipelineId?: string;
  metadata?: Record<string, unknown> | null;
  onMetadataChange: (metadata: Record<string, unknown>) => void;
};

function hasContextSets(metadata?: Record<string, unknown> | null): boolean {
  const block = metadata?.contexts;
  if (!block || typeof block !== "object" || Array.isArray(block)) return false;
  const sets = (block as { sets?: unknown }).sets;
  if (!sets || typeof sets !== "object" || Array.isArray(sets)) return false;
  return Object.keys(sets as Record<string, unknown>).length > 0;
}

type KvRow = { key: string; value: string };

function ContextKvTable({
  setName,
  entries,
  onCommit,
}: {
  setName: string;
  entries: Record<string, unknown>;
  onCommit: (entries: Record<string, unknown>) => void;
}) {
  const [rows, setRows] = useState<KvRow[]>(() => contextEntriesToRows(entries));

  const commitRows = (nextRows: KvRow[]) => {
    setRows(nextRows);
    onCommit(rowsToContextEntries(nextRows));
  };

  return (
    <>
      <label className="field-label">Parameters ({setName})</label>
      <table className="contexts-table" data-testid="job-context-kv-table">
        <thead>
          <tr>
            <th>Key</th>
            <th>Value</th>
            <th aria-label="Actions" />
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`row-${index}`}>
              <td>
                <input
                  className="contexts-input"
                  value={row.key}
                  onChange={(e) => {
                    const next = rows.map((r, i) => (i === index ? { ...r, key: e.target.value } : r));
                    commitRows(next);
                  }}
                  placeholder="key"
                  data-testid={`context-key-${index}`}
                  aria-label={`Context key ${index + 1}`}
                />
              </td>
              <td>
                <input
                  className="contexts-input"
                  value={row.value}
                  onChange={(e) => {
                    const next = rows.map((r, i) =>
                      i === index ? { ...r, value: e.target.value } : r,
                    );
                    commitRows(next);
                  }}
                  placeholder="param value"
                  data-testid={`context-value-${index}`}
                  aria-label={`Context value ${index + 1}`}
                />
              </td>
              <td>
                <button
                  type="button"
                  className="btn-link contexts-row-delete"
                  onClick={() => commitRows(rows.filter((_, i) => i !== index))}
                  data-testid={`context-delete-row-${index}`}
                  aria-label={`Delete row ${index + 1}`}
                >
                  ✕
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button
        type="button"
        className="btn btn-sm"
        onClick={() => commitRows([...rows, { key: "", value: "" }])}
        data-testid="context-add-row"
      >
        Add row
      </button>
    </>
  );
}

/**
 * Pipeline-level Job Contexts editor (DEV/QA/PROD key–value sets + run_params).
 * Shares the same metadata.contexts / metadata.run_params as VariablesPanel.
 */
export function JobContextsPanel({ pipelineId, metadata, onMetadataChange }: Props) {
  const seeded = useMemo(() => ensureContextsMetadata(metadata), [metadata]);
  const { active, sets } = useMemo(() => parseContexts(seeded), [seeded]);
  const contextNames = useMemo(() => Object.keys(sets), [sets]);
  const activeSet = sets[active] || {};

  const [newSetName, setNewSetName] = useState("");
  const [renameTo, setRenameTo] = useState(active);
  const [renameActive, setRenameActive] = useState(active);
  const seededForPipeline = useRef<string | null>(null);

  if (active !== renameActive) {
    setRenameActive(active);
    setRenameTo(active);
  }

  // Seed empty contexts into pipeline state once per pipeline (so Save persists defaults).
  useEffect(() => {
    const id = pipelineId || "_";
    if (hasContextSets(metadata)) {
      seededForPipeline.current = id;
      return;
    }
    if (seededForPipeline.current === id) return;
    seededForPipeline.current = id;
    onMetadataChange(ensureContextsMetadata(metadata));
  }, [pipelineId, metadata, onMetadataChange]);

  const runParams =
    seeded.run_params && typeof seeded.run_params === "object" && !Array.isArray(seeded.run_params)
      ? (seeded.run_params as Record<string, unknown>)
      : {};

  const onActiveChange = (name: string) => {
    onMetadataChange(setActiveContext(seeded, name));
  };

  const onAddSet = () => {
    const name = newSetName.trim() || `CTX_${contextNames.length + 1}`;
    onMetadataChange(addContextSet(seeded, name));
    setNewSetName("");
  };

  const onDuplicate = () => {
    const base = `${active}_copy`;
    let name = base;
    let n = 2;
    while (sets[name]) {
      name = `${base}${n}`;
      n += 1;
    }
    onMetadataChange(duplicateContextSet(seeded, active, name));
  };

  const onRename = () => {
    const next = renameTo.trim();
    if (!next || next === active) return;
    onMetadataChange(renameContextSet(seeded, active, next));
  };

  const onDeleteSet = () => {
    onMetadataChange(deleteContextSet(seeded, active));
  };

  const onRunParam = (key: string, value: string) => {
    onMetadataChange(setRunParam(seeded, key, value));
  };

  return (
    <div className="contexts-form" data-testid="job-contexts-panel">
      <p className="schedule-note contexts-help">
        Environment parameters for this pipeline. Use{" "}
        <code>{"${context.key}"}</code> in Databricks SQL / Job params and Child pipelines via{" "}
        <strong>Run Pipeline</strong> with context mode <code>inherit</code>. Tokens stay in
        Connections / secrets — never inherited across Master → Child.
      </p>

      <label className="field-label">Active context</label>
      <select
        className="schedule-input"
        value={active}
        onChange={(e) => onActiveChange(e.target.value)}
        data-testid="job-context-select"
      >
        {contextNames.map((name) => (
          <option key={name} value={name}>
            {name}
          </option>
        ))}
      </select>

      <ContextKvTable
        key={active}
        setName={active}
        entries={activeSet}
        onCommit={(entries) => onMetadataChange(setContextEntries(seeded, active, entries))}
      />

      <div className="contexts-set-actions">
        <label className="field-label">Add context set</label>
        <div className="contexts-inline">
          <input
            className="schedule-input"
            value={newSetName}
            onChange={(e) => setNewSetName(e.target.value)}
            placeholder="e.g. STAGING"
            data-testid="context-new-set-name"
          />
          <button type="button" className="btn btn-sm" onClick={onAddSet} data-testid="context-add-set">
            Add
          </button>
        </div>
        <div className="contexts-inline contexts-inline-wrap">
          <button type="button" className="btn btn-sm" onClick={onDuplicate} data-testid="context-duplicate-set">
            Duplicate set
          </button>
          <button
            type="button"
            className="btn btn-sm"
            onClick={onDeleteSet}
            data-testid="context-delete-set"
            title="Delete the active set (reseeds DEV/QA/PROD if none remain)"
          >
            Delete set
          </button>
        </div>
        <label className="field-label">Rename active set</label>
        <div className="contexts-inline">
          <input
            className="schedule-input"
            value={renameTo}
            onChange={(e) => setRenameTo(e.target.value)}
            data-testid="context-rename-input"
          />
          <button type="button" className="btn btn-sm" onClick={onRename} data-testid="context-rename-set">
            Rename
          </button>
        </div>
      </div>

      <label className="field-label">Run params</label>
      <p className="schedule-note" style={{ marginTop: 0 }}>
        Available as <code>{"${run.run_date}"}</code> / <code>{"${run.job_name}"}</code> (and bare{" "}
        <code>{"${run_date}"}</code> via merged params).
      </p>
      <label className="field-label">run_date</label>
      <input
        className="schedule-input"
        value={runParams.run_date == null ? "" : String(runParams.run_date)}
        onChange={(e) => onRunParam("run_date", e.target.value)}
        placeholder="YYYY-MM-DD"
        data-testid="run-param-run-date"
      />
      <label className="field-label">job_name</label>
      <input
        className="schedule-input"
        value={runParams.job_name == null ? "" : String(runParams.job_name)}
        onChange={(e) => onRunParam("job_name", e.target.value)}
        placeholder="optional job label"
        data-testid="run-param-job-name"
      />
    </div>
  );
}
