import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { api, type PipelineEdge, type PipelineNode, type SchemaDiscoverResult } from "./api";
import { MAPPER_FUNCTION_GROUPS } from "./mapperFunctions";

export type MappingRow = {
  id: string;
  source: string;
  target: string;
  type: string;
};

export type VariableRow = {
  id: string;
  name: string;
  expr: string;
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
  kind: "in-out" | "in-var" | "var-out";
};

type DragKind = "input" | "var";

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

/** Parse column_map "old:new" or Field Mapper "out=expr" into mapping rows. */
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

export function parseExistingVariables(config: Record<string, unknown>): VariableRow[] {
  const raw = config.variables;
  if (!raw) return [];
  const items: unknown[] = [];
  if (typeof raw === "string") {
    items.push(...raw.split(/\n/).map((s) => s.trim()).filter(Boolean));
  } else if (Array.isArray(raw)) {
    items.push(...raw);
  } else if (typeof raw === "object") {
    const obj = raw as Record<string, unknown>;
    if ("name" in obj && ("expr" in obj || "expression" in obj)) {
      items.push(obj);
    } else {
      for (const [k, v] of Object.entries(obj)) {
        items.push({ name: k, expr: String(v) });
      }
    }
  }

  const rows: VariableRow[] = [];
  for (const item of items) {
    if (item && typeof item === "object" && !Array.isArray(item)) {
      const o = item as Record<string, unknown>;
      const name = String(o.name || o.key || "").trim();
      const expr = String(o.expr || o.expression || o.value || "").trim();
      if (name && expr) rows.push({ id: uid(), name, expr });
      continue;
    }
    const line = String(item).trim();
    if (!line) continue;
    let name = "";
    let expr = "";
    if (line.includes("=")) [name, expr] = line.split("=", 2);
    else if (line.includes(":")) [name, expr] = line.split(":", 2);
    else continue;
    name = name.trim();
    expr = expr.trim();
    if (name && expr) rows.push({ id: uid(), name, expr });
  }
  return rows;
}

