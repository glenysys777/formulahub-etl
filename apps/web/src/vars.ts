/** Client-side ${…} preview — mirrors formulaetl.sdk.vars (no live execution). */

export type VarRow = {
  key: string;
  value: string;
  source: string;
  resolved: boolean;
};

export type ContextsBlock = {
  active?: string;
  sets?: Record<string, Record<string, unknown>>;
};

export type VarScopeInput = {
  context?: Record<string, unknown>;
  run?: Record<string, unknown>;
  env?: Record<string, string>;
  upstream?: Record<string, unknown>;
  params?: Record<string, unknown>;
  activeContext?: string;
};

const VAR_RE = /\$\{([^{}]+)\}/g;

export function findRefs(text: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  const s = text || "";
  let m: RegExpExecArray | null;
  const re = new RegExp(VAR_RE.source, "g");
  while ((m = re.exec(s)) !== null) {
    const inner = m[1].trim();
    if (!seen.has(inner)) {
      seen.add(inner);
      out.push(inner);
    }
  }
  return out;
}

function lookup(expr: string, scope: VarScopeInput): { value: string | null; source: string } {
  const raw = (expr || "").trim();
  if (!raw) return { value: null, source: "empty" };

  const get = (obj: Record<string, unknown> | undefined, key: string) =>
    obj && Object.prototype.hasOwnProperty.call(obj, key) ? obj[key] : undefined;

  if (raw.startsWith("context.")) {
    const key = raw.slice("context.".length);
    const v = get(scope.context, key);
    return v === undefined ? { value: null, source: "context" } : { value: String(v), source: "context" };
  }
  if (raw.startsWith("run.")) {
    const key = raw.slice("run.".length);
    const v = get(scope.run, key);
    return v === undefined ? { value: null, source: "run" } : { value: String(v), source: "run" };
  }
  if (raw.startsWith("env.")) {
    const key = raw.slice("env.".length);
    const v = scope.env?.[key];
    return v === undefined ? { value: null, source: "env" } : { value: String(v), source: "env" };
  }
  if (raw.startsWith("upstream.")) {
    const key = raw.slice("upstream.".length);
    const v = get(scope.upstream, key);
    return v === undefined
      ? { value: null, source: "upstream" }
      : { value: String(v), source: "upstream" };
  }

  for (const [bag, source] of [
    [scope.params, "params"],
    [scope.context, "context"],
    [scope.run, "run"],
    [scope.upstream, "upstream"],
  ] as const) {
    const v = get(bag, raw);
    if (v !== undefined) return { value: String(v), source };
  }
  return { value: null, source: "unresolved" };
}

export function resolveString(text: string, scope: VarScopeInput): string {
  return (text || "").replace(VAR_RE, (_full, inner: string) => {
    const { value } = lookup(inner, scope);
    return value === null ? `\${${inner}}` : value;
  });
}

export function previewRefs(text: string, scope: VarScopeInput): VarRow[] {
  return findRefs(text).map((key) => {
    const { value, source } = lookup(key, scope);
    return {
      key,
      value: value ?? "",
      source: value === null ? "unresolved" : source,
      resolved: value !== null,
    };
  });
}

export function parseContexts(metadata?: Record<string, unknown> | null): {
  active: string;
  sets: Record<string, Record<string, unknown>>;
} {
  const block = (metadata?.contexts || {}) as ContextsBlock;
  const sets = (block.sets || {}) as Record<string, Record<string, unknown>>;
  let active = String(block.active || "").trim();
  if (!active && Object.keys(sets).length) {
    for (const preferred of ["DEV", "dev", "QA", "qa", "PROD", "prod"]) {
      if (sets[preferred]) {
        active = preferred;
        break;
      }
    }
    if (!active) active = Object.keys(sets)[0];
  }
  return { active, sets };
}

