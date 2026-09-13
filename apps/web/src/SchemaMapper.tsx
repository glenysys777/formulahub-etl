import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { api, type PipelineEdge, type PipelineNode, type SchemaDiscoverResult } from "./api";

export type MappingRow = {
  id: string;
  source: string;
  target: string;
  type: string;
};

type Props = {
  open: boolean;
  onClose: () => void;
  componentType: string;
  nodeId: string;
  config: Record<string, unknown>;
  nodes: PipelineNode[];
  edges: PipelineEdge[];
  onApply: (config: Record<string, unknown>) => void;
};

type Col = { name: string; type: string; required?: boolean };

type LinkPath = {
  id: string;
  d: string;
  source: string;
  target: string;
};

function uid() {
  return `m_${Math.random().toString(36).slice(2, 9)}`;
}

function isIdent(name: string): boolean {
  return /^[A-Za-z_][A-Za-z0-9_]*$/.test(name);
}

function uiComponentLabel(type: string, label?: string | null): string {
  if (type === "tmap") return label && !/tmap/i.test(label) ? label : "Field Mapper";
  if (type === "column_map") return label || "Schema Map";
  return label || type;
}

/** Parse column_map "old:new" or tmap "out=expr" into mapping rows. */
export function parseExistingMappings(
  componentType: string,
  config: Record<string, unknown>,
): MappingRow[] {
  const raw = config.mappings ?? config.rename;
  const lines: string[] = [];
  if (raw && typeof raw === "object" && !Array.isArray(raw)) {
    return Object.entries(raw as Record<string, string>).map(([k, v]) => ({
      id: uid(),
      source: componentType === "tmap" ? String(v) : String(k),
      target: componentType === "tmap" ? String(k) : String(v),
      type: "string",
    }));
  }
  if (typeof raw === "string") {
    lines.push(...raw.split(/\n/).map((s) => s.trim()).filter(Boolean));
  } else if (Array.isArray(raw)) {
    lines.push(...raw.map(String).map((s) => s.trim()).filter(Boolean));
  }

  const rows: MappingRow[] = [];
  for (const line of lines) {
    if (componentType === "tmap") {
      let out = "";
      let expr = "";
      if (line.includes("=")) {
        [out, expr] = line.split("=", 2);
      } else if (line.includes(":")) {
        [out, expr] = line.split(":", 2);
      } else continue;
      out = out.trim();
      expr = expr.trim();
      let source = expr;
      const colMatch = expr.match(/^col\(\s*["']([^"']+)["']\s*\)$/);
      if (colMatch) source = colMatch[1];
      else if (isIdent(expr)) source = expr;
      // Keep complex expressions (int(col("X")), upper(...)) intact for round-trip
      rows.push({ id: uid(), source, target: out, type: "string" });
    } else {
      let sep: string | null = null;
      for (const c of [":", "→", "->", "="]) {
        if (line.includes(c)) {
          sep = c;
          break;
        }
      }
      if (!sep) continue;
      const [old, neu] = line.split(sep, 2);
      if (old?.trim() && neu?.trim()) {
        rows.push({ id: uid(), source: old.trim(), target: neu.trim(), type: "string" });
      }
    }
  }
  return rows;
}