function mappingsToConfig(
  componentType: string,
  rows: MappingRow[],
  variables: VariableRow[],
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
    const vars = variables
      .filter((v) => v.name.trim() && v.expr.trim())
      .map((v) => `${v.name.trim()}=${v.expr.trim()}`);
    const next: Record<string, unknown> = { ...prev, mappings };
    if (vars.length) next.variables = vars;
    else delete next.variables;
    return next;
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

/** Column / ident names referenced by a simple expression (best-effort for arrows). */
function referencedIdents(expr: string): string[] {
  const s = expr.trim();
  if (!s) return [];
  const out: string[] = [];
  const colRe = /col\(\s*["']([^"']+)["']\s*\)/g;
  let m: RegExpExecArray | null;
  while ((m = colRe.exec(s))) out.push(m[1]);
  if (isIdent(s)) out.push(s);
  else {
    const idRe = /\b([A-Za-z_][A-Za-z0-9_]*)\b/g;
    const reserved = new Set([
      "upper",
      "lower",
      "str",
      "int",
      "float",
      "len",
      "coalesce",
      "abs",
      "round",
      "min",
      "max",
      "col",
      "row",
      "True",
      "False",
      "None",
      "and",
      "or",
      "not",
      "in",
      "if",
      "else",
    ]);
    while ((m = idRe.exec(s))) {
      if (!reserved.has(m[1])) out.push(m[1]);
    }
  }
  return [...new Set(out)];
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
  const isFieldMapper = componentType === "tmap";
  const [sourceCols, setSourceCols] = useState<Col[]>([]);
  const [rows, setRows] = useState<MappingRow[]>([]);
  const [variables, setVariables] = useState<VariableRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [sourceQuery, setSourceQuery] = useState("");
  const [varQuery, setVarQuery] = useState("");
  const [targetQuery, setTargetQuery] = useState("");
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [drag, setDrag] = useState<{ kind: DragKind; key: string } | null>(null);
  const [draft, setDraft] = useState<{ x1: number; y1: number; x2: number; y2: number } | null>(
    null,
  );
  const [paths, setPaths] = useState<LinkPath[]>([]);
  const [selectedPathId, setSelectedPathId] = useState<string | null>(null);
  const [fnHelpOpen, setFnHelpOpen] = useState(true);

  const bodyRef = useRef<HTMLDivElement>(null);
  const sourcePaneRef = useRef<HTMLDivElement>(null);
  const varPaneRef = useRef<HTMLDivElement>(null);
  const targetPaneRef = useRef<HTMLDivElement>(null);
  const sourceHandleRefs = useRef<Map<string, HTMLButtonElement>>(new Map());
  const varInHandleRefs = useRef<Map<string, HTMLButtonElement>>(new Map());
  const varOutHandleRefs = useRef<Map<string, HTMLButtonElement>>(new Map());
  const targetHandleRefs = useRef<Map<string, HTMLButtonElement>>(new Map());

  const initFromConfig = useCallback(() => {
    const parsed = parseExistingMappings(componentType, config);
    setRows(parsed);
    const vars = isFieldMapper ? parseExistingVariables(config) : [];
    setVariables(vars);
    const seeded: Col[] = [];
    const seen = new Set<string>();
    for (const r of parsed) {
      const colName = extractSourceCol(r.source);
      if (colName && !seen.has(colName)) {
        seen.add(colName);
        seeded.push({ name: colName, type: r.type || "string" });
      }
    }
    for (const v of vars) {
      for (const ref of referencedIdents(v.expr)) {
        if (!seen.has(ref) && !vars.some((x) => x.name === ref)) {
          seen.add(ref);
          seeded.push({ name: ref, type: "string" });
        }
      }
    }
    if (seeded.length) setSourceCols(seeded);
  }, [componentType, config, isFieldMapper]);

  useEffect(() => {
    if (open) {
      initFromConfig();
      setError(null);
      setInfo(null);
      setSourceQuery("");
      setVarQuery("");
      setTargetQuery("");
      setHoverId(null);
      setDrag(null);
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
        if (selectedPathId.startsWith("var_")) {
          setVariables((prev) => prev.filter((v) => `var_${v.id}` !== selectedPathId));
        } else {
          setRows((prev) => prev.filter((r) => r.id !== selectedPathId));
        }
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

  const addVariable = () => {
    setVariables((prev) => [
      ...prev,
      { id: uid(), name: `var_${prev.length + 1}`, expr: "" },
    ]);
  };

  const removeRow = (id: string) => {
    setRows((prev) => prev.filter((r) => r.id !== id));
    setSelectedPathId((cur) => (cur === id ? null : cur));
  };

  const removeVariable = (id: string) => {
    setVariables((prev) => prev.filter((v) => v.id !== id));
    setSelectedPathId((cur) => (cur === `var_${id}` ? null : cur));
  };

  const updateRow = (id: string, patch: Partial<MappingRow>) => {
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  };

  const updateVariable = (id: string, patch: Partial<VariableRow>) => {
    setVariables((prev) => prev.map((v) => (v.id === id ? { ...v, ...patch } : v)));
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

  const linkVarToTarget = (varName: string, targetRowId: string) => {
    setRows((prev) =>
      prev.map((r) => (r.id === targetRowId ? { ...r, source: varName } : r)),
    );
  };

  const linkSourceToVar = (sourceName: string, varId: string) => {
    setVariables((prev) =>
      prev.map((v) => {
        if (v.id !== varId) return v;
        const ident = isIdent(sourceName) ? sourceName : `col(${JSON.stringify(sourceName)})`;
        if (!v.expr.trim()) return { ...v, expr: ident };
        if (referencedIdents(v.expr).includes(sourceName) || v.expr.includes(sourceName)) return v;
        return { ...v, expr: `${v.expr}+${ident}` };
      }),
    );
  };

  const linkSourceCreate = (sourceName: string) => {
    const col = sourceCols.find((c) => c.name === sourceName);
    setRows((prev) => {
      const slug = slugifyTarget(sourceName);
      const empty = prev.find((r) => !r.source && (r.target === slug || !r.target));
      if (empty) {
        return prev.map((r) =>
          r.id === empty.id
            ? { ...r, source: sourceName, target: r.target || slug, type: col?.type || "string" }
            : r,
        );
      }
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
    const next = mappingsToConfig(componentType, rows, variables, config);
    onApply(next);
    onClose();
  };

  const varNames = useMemo(() => new Set(variables.map((v) => v.name).filter(Boolean)), [variables]);

  const mappedSources = useMemo(() => {
    const s = new Set<string>();
    for (const r of rows) {
      for (const ref of referencedIdents(r.source)) {
        if (!varNames.has(ref)) s.add(ref);
      }
    }
    for (const v of variables) {
      for (const ref of referencedIdents(v.expr)) {
        if (!varNames.has(ref)) s.add(ref);
      }
    }
    return s;
  }, [rows, variables, varNames]);

  const filteredSources = useMemo(() => {
    const q = sourceQuery.trim().toLowerCase();
    if (!q) return sourceCols;
    return sourceCols.filter(
      (c) => c.name.toLowerCase().includes(q) || c.type.toLowerCase().includes(q),
    );
  }, [sourceCols, sourceQuery]);

  const filteredVars = useMemo(() => {
    const q = varQuery.trim().toLowerCase();
    if (!q) return variables;
    return variables.filter(
      (v) => v.name.toLowerCase().includes(q) || v.expr.toLowerCase().includes(q),
    );
  }, [variables, varQuery]);

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

    const mid = (el: HTMLElement) => {
      const r = el.getBoundingClientRect();
      return {
        x: r.left + r.width / 2 - br.left,
        y: r.top + r.height / 2 - br.top,
      };
    };

    if (isFieldMapper) {
      for (const v of variables) {
        for (const ref of referencedIdents(v.expr)) {
          if (varNames.has(ref)) continue;
          const srcEl = sourceHandleRefs.current.get(ref);
          const tgtEl = varInHandleRefs.current.get(v.id);
          if (!srcEl || !tgtEl) continue;
          const a = mid(srcEl);
          const b = mid(tgtEl);
          next.push({
            id: `invar::${v.id}::${ref}`,
            kind: "in-var",
            d: bezierPath(a.x, a.y, b.x, b.y),
          });
        }
      }
      for (const r of rows) {
        if (!r.source || !r.target) continue;
        const srcKey = extractSourceCol(r.source);
        if (varNames.has(srcKey) || variables.some((v) => v.name === srcKey)) {
          const varRow = variables.find((v) => v.name === srcKey);
          if (!varRow) continue;
          const srcEl = varOutHandleRefs.current.get(varRow.id);
          const tgtEl = targetHandleRefs.current.get(r.id);
          if (!srcEl || !tgtEl) continue;
          const a = mid(srcEl);
          const b = mid(tgtEl);
          next.push({
            id: r.id,
            kind: "var-out",
            d: bezierPath(a.x, a.y, b.x, b.y),
          });
        } else {
          const srcEl = sourceHandleRefs.current.get(srcKey);
          const tgtEl = targetHandleRefs.current.get(r.id);
          if (!srcEl || !tgtEl) continue;
          const a = mid(srcEl);
          const b = mid(tgtEl);
          next.push({
            id: r.id,
            kind: "in-out",
            d: bezierPath(a.x, a.y, b.x, b.y),
          });
        }
      }
    } else {
      for (const r of rows) {
        if (!r.source || !r.target) continue;
        const srcKey = extractSourceCol(r.source);
        const srcEl = sourceHandleRefs.current.get(srcKey);
        const tgtEl = targetHandleRefs.current.get(r.id);
        if (!srcEl || !tgtEl) continue;
        const a = mid(srcEl);
        const b = mid(tgtEl);
        next.push({
          id: r.id,
          kind: "in-out",
          d: bezierPath(a.x, a.y, b.x, b.y),
        });
      }
    }
    setPaths(next);
  }, [rows, variables, varNames, isFieldMapper]);

  useLayoutEffect(() => {
    if (!open) return;
    recomputePaths();
  }, [open, recomputePaths, filteredSources, filteredVars, filteredRows, sourceCols]);

  useEffect(() => {
    if (!open) return;
    let raf = 0;
    const onResize = () => {
      if (raf) return;
      raf = window.requestAnimationFrame(() => {
        raf = 0;
        recomputePaths();
      });
    };
    window.addEventListener("resize", onResize);
    const srcPane = sourcePaneRef.current;
    const varPane = varPaneRef.current;
    const tgtPane = targetPaneRef.current;
    srcPane?.addEventListener("scroll", onResize, { passive: true });
    varPane?.addEventListener("scroll", onResize, { passive: true });
    tgtPane?.addEventListener("scroll", onResize, { passive: true });
    const t = window.setTimeout(recomputePaths, 50);
    return () => {
      window.removeEventListener("resize", onResize);
      srcPane?.removeEventListener("scroll", onResize);
      varPane?.removeEventListener("scroll", onResize);
      tgtPane?.removeEventListener("scroll", onResize);
      window.clearTimeout(t);
      if (raf) window.cancelAnimationFrame(raf);
    };
  }, [open, recomputePaths]);

  useEffect(() => {
    if (!drag) return;
    const onMove = (e: MouseEvent) => {
      const body = bodyRef.current;
      if (!body) return;
      const br = body.getBoundingClientRect();
      const srcEl =
        drag.kind === "input"
          ? sourceHandleRefs.current.get(drag.key)
          : varOutHandleRefs.current.get(drag.key);
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
      const targetHandle = el?.closest("[data-target-handle]") as HTMLElement | null;
      const varHandle = el?.closest("[data-var-handle]") as HTMLElement | null;

      if (drag.kind === "input") {
        if (varHandle && isFieldMapper) {
          const varId = varHandle.getAttribute("data-var-handle");
          if (varId) linkSourceToVar(drag.key, varId);
        } else if (targetHandle) {
          const rowId = targetHandle.getAttribute("data-target-handle");
          if (rowId) linkSourceToTarget(drag.key, rowId);
        } else if (el?.closest(".sm-target-pane")) {
          linkSourceCreate(drag.key);
        } else if (el?.closest(".sm-var-pane") && isFieldMapper) {
          // Drop on empty Variables pane → create a variable seeded from the column
          const ident = isIdent(drag.key) ? drag.key : `col(${JSON.stringify(drag.key)})`;
          setVariables((prev) => [
            ...prev,
            { id: uid(), name: slugifyTarget(drag.key) || "var_1", expr: ident },
          ]);
        }
      } else if (drag.kind === "var") {
        const varRow = variables.find((v) => v.id === drag.key);
        if (varRow && targetHandle) {
          const rowId = targetHandle.getAttribute("data-target-handle");
          if (rowId) linkVarToTarget(varRow.name, rowId);
        } else if (varRow && el?.closest(".sm-target-pane")) {
          setRows((prev) => [
            ...prev,
            {
              id: uid(),
              source: varRow.name,
              target: slugifyTarget(varRow.name) || varRow.name,
              type: "string",
            },
          ]);
        }
      }
      setDrag(null);
      setDraft(null);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [drag, isFieldMapper, variables]);

  if (!open) return null;

  const activeHover = hoverId || selectedPathId;
  const linkCount =
    rows.filter((r) => r.source && r.target).length +
    (isFieldMapper ? variables.filter((v) => v.name && v.expr).length : 0);

  return (
    <div className="schema-mapper-overlay" role="dialog" aria-modal="true">
      <div className={`schema-mapper-modal${isFieldMapper ? " fullscreen" : ""}`}>
        <header className="schema-mapper-header">
          <div>
            <h2>Field Mapper</h2>
            <p className="schema-mapper-sub">
              {isFieldMapper
                ? "Main input · Variables · Output — drag handles · helpers for string / math / null · Esc closes"
                : "Map Main input columns to targets · drag handles · Delete removes a link · Esc closes"}
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
          {isFieldMapper && (
            <button type="button" className="btn" onClick={addVariable} data-testid="add-variable">
              Add variable
            </button>
          )}
          <button type="button" className="btn" onClick={addTarget}>
            Add target
          </button>
          <button type="button" className="btn" onClick={clearMappings}>
            Clear
          </button>
          <div className="schema-mapper-spacer" />
          <span className="sm-map-count">{linkCount} links</span>
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

        <div
          className={`schema-mapper-body${isFieldMapper ? " three-pane" : ""}`}
          ref={bodyRef}
        >
          <svg className="sm-links-svg" aria-hidden>
            {paths.map((p) => {
              const active = activeHover === p.id;
              const dimmed = Boolean(activeHover && !active);
              return (
                <g key={p.id}>
                  <path
                    d={p.d}
                    className={`sm-link-hit${active ? " active" : ""}`}
                    onMouseEnter={() => setHoverId(p.id)}
                    onMouseLeave={() => setHoverId((id) => (id === p.id ? null : id))}
                    onClick={() => setSelectedPathId((cur) => (cur === p.id ? null : p.id))}
                    onDoubleClick={(e) => {
                      e.preventDefault();
                      if (p.id.startsWith("invar::")) {
                        const varId = p.id.split("::")[1];
                        setSelectedPathId(`var_${varId}`);
                      } else {
                        removeRow(p.id);
                      }
                    }}
                  />
                  <path
                    d={p.d}
                    className={`sm-link${active ? " active" : ""}${dimmed ? " dimmed" : ""}${
                      p.kind === "in-var" ? " var-link" : ""
                    }`}
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
              <span className="sm-pane-badge source">Input · Main</span>
              <span className="sm-pane-meta">{filteredSources.length} columns</span>
            </div>
            <div className="sm-search">
              <input
                type="search"
                placeholder="Search input…"
                value={sourceQuery}
                onChange={(e) => setSourceQuery(e.target.value)}
                aria-label="Filter input columns"
              />
            </div>
            {filteredSources.length === 0 ? (
              <div className="sm-empty">
                <div className="sm-empty-icon">◎</div>
                <p>No input columns yet</p>
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  disabled={busy}
                  onClick={discoverUpstream}
                >
                  Discover upstream schema
                </button>
              </div>
            ) : (
              <ul className="sm-col-list">
                {filteredSources.map((c) => {
                  const mapped = mappedSources.has(c.name);
                  const linked = drag?.kind === "input" && drag.key === c.name;
                  return (
                    <li
                      key={c.name}
                      className={`sm-col-row source${mapped ? " mapped" : " unmapped"}${
                        linked ? " linked" : ""
                      }`}
                    >
                      <div className="sm-col-main">
                        <span className="sm-col-name">{c.name}</span>
                        <div className="sm-col-meta">
                          <span className="sm-type-chip">{c.type}</span>
                          {c.required && (
                            <span className="sm-required" title="Required">
                              *
                            </span>
                          )}
                        </div>
                      </div>
                      <button
                        type="button"
                        className={`sm-handle source${mapped ? " on" : ""}${
                          drag?.kind === "input" && drag.key === c.name ? " dragging" : ""
                        }`}
                        title="Drag to a Variable or Output column"
                        aria-label={`Connect ${c.name}`}
                        ref={(el) => {
                          if (el) sourceHandleRefs.current.set(c.name, el);
                          else sourceHandleRefs.current.delete(c.name);
                        }}
                        onMouseDown={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                          setDrag({ kind: "input", key: c.name });
                          setSelectedPathId(null);
                        }}
                      />
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          {isFieldMapper ? (
            <div className="sm-pane sm-var-pane" ref={varPaneRef}>
              <div className="sm-pane-label sticky">
                <span className="sm-pane-badge variables">Variables</span>
                <span className="sm-pane-meta">{filteredVars.length}</span>
              </div>
              <div className="sm-search">
                <input
                  type="search"
                  placeholder="Search variables…"
                  value={varQuery}
                  onChange={(e) => setVarQuery(e.target.value)}
                  aria-label="Filter variables"
                />
              </div>
              <div className="sm-fn-help" data-testid="mapper-fn-help">
                <button
                  type="button"
                  className="sm-fn-help-toggle"
                  onClick={() => setFnHelpOpen((v) => !v)}
                  aria-expanded={fnHelpOpen}
                >
                  {fnHelpOpen ? "▾" : "▸"} Expression helpers
                </button>
                {fnHelpOpen && (
                  <div className="sm-fn-groups">
                    <p className="sm-fn-intro">
                      Named Variables sit between Input and Output. Click a helper to seed the
                      focused expression, or type freely — FormulaHub Field Mapper only.
                    </p>
                    {MAPPER_FUNCTION_GROUPS.map((g) => (
                      <div key={g.id} className="sm-fn-group">
                        <div className="sm-fn-group-label">{g.label}</div>
                        <div className="sm-fn-chips">
                          {g.items.map((item) => (
                            <button
                              key={item.sig}
                              type="button"
                              className="sm-fn-chip"
                              title={item.tip}
                              onClick={() => {
                                setVariables((prev) => {
                                  if (!prev.length) {
                                    return [{ id: uid(), name: "var_1", expr: item.sig }];
                                  }
                                  const last = prev[prev.length - 1];
                                  if (!last.expr.trim()) {
                                    return prev.map((v) =>
                                      v.id === last.id ? { ...v, expr: item.sig } : v,
                                    );
                                  }
                                  return [...prev, { id: uid(), name: `var_${prev.length + 1}`, expr: item.sig }];
                                });
                              }}
                            >
                              <code>{item.sig}</code>
                            </button>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
              {filteredVars.length === 0 ? (
                <div className="sm-empty">
                  <div className="sm-empty-icon">◎</div>
                  <p>No variables yet</p>
                  <p className="sm-empty-hint">
                    Named intermediate expressions — reference Input columns, then use in Output.
                  </p>
                  <button type="button" className="btn btn-primary btn-sm" onClick={addVariable}>
                    Add variable
                  </button>
                </div>
              ) : (
                <ul className="sm-col-list">
                  {filteredVars.map((v) => {
                    const linked = activeHover === `var_${v.id}` || activeHover?.includes(v.id);
                    return (
                      <li
                        key={v.id}
                        className={`sm-col-row variable${v.expr ? " mapped" : ""}${
                          linked ? " linked" : ""
                        }`}
                        onMouseEnter={() => setHoverId(`var_${v.id}`)}
                        onMouseLeave={() => setHoverId(null)}
                      >
                        <button
                          type="button"
                          className={`sm-handle target${v.expr ? " on" : ""}`}
                          data-var-handle={v.id}
                          title="Drop an input column here"
                          aria-label={`Variable input for ${v.name || "unnamed"}`}
                          ref={(el) => {
                            if (el) varInHandleRefs.current.set(v.id, el);
                            else varInHandleRefs.current.delete(v.id);
                          }}
                        />
                        <div className="sm-col-main">
                          <input
                            className="sm-target-input"
                            value={v.name}
                            onChange={(e) => updateVariable(v.id, { name: e.target.value })}
                            placeholder="variable name"
                            aria-label="Variable name"
                            data-testid="variable-name"
                          />
                          <input
                            className="sm-expr-input"
                            value={v.expr}
                            onChange={(e) => updateVariable(v.id, { expr: e.target.value })}
                            placeholder={"expression e.g. upper(first)+' '+last"}
                            aria-label="Variable expression"
                            data-testid="variable-expr"
                          />
                          <div className="sm-col-meta">
                            <button
                              type="button"
                              className="btn-icon"
                              title="Delete variable"
                              onClick={() => removeVariable(v.id)}
                            >
                              ×
                            </button>
                          </div>
                        </div>
                        <button
                          type="button"
                          className={`sm-handle source${v.name ? " on" : ""}${
                            drag?.kind === "var" && drag.key === v.id ? " dragging" : ""
                          }`}
                          title="Drag to an Output column"
                          aria-label={`Connect variable ${v.name}`}
                          ref={(el) => {
                            if (el) varOutHandleRefs.current.set(v.id, el);
                            else varOutHandleRefs.current.delete(v.id);
                          }}
                          onMouseDown={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            setDrag({ kind: "var", key: v.id });
                            setSelectedPathId(null);
                          }}
                        />
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          ) : (
            <div className="sm-center-gap" aria-hidden />
          )}

          <div className="sm-pane sm-target-pane" ref={targetPaneRef}>
            <div className="sm-pane-label sticky">
              <span className="sm-pane-badge target">Output</span>
              <span className="sm-pane-meta">{filteredRows.length} columns</span>
            </div>
            <div className="sm-search">
              <input
                type="search"
                placeholder="Search output…"
                value={targetQuery}
                onChange={(e) => setTargetQuery(e.target.value)}
                aria-label="Filter output columns"
              />
            </div>
            {filteredRows.length === 0 ? (
              <div className="sm-empty">
                <div className="sm-empty-icon">◎</div>
                <p>No output mappings</p>
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
                      className={`sm-col-row target${r.source ? " mapped" : ""}${
                        linked ? " linked" : ""
                      }`}
                      onMouseEnter={() => setHoverId(r.id)}
                      onMouseLeave={() => setHoverId(null)}
                    >
                      <button
                        type="button"
                        className={`sm-handle target${r.source ? " on" : ""}`}
                        data-target-handle={r.id}
                        title="Drop an input or variable connection here"
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
                          placeholder="output name"
                          aria-label="Output column name"
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
                            aria-label="Output type"
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
                            placeholder='expression e.g. upper(col("Name")) or a Variable name'
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
            <button
              type="button"
              className="btn btn-sm"
              onClick={() => {
                if (selectedPathId.startsWith("var_")) {
                  removeVariable(selectedPathId.replace(/^var_/, ""));
                } else if (!selectedPathId.startsWith("invar::")) {
                  removeRow(selectedPathId);
                }
                setSelectedPathId(null);
              }}
            >
              Delete link
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