export function buildPreviewScope(
  metadata?: Record<string, unknown> | null,
  opts?: { upstream?: Record<string, unknown>; activeOverride?: string },
): VarScopeInput {
  const { active: parsedActive, sets } = parseContexts(metadata);
  const active = opts?.activeOverride || parsedActive;
  const context = { ...(sets[active] || {}) };
  const runParams =
    metadata?.run_params && typeof metadata.run_params === "object" && !Array.isArray(metadata.run_params)
      ? (metadata.run_params as Record<string, unknown>)
      : {};
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  const runDate = `${now.getUTCFullYear()}-${pad(now.getUTCMonth() + 1)}-${pad(now.getUTCDate())}`;
  const run: Record<string, unknown> = {
    run_id: "preview",
    pipeline_id: "preview",
    run_date: runDate,
    run_ts: `${runDate.replace(/-/g, "")}T000000Z`,
    year: String(now.getUTCFullYear()),
    month: pad(now.getUTCMonth() + 1),
    day: pad(now.getUTCDate()),
    ...runParams,
  };
  const params = { ...runParams, ...context };
  return {
    context,
    run,
    upstream: opts?.upstream || {},
    params,
    activeContext: active,
    env: {},
  };
}

/** Collect template text from node config for variable scanning. */
export function collectTemplateText(config: Record<string, unknown>): string {
  const parts: string[] = [];
  if (typeof config.sql === "string") parts.push(config.sql);
  const lists = ["notebook_params", "python_params"] as const;
  for (const key of lists) {
    const raw = config[key];
    if (Array.isArray(raw)) parts.push(raw.map(String).join("\n"));
    else if (typeof raw === "string") parts.push(raw);
    else if (raw && typeof raw === "object") {
      parts.push(
        Object.entries(raw as Record<string, unknown>)
          .map(([k, v]) => `${k}=${v}`)
          .join("\n"),
      );
    }
  }
  return parts.join("\n");
}

export function supportsVariables(componentType: string): boolean {
  return componentType === "databricks_sql" || componentType === "databricks_job";
}

/** Starter keys for a new Job Context set (empty values — founder fills them). */
export const STARTER_CONTEXT_KEYS = ["env", "catalog", "schema"] as const;

export const DEFAULT_CONTEXT_SET_NAMES = ["DEV", "QA", "PROD"] as const;

export function emptyStarterSet(): Record<string, unknown> {
  const set: Record<string, unknown> = {};
  for (const key of STARTER_CONTEXT_KEYS) set[key] = "";
  return set;
}

export function defaultContextSets(): Record<string, Record<string, unknown>> {
  const sets: Record<string, Record<string, unknown>> = {};
  for (const name of DEFAULT_CONTEXT_SET_NAMES) {
    sets[name] = emptyStarterSet();
  }
  return sets;
}

/**
 * Ensure pipeline metadata has a Job Contexts block.
 * Seeds DEV/QA/PROD with starter keys when sets are missing or empty.
 * Does not overwrite existing non-empty sets.
 */
export function ensureContextsMetadata(
  metadata?: Record<string, unknown> | null,
): Record<string, unknown> {
  const next = { ...(metadata || {}) };
  const { active, sets } = parseContexts(next);
  const hasSets = Object.keys(sets).length > 0;
  const seededSets = hasSets ? sets : defaultContextSets();
  const seededActive =
    active && seededSets[active]
      ? active
      : Object.keys(seededSets).includes("DEV")
        ? "DEV"
        : Object.keys(seededSets)[0] || "DEV";
  next.contexts = {
    ...((next.contexts as Record<string, unknown>) || {}),
    active: seededActive,
    sets: seededSets,
  };
  if (!next.run_params || typeof next.run_params !== "object" || Array.isArray(next.run_params)) {
    next.run_params = { run_date: "", job_name: "" };
  } else {
    const rp = { ...(next.run_params as Record<string, unknown>) };
    if (!Object.prototype.hasOwnProperty.call(rp, "run_date")) rp.run_date = "";
    if (!Object.prototype.hasOwnProperty.call(rp, "job_name")) rp.job_name = "";
    next.run_params = rp;
  }
  return next;
}

export function setActiveContext(
  metadata: Record<string, unknown> | null | undefined,
  name: string,
): Record<string, unknown> {
  const base = ensureContextsMetadata(metadata);
  const { sets } = parseContexts(base);
  if (!sets[name]) return base;
  return {
    ...base,
    contexts: {
      ...((base.contexts as Record<string, unknown>) || {}),
      active: name,
      sets,
    },
  };
}