function mappingsToConfig(
  componentType: string,
  rows: MappingRow[],
  prev: Record<string, unknown>,
): Record<string, unknown> {
  if (componentType === "tmap") {
    const mappings = rows
      .filter((r) => r.target.trim())
      .map((r) => {
        const tgt = r.target.trim();
        const src = r.source.trim();
        if (!src) return `${tgt}=None`;
        const looksExpr =
          /[()*+\-/]|col\s*\(/.test(src) ||
          /\b(upper|lower|int|float|str|coalesce|len|abs|round)\s*\(/.test(src);
        if (looksExpr) return `${tgt}=${src}`;
        if (isIdent(src)) return `${tgt}=${src}`;
        return `${tgt}=col(${JSON.stringify(src)})`;
      });
    return { ...prev, mappings };
  }
  const mappings = rows
    .filter((r) => r.source.trim() && r.target.trim())
    .map((r) => `${r.source.trim()}:${r.target.trim()}`);
  return { ...prev, mappings };
}

function findUpstreamSource(
  nodeId: string,
  nodes: PipelineNode[],
  edges: PipelineEdge[],
): PipelineNode | null {
  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
  const SOURCE_TYPES = new Set([
    "excel_source",
    "local_file_source",
    "http_api_source",
    "s3_source",
    "sqlite_source",
    "postgres_source",
    "mysql_source",
    "sftp_source",
    "csv_parser",
  ]);
  const queue = [nodeId];
  const seen = new Set<string>();
  while (queue.length) {
    const cur = queue.shift()!;
    if (seen.has(cur)) continue;
    seen.add(cur);
    const incoming = edges.filter((e) => e.target === cur);
    for (const e of incoming) {
      const n = byId[e.source];
      if (!n) continue;
      if (SOURCE_TYPES.has(n.type) || n.type.endsWith("_source")) {
        return n;
      }
      queue.push(n.id);
    }
  }
  return null;
}


function extractSourceCol(source: string): string {
  const simple = source.match(/^col\(\s*["']([^"']+)["']\s*\)$/);
  if (simple) return simple[1];
  const nested = source.match(/col\(\s*["']([^"']+)["']\s*\)/);
  if (nested) return nested[1];
  if (isIdent(source)) return source;
  return source;
}

function slugifyTarget(name: string): string {
  return name
    .trim()
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .replace(/[^A-Za-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .toLowerCase();
}

function bezierPath(x1: number, y1: number, x2: number, y2: number): string {
  const dx = Math.max(48, Math.abs(x2 - x1) * 0.45);
  return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
}

export function SchemaMapper({
  open,
  onClose,
  componentType,
  nodeId,
  config,
  nodes,
  edges,
  onApply,
}: Props) {
  const [sourceCols, setSourceCols] = useState<Col[]>([]);
  const [rows, setRows] = useState<MappingRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [sourceQuery, setSourceQuery] = useState("");
  const [targetQuery, setTargetQuery] = useState("");
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [dragSource, setDragSource] = useState<string | null>(null);
  const [draft, setDraft] = useState<{ x1: number; y1: number; x2: number; y2: number } | null>(
    null,
  );
  const [paths, setPaths] = useState<LinkPath[]>([]);
  const [selectedPathId, setSelectedPathId] = useState<string | null>(null);

  const bodyRef = useRef<HTMLDivElement>(null);
  const sourcePaneRef = useRef<HTMLDivElement>(null);
  const targetPaneRef = useRef<HTMLDivElement>(null);
  const sourceHandleRefs = useRef<Map<string, HTMLButtonElement>>(new Map());
  const targetHandleRefs = useRef<Map<string, HTMLButtonElement>>(new Map());

  const initFromConfig = useCallback(() => {
    const parsed = parseExistingMappings(componentType, config);
    setRows(parsed);
    // Seed source columns from existing mappings so arrows are visible without Discover
    const seeded: Col[] = [];
    const seen = new Set<string>();
    for (const r of parsed) {
      const colName = extractSourceCol(r.source);
      if (colName && !seen.has(colName)) {
        seen.add(colName);
        seeded.push({ name: colName, type: r.type || "string" });
      }
    }
    if (seeded.length) setSourceCols(seeded);
  }, [componentType, config]);

  useEffect(() => {
    if (open) {
      initFromConfig();
      setError(null);
      setInfo(null);
      setSourceQuery("");
      setTargetQuery("");
      setHoverId(null);
      setDragSource(null);
      setDraft(null);
      setSelectedPathId(null);
    }
  }, [open, initFromConfig]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      const tag = el?.tagName;
      const editing =
        tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || Boolean(el?.isContentEditable);
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }
      if ((e.key === "Delete" || e.key === "Backspace") && selectedPathId && !editing) {
        e.preventDefault();
        setRows((prev) => prev.filter((r) => r.id !== selectedPathId));
        setSelectedPathId(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose, selectedPathId]);

  const applyDiscover = (result: SchemaDiscoverResult) => {
    const cols = result.columns.map((c) => ({
      name: c.name,
      type: c.type,
      required: c.nullable === false,
    }));
    setSourceCols(cols);
    setInfo(`Discovered ${cols.length} columns`);
    setRows((prev) => {
      if (prev.length > 0) return prev;
      return cols.map((c) => ({
        id: uid(),
        source: c.name,
        target: slugifyTarget(c.name),
        type: c.type,
      }));
    });
  };

  const discoverUpstream = async () => {
    setBusy(true);
    setError(null);
    try {
      const upstream = findUpstreamSource(nodeId, nodes, edges);
      if (!upstream) {
        setError("No upstream source found. Connect a source node, or discover on the source first.");
        return;
      }
      const stored = upstream.config?.discovered_schema as SchemaDiscoverResult | undefined;
      if (stored?.columns?.length) {
        applyDiscover(stored);
        setInfo(`Loaded schema from ${uiComponentLabel(upstream.type, upstream.label)}`);
        return;
      }
      const result = await api.discoverSchema(upstream.type, upstream.config || {});
      applyDiscover(result);
      setInfo(`Discovered from ${uiComponentLabel(upstream.type, upstream.label)}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const autoMapByName = () => {
    const srcNames = sourceCols.map((c) => c.name);
    if (!srcNames.length && rows.length) {
      setRows((prev) =>
        prev.map((r) => (r.target ? r : { ...r, target: slugifyTarget(r.source) })),
      );
      return;
    }
    const byLower = new Map(srcNames.map((n) => [n.toLowerCase(), n]));
    const bySlug = new Map(srcNames.map((n) => [slugifyTarget(n), n]));
    setRows((prev) => {
      if (prev.length === 0) {
        return sourceCols.map((c) => ({
          id: uid(),
          source: c.name,
          target: slugifyTarget(c.name),
          type: c.type,
        }));
      }
      // Ensure every source has a mapping
      const next = [...prev];
      const mappedSrc = new Set(next.map((r) => r.source).filter(Boolean));
      for (const c of sourceCols) {
        if (!mappedSrc.has(c.name)) {
          next.push({
            id: uid(),
            source: c.name,
            target: slugifyTarget(c.name),
            type: c.type,
          });
        }
      }
      return next.map((r) => {
        if (r.source && byLower.has(r.target.toLowerCase())) {
          return { ...r, source: byLower.get(r.target.toLowerCase())! };
        }
        if (!r.source && bySlug.has(slugifyTarget(r.target))) {
          return { ...r, source: bySlug.get(slugifyTarget(r.target))! };
        }
        const exact = srcNames.find((n) => n === r.target || slugifyTarget(n) === r.target);
        if (exact && !r.source) return { ...r, source: exact };
        if (!r.target && r.source) return { ...r, target: slugifyTarget(r.source) };
        return r;
      });
    });
  };

  const clearMappings = () => {
    setRows([]);
    setSelectedPathId(null);
  };

  const addTarget = () => {
    setRows((prev) => [
      ...prev,
      { id: uid(), source: "", target: `col_${prev.length + 1}`, type: "string" },
    ]);
  };

  const removeRow = (id: string) => {
    setRows((prev) => prev.filter((r) => r.id !== id));
    setSelectedPathId((cur) => (cur === id ? null : cur));
  };

  const updateRow = (id: string, patch: Partial<MappingRow>) => {
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  };

  const linkSourceToTarget = (sourceName: string, targetRowId: string) => {
    const col = sourceCols.find((c) => c.name === sourceName);
    setRows((prev) =>
      prev.map((r) =>
        r.id === targetRowId
          ? { ...r, source: sourceName, type: col?.type || r.type || "string" }
          : r,
      ),
    );
  };

  const linkSourceCreate = (sourceName: string) => {
    const col = sourceCols.find((c) => c.name === sourceName);
    setRows((prev) => {
      // If a target already exists with slug name and empty source, fill it
      const slug = slugifyTarget(sourceName);
      const empty = prev.find((r) => !r.source && (r.target === slug || !r.target));
      if (empty) {
        return prev.map((r) =>
          r.id === empty.id
            ? { ...r, source: sourceName, target: r.target || slug, type: col?.type || "string" }
            : r,
        );
      }
      // Avoid duplicate source→same target
      if (prev.some((r) => r.source === sourceName && r.target === slug)) return prev;
      return [
        ...prev,
        {
          id: uid(),
          source: sourceName,
          target: slug,
          type: col?.type || "string",
        },
      ];
    });
  };

  const handleApply = () => {
    const next = mappingsToConfig(componentType, rows, config);
    onApply(next);
    onClose();
  };

  const mappedSources = useMemo(
    () => new Set(rows.map((r) => extractSourceCol(r.source)).filter(Boolean)),
    [rows],
  );

  const filteredSources = useMemo(() => {
    const q = sourceQuery.trim().toLowerCase();
    if (!q) return sourceCols;
    return sourceCols.filter(
      (c) => c.name.toLowerCase().includes(q) || c.type.toLowerCase().includes(q),
    );
  }, [sourceCols, sourceQuery]);

  const filteredRows = useMemo(() => {
    const q = targetQuery.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter(
      (r) =>
        r.target.toLowerCase().includes(q) ||
        r.source.toLowerCase().includes(q) ||
        r.type.toLowerCase().includes(q),
    );
  }, [rows, targetQuery]);

  const recomputePaths = useCallback(() => {
    const body = bodyRef.current;
    if (!body) {
      setPaths([]);
      return;
    }
    const br = body.getBoundingClientRect();
    const next: LinkPath[] = [];
    for (const r of rows) {
      if (!r.source || !r.target) continue;
      // Only draw if both ends are currently visible in filtered lists
      const srcKey = extractSourceCol(r.source);
      const srcEl = sourceHandleRefs.current.get(srcKey);
      const tgtEl = targetHandleRefs.current.get(r.id);
      if (!srcEl || !tgtEl) continue;
      const sr = srcEl.getBoundingClientRect();
      const tr = tgtEl.getBoundingClientRect();
      const x1 = sr.left + sr.width / 2 - br.left;
      const y1 = sr.top + sr.height / 2 - br.top;
      const x2 = tr.left + tr.width / 2 - br.left;
      const y2 = tr.top + tr.height / 2 - br.top;
      next.push({
        id: r.id,
        source: srcKey,
        target: r.target,
        d: bezierPath(x1, y1, x2, y2),
      });
    }
    setPaths(next);
  }, [rows]);

  useLayoutEffect(() => {
    if (!open) return;
    recomputePaths();
  }, [open, recomputePaths, filteredSources, filteredRows, sourceCols]);

  useEffect(() => {
    if (!open) return;
    const onResize = () => recomputePaths();
    window.addEventListener("resize", onResize);
    const srcPane = sourcePaneRef.current;
    const tgtPane = targetPaneRef.current;
    srcPane?.addEventListener("scroll", onResize, { passive: true });
    tgtPane?.addEventListener("scroll", onResize, { passive: true });
    // Recompute after fonts/layout settle
    const t = window.setTimeout(recomputePaths, 50);
    const t2 = window.setTimeout(recomputePaths, 200);
    return () => {
      window.removeEventListener("resize", onResize);
      srcPane?.removeEventListener("scroll", onResize);
      tgtPane?.removeEventListener("scroll", onResize);
      window.clearTimeout(t);
      window.clearTimeout(t2);
    };
  }, [open, recomputePaths]);

  useEffect(() => {
    if (!dragSource) return;
    const onMove = (e: MouseEvent) => {
      const body = bodyRef.current;
      if (!body) return;
      const br = body.getBoundingClientRect();
      const srcEl = sourceHandleRefs.current.get(dragSource);
      if (!srcEl) return;
      const sr = srcEl.getBoundingClientRect();
      setDraft({
        x1: sr.left + sr.width / 2 - br.left,
        y1: sr.top + sr.height / 2 - br.top,
        x2: e.clientX - br.left,
        y2: e.clientY - br.top,
      });
    };
    const onUp = (e: MouseEvent) => {
      const el = document.elementFromPoint(e.clientX, e.clientY) as HTMLElement | null;
      const handle = el?.closest("[data-target-handle]") as HTMLElement | null;
      if (handle) {
        const rowId = handle.getAttribute("data-target-handle");
        if (rowId) linkSourceToTarget(dragSource, rowId);
      } else {
        const pane = el?.closest(".sm-target-pane");
        if (pane) linkSourceCreate(dragSource);
      }
      setDragSource(null);
      setDraft(null);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [dragSource]);

  if (!open) return null;

  const activeHover = hoverId || selectedPathId;
  const hoverRow = rows.find((r) => r.id === activeHover);

  return (
    <div className="schema-mapper-overlay" role="dialog" aria-modal="true">
      <div className="schema-mapper-modal">
        <header className="schema-mapper-header">
          <div>
            <h2>Field Mapper</h2>
            <p className="schema-mapper-sub">
              Map source columns to targets · drag handles · Delete removes a link · Esc closes
            </p>
          </div>
          <button type="button" className="btn" onClick={onClose}>
            Close
          </button>
        </header>

        <div className="schema-mapper-toolbar">
          <button
            type="button"
            className="btn"
            disabled={busy}
            onClick={discoverUpstream}
            data-testid="discover-upstream"
          >
            {busy ? "Discovering…" : "Discover"}
          </button>
          <button type="button" className="btn" onClick={autoMapByName}>
            Auto-map
          </button>
          <button type="button" className="btn" onClick={addTarget}>
            Add target
          </button>
          <button type="button" className="btn" onClick={clearMappings}>
            Clear
          </button>
          <div className="schema-mapper-spacer" />
          <span className="sm-map-count">
            {rows.filter((r) => r.source && r.target).length} links
          </span>
          <button
            type="button"
            className="btn btn-run"
            onClick={handleApply}
            data-testid="apply-mappings"
          >
            Apply
          </button>
        </div>

        {error && <div className="schema-mapper-error">{error}</div>}
        {info && !error && <div className="schema-mapper-info">{info}</div>}

        <div className="schema-mapper-body" ref={bodyRef}>
          <svg className="sm-links-svg" aria-hidden>
            {paths.map((p) => {
              const active = activeHover === p.id;
              const dimmed = activeHover && !active;
              return (
                <g key={p.id}>
                  <path
                    d={p.d}
                    className={`sm-link-hit${active ? " active" : ""}`}
                    onMouseEnter={() => setHoverId(p.id)}
                    onMouseLeave={() => setHoverId((id) => (id === p.id ? null : id))}
                    onClick={() =>
                      setSelectedPathId((cur) => (cur === p.id ? null : p.id))
                    }
                    onDoubleClick={(e) => {
                      e.preventDefault();
                      removeRow(p.id);
                    }}
                  />
                  <path
                    d={p.d}
                    className={`sm-link${active ? " active" : ""}${dimmed ? " dimmed" : ""}`}
                    markerEnd={active ? "url(#sm-arrow-active)" : "url(#sm-arrow)"}
                  />
                </g>
              );
            })}
            {draft && (
              <path
                d={bezierPath(draft.x1, draft.y1, draft.x2, draft.y2)}
                className="sm-link draft"
                markerEnd="url(#sm-arrow-active)"
              />
            )}
            <defs>
              <marker
                id="sm-arrow"
                viewBox="0 0 10 10"
                refX="9"
                refY="5"
                markerWidth="6"
                markerHeight="6"
                orient="auto-start-reverse"
              >
                <path d="M 0 0 L 10 5 L 0 10 z" fill="#0071e3" />
              </marker>
              <marker
                id="sm-arrow-active"
                viewBox="0 0 10 10"
                refX="9"
                refY="5"
                markerWidth="6"
                markerHeight="6"
                orient="auto-start-reverse"
              >
                <path d="M 0 0 L 10 5 L 0 10 z" fill="#0071e3" />
              </marker>
            </defs>
          </svg>

          <div className="sm-pane sm-source-pane" ref={sourcePaneRef}>
            <div className="sm-pane-label sticky">
              <span className="sm-pane-badge source">Source</span>
              <span className="sm-pane-meta">{filteredSources.length} columns</span>
            </div>
            <div className="sm-search">
              <input
                type="search"
                placeholder="Search source…"
                value={sourceQuery}
                onChange={(e) => setSourceQuery(e.target.value)}
                aria-label="Filter source columns"
              />
            </div>
            {filteredSources.length === 0 ? (
              <div className="sm-empty">
                <div className="sm-empty-icon">◎</div>
                <p>No source columns yet</p>
                <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={discoverUpstream}>
                  Discover upstream schema
                </button>
              </div>
            ) : (
              <ul className="sm-col-list">
                {filteredSources.map((c) => {
                  const mapped = mappedSources.has(c.name);
                  const linked =
                    (hoverRow && extractSourceCol(hoverRow.source) === c.name) ||
                    dragSource === c.name;
                  return (
                    <li
                      key={c.name}
                      className={`sm-col-row source${mapped ? " mapped" : " unmapped"}${linked ? " linked" : ""}`}
                      onMouseEnter={() => {
                        const row = rows.find((r) => extractSourceCol(r.source) === c.name);
                        if (row) setHoverId(row.id);
                      }}
                      onMouseLeave={() => setHoverId(null)}
                    >
                      <div className="sm-col-main">
                        <span className="sm-col-name">{c.name}</span>
                        <div className="sm-col-meta">
                          <span className="sm-type-chip">{c.type}</span>
                          {c.required && <span className="sm-required" title="Required">*</span>}
                        </div>
                      </div>
                      <button
                        type="button"
                        className={`sm-handle source${mapped ? " on" : ""}${dragSource === c.name ? " dragging" : ""}`}
                        title="Drag to a target column"
                        aria-label={`Connect ${c.name}`}
                        ref={(el) => {
                          if (el) sourceHandleRefs.current.set(c.name, el);
                          else sourceHandleRefs.current.delete(c.name);
                        }}
                        onMouseDown={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                          setDragSource(c.name);
                          setSelectedPathId(null);
                        }}
                      />
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          <div className="sm-center-gap" aria-hidden />

          <div className="sm-pane sm-target-pane" ref={targetPaneRef}>
            <div className="sm-pane-label sticky">
              <span className="sm-pane-badge target">Target</span>
              <span className="sm-pane-meta">{filteredRows.length} columns</span>
            </div>
            <div className="sm-search">
              <input
                type="search"
                placeholder="Search target…"
                value={targetQuery}
                onChange={(e) => setTargetQuery(e.target.value)}
                aria-label="Filter target columns"
              />
            </div>
            {filteredRows.length === 0 ? (
              <div className="sm-empty">
                <div className="sm-empty-icon">◎</div>
                <p>No target mappings</p>
                <button type="button" className="btn btn-primary btn-sm" onClick={autoMapByName}>
                  Auto-map by name
                </button>
              </div>
            ) : (
              <ul className="sm-col-list">
                {filteredRows.map((r) => {
                  const linked = activeHover === r.id;
                  return (
                    <li
                      key={r.id}
                      className={`sm-col-row target${r.source ? " mapped" : ""}${linked ? " linked" : ""}`}
                      onMouseEnter={() => setHoverId(r.id)}
                      onMouseLeave={() => setHoverId(null)}
                    >
                      <button
                        type="button"
                        className={`sm-handle target${r.source ? " on" : ""}`}
                        data-target-handle={r.id}
                        title="Drop a source connection here"
                        aria-label={`Target handle for ${r.target || "unnamed"}`}
                        ref={(el) => {
                          if (el) targetHandleRefs.current.set(r.id, el);
                          else targetHandleRefs.current.delete(r.id);
                        }}
                      />
                      <div className="sm-col-main">
                        <input
                          className="sm-target-input"
                          value={r.target}
                          onChange={(e) => updateRow(r.id, { target: e.target.value })}
                          placeholder="target name"
                          aria-label="Target column name"
                        />
                        <div className="sm-col-meta">
                          {r.source ? (
                            <span className="sm-from" title={r.source}>
                              ← {extractSourceCol(r.source)}
                            </span>
                          ) : (
                            <span className="sm-from muted">unlinked</span>
                          )}
                          <select
                            className="sm-type-select"
                            value={r.type}
                            onChange={(e) => updateRow(r.id, { type: e.target.value })}
                            aria-label="Target type"
                          >
                            {["string", "int", "float", "boolean", "date"].map((t) => (
                              <option key={t} value={t}>
                                {t}
                              </option>
                            ))}
                          </select>
                          <button
                            type="button"
                            className="btn-icon"
                            title="Delete mapping"
                            onClick={() => removeRow(r.id)}
                          >
                            ×
                          </button>
                        </div>
                        {(selectedPathId === r.id || linked) && (
                          <input
                            className="sm-expr-input"
                            value={r.source}
                            onChange={(e) => updateRow(r.id, { source: e.target.value })}
                            placeholder='expression e.g. upper(col("Name"))'
                            aria-label="Mapping expression"
                            title="Edit source expression"
                          />
                        )}
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>

        {selectedPathId && (
          <div className="sm-link-actions">
            <span>
              Selected link — Delete key or double-click arrow to remove, or
            </span>
            <button type="button" className="btn btn-sm" onClick={() => removeRow(selectedPathId)}>
              Delete link
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