export function setContextEntries(
  metadata: Record<string, unknown> | null | undefined,
  setName: string,
  entries: Record<string, unknown>,
): Record<string, unknown> {
  const base = ensureContextsMetadata(metadata);
  const { active, sets } = parseContexts(base);
  return {
    ...base,
    contexts: {
      ...((base.contexts as Record<string, unknown>) || {}),
      active: sets[active] ? active : setName,
      sets: { ...sets, [setName]: { ...entries } },
    },
  };
}

export function addContextSet(
  metadata: Record<string, unknown> | null | undefined,
  name: string,
  source?: Record<string, unknown>,
): Record<string, unknown> {
  const trimmed = name.trim();
  if (!trimmed) return ensureContextsMetadata(metadata);
  const base = ensureContextsMetadata(metadata);
  const { active, sets } = parseContexts(base);
  if (sets[trimmed]) return base;
  const nextSets = {
    ...sets,
    [trimmed]: source ? { ...source } : emptyStarterSet(),
  };
  return {
    ...base,
    contexts: {
      ...((base.contexts as Record<string, unknown>) || {}),
      active: active || trimmed,
      sets: nextSets,
    },
  };
}

export function duplicateContextSet(
  metadata: Record<string, unknown> | null | undefined,
  fromName: string,
  toName: string,
): Record<string, unknown> {
  const { sets } = parseContexts(metadata);
  const source = sets[fromName];
  if (!source) return ensureContextsMetadata(metadata);
  return addContextSet(metadata, toName, source);
}

export function deleteContextSet(
  metadata: Record<string, unknown> | null | undefined,
  name: string,
): Record<string, unknown> {
  const base = ensureContextsMetadata(metadata);
  const { active, sets } = parseContexts(base);
  if (!sets[name]) return base;
  const nextSets = { ...sets };
  delete nextSets[name];
  // Keep at least one set — reseed defaults if emptied.
  const finalSets = Object.keys(nextSets).length > 0 ? nextSets : defaultContextSets();
  let nextActive = active === name ? "" : active;
  if (!nextActive || !finalSets[nextActive]) {
    nextActive = Object.keys(finalSets).includes("DEV")
      ? "DEV"
      : Object.keys(finalSets)[0];
  }
  return {
    ...base,
    contexts: {
      ...((base.contexts as Record<string, unknown>) || {}),
      active: nextActive,
      sets: finalSets,
    },
  };
}

export function renameContextSet(
  metadata: Record<string, unknown> | null | undefined,
  fromName: string,
  toName: string,
): Record<string, unknown> {
  const trimmed = toName.trim();
  if (!trimmed || trimmed === fromName) return ensureContextsMetadata(metadata);
  const base = ensureContextsMetadata(metadata);
  const { active, sets } = parseContexts(base);
  if (!sets[fromName] || sets[trimmed]) return base;
  const nextSets = { ...sets };
  nextSets[trimmed] = { ...nextSets[fromName] };
  delete nextSets[fromName];
  return {
    ...base,
    contexts: {
      ...((base.contexts as Record<string, unknown>) || {}),
      active: active === fromName ? trimmed : active,
      sets: nextSets,
    },
  };
}

export function setRunParam(
  metadata: Record<string, unknown> | null | undefined,
  key: string,
  value: string,
): Record<string, unknown> {
  const base = ensureContextsMetadata(metadata);
  const rp =
    base.run_params && typeof base.run_params === "object" && !Array.isArray(base.run_params)
      ? { ...(base.run_params as Record<string, unknown>) }
      : {};
  rp[key] = value;
  return { ...base, run_params: rp };
}

/** Stable key/value rows for the editor (preserves insertion order of object keys). */
export function contextEntriesToRows(
  entries: Record<string, unknown>,
): { key: string; value: string }[] {
  return Object.keys(entries).map((key) => ({
    key,
    value: entries[key] == null ? "" : String(entries[key]),
  }));
}

export function rowsToContextEntries(
  rows: { key: string; value: string }[],
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const row of rows) {
    const k = row.key.trim();
    if (!k) continue;
    // First wins if duplicate keys after trim.
    if (Object.prototype.hasOwnProperty.call(out, k)) continue;
    out[k] = row.value;
  }
  return out;
}
