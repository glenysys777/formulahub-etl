import { memo, useMemo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { useStudioNodeActions } from "./studioActions";

/** Visual category → CSS class + accent (distinct colors, original glyphs — no vendor logos) */
const CATEGORY: Record<string, string> = {
  s3_source: "source",
  http_api_source: "source",
  kafka_source: "stream",
  sftp_source: "source",

  local_file_source: "file",
  excel_source: "file",
  local_file_destination: "file",
  excel_destination: "file",
  archive_files: "file",

  sqlite_source: "db",
  postgres_source: "db",
  mysql_source: "db",
  sqlite_destination: "db",
  postgres_destination: "db",
  mysql_destination: "db",
  snowflake_destination: "db",
  databricks_job: "orch",
  databricks_sql: "orch",
  run_pipeline: "orch",

  pgp_decrypt: "security",
  pgp_encrypt: "security",

  csv_parser: "transform",
  json_parser: "transform",
  xml_parser: "transform",
  column_map: "transform",
  tmap: "transform",
  transform: "transform",
  filter: "transform",
  sort: "transform",
  aggregate: "transform",
  python_row: "transform",
  dedupe: "transform",
  lookup_join: "transform",

  schema_validate: "quality",

  sftp_destination: "destination",

  logger_metrics: "utility",
};

export const CAT_COLORS: Record<string, string> = {
  source: "#0071e3",
  stream: "#ff375f",
  file: "#0d9488",
  db: "#5856d6",
  orch: "#ff6b35",
  security: "#af52de",
  transform: "#ff9f0a",
  quality: "#e6a800",
  destination: "#34c759",
  utility: "#8e8e93",
};

/** Original SVG glyphs per component (never vendor trademark logos). */
export function ComponentGlyph({
  type,
  size = 16,
}: {
  type: string;
  size?: number;
}) {
  const common = {
    width: size,
    height: size,
    viewBox: "0 0 16 16",
    fill: "none" as const,
    "aria-hidden": true as const,
  };
  // Bucket (S3-style object storage — geometric, not AWS logo)
  if (type === "s3_source") {
    return (
      <svg {...common}>
        <path d="M2.5 5.5 8 2.5l5.5 3-5.5 3-5.5-3Z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
        <path d="M2.5 5.5V11l5.5 2.5L13.5 11V5.5" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
        <path d="M8 8.5v5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      </svg>
    );
  }
  // Bolt / stream (Kafka-style — not Confluent/Kafka logos)
  if (type === "kafka_source") {
    return (
      <svg {...common}>
        <path d="M9.2 1.8 4.2 8.2h3.2L6.8 14.2l5-6.4H8.6L9.2 1.8Z" stroke="currentColor" strokeWidth="1.35" strokeLinejoin="round" />
      </svg>
    );
  }
  // Globe / API
  if (type === "http_api_source") {
    return (
      <svg {...common}>
        <circle cx="8" cy="8" r="5.5" stroke="currentColor" strokeWidth="1.4" />
        <path d="M2.5 8h11M8 2.5c1.8 1.8 1.8 9.2 0 11M8 2.5c-1.8 1.8-1.8 9.2 0 11" stroke="currentColor" strokeWidth="1.25" />
      </svg>
    );
  }
  // Table / spark job trigger (Databricks orchestration — geometric table+play, not vendor mark)
  if (type === "databricks_job") {
    return (
      <svg {...common}>
        <rect x="2" y="3" width="12" height="10" rx="1.2" stroke="currentColor" strokeWidth="1.4" />
        <path d="M2 6.5h12M6.5 3v10M9.5 3v10" stroke="currentColor" strokeWidth="1.2" />
        <path d="M11.2 9.2 13.5 10.5 11.2 11.8V9.2Z" fill="currentColor" />
      </svg>
    );
  }
  // SQL statement (warehouse) — table + cursor
  if (type === "databricks_sql") {
    return (
      <svg {...common}>
        <rect x="2" y="3" width="12" height="10" rx="1.2" stroke="currentColor" strokeWidth="1.4" />
        <path d="M2 6.5h12M6.5 3v10M9.5 3v10" stroke="currentColor" strokeWidth="1.2" />
        <path d="M4.2 12.2h3.2" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      </svg>
    );
  }
  // Nested pipeline (Master → Child) — stacked frames + play
  if (type === "run_pipeline") {
    return (
      <svg {...common}>
        <rect x="1.5" y="2.5" width="10" height="8" rx="1.2" stroke="currentColor" strokeWidth="1.35" />
        <rect x="4.5" y="5.5" width="10" height="8" rx="1.2" stroke="currentColor" strokeWidth="1.35" />
        <path d="M8.2 8.2 11.2 10 8.2 11.8V8.2Z" fill="currentColor" />
      </svg>
    );
  }
  // Lock
  if (type === "pgp_decrypt" || type === "pgp_encrypt") {
    return (
      <svg {...common}>
        <rect x="3.5" y="7" width="9" height="7" rx="1.2" stroke="currentColor" strokeWidth="1.4" />
        <path d="M5.5 7V5.2a2.5 2.5 0 0 1 5 0V7" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
        <circle cx="8" cy="10.5" r="1" fill="currentColor" />
      </svg>
    );
  }
  // Cylinder DB
  if (
    type.includes("postgres") ||
    type.includes("mysql") ||
    type.includes("sqlite") ||
    type.includes("snowflake")
  ) {
    return (
      <svg {...common}>
        <ellipse cx="8" cy="4" rx="5" ry="2" stroke="currentColor" strokeWidth="1.4" />
        <path d="M3 4v4c0 1.1 2.2 2 5 2s5-.9 5-2V4" stroke="currentColor" strokeWidth="1.4" />
        <path d="M3 8v4c0 1.1 2.2 2 5 2s5-.9 5-2V8" stroke="currentColor" strokeWidth="1.4" />
      </svg>
    );
  }
  // File
  if (type.includes("file") || type.includes("excel") || type === "archive_files") {
    return (
      <svg {...common}>
        <path d="M4 2.5h5.5L12 5v8.5H4V2.5Z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
        <path d="M9.5 2.5V5H12M6 8h4M6 10.5h4" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
      </svg>
    );
  }
  // Download arrow (generic source)
  if (type.endsWith("_source") || type.includes("sftp_source")) {
    return (
      <svg {...common}>
        <path d="M8 2v9M4.5 8.5 8 12l3.5-3.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M3 14h10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
    );
  }
  // Upload (destination)
  if (type.endsWith("_destination") || type.includes("sftp_destination")) {
    return (
      <svg {...common}>
        <path d="M8 14V5M4.5 7.5 8 4l3.5 3.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M3 2h10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
    );
  }
  // Check quality
  if (type === "schema_validate") {
    return (
      <svg {...common}>
        <circle cx="8" cy="8" r="5.5" stroke="currentColor" strokeWidth="1.4" />
        <path d="M5.5 8.2 7.2 10l3.5-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  // Transform arrows
  if (
    type === "tmap" ||
    type === "column_map" ||
    type === "transform" ||
    type.includes("parser") ||
    type === "filter" ||
    type === "sort" ||
    type === "aggregate" ||
    type === "dedupe" ||
    type === "lookup_join" ||
    type === "python_row"
  ) {
    return (
      <svg {...common}>
        <path d="M3 5h7.5M10.5 5l-2-2M10.5 5l-2 2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M13 11H5.5M5.5 11l2-2M5.5 11l2 2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  // Gear utility
  return (
    <svg {...common}>
      <circle cx="8" cy="8" r="2.2" stroke="currentColor" strokeWidth="1.4" />
      <path
        d="M8 2.5v1.8M8 11.7v1.8M2.5 8h1.8M11.7 8h1.8M4.1 4.1l1.3 1.3M10.6 10.6l1.3 1.3M11.9 4.1l-1.3 1.3M5.4 10.6l-1.3 1.3"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function categoryForType(type: string): string {
  return CATEGORY[type] || "utility";
}

export function isMapperType(t: string): boolean {
  return t === "column_map" || t === "tmap";
}

export function isLookupType(t: string): boolean {
  return t === "lookup_join";
}

function mappingCount(config: Record<string, unknown>): number {
  const m = config.mappings ?? config.rename;
  if (Array.isArray(m)) return m.length;
  if (typeof m === "string") return m.split(/\n/).map((s) => s.trim()).filter(Boolean).length;
  if (m && typeof m === "object") return Object.keys(m as Record<string, unknown>).length;
  return 0;
}

function MapGlyph() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden>
      <rect x="1.5" y="3" width="4.5" height="10" rx="1" stroke="currentColor" strokeWidth="1.3" />
      <rect x="10" y="3" width="4.5" height="10" rx="1" stroke="currentColor" strokeWidth="1.3" />
      <path
        d="M6.5 8h3M8.5 6.5 10 8l-1.5 1.5"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function summary(type: string, config: Record<string, unknown>): string {
  if (type === "s3_source") return `s3://${config.bucket}/${config.key}`;
  if (type === "kafka_source")
    return `${config.topic || "topic"} @ ${config.brokers || "brokers"}`;
  if (type === "databricks_job")
    return `job ${config.job_id || "?"} · ${config.workspace_host || "host"}`;
  if (type === "databricks_sql") {
    const sql = String(config.sql || "");
    const short = sql.length > 36 ? `${sql.slice(0, 36)}…` : sql || "SQL";
    return `${config.warehouse_id || "warehouse"} · ${short}`;
  }
  if (type === "run_pipeline") {
    const pub = config.publish_as ? ` → ${config.publish_as}` : "";
    return `${config.pipeline_id || "child"}${pub}`;
  }
  if (type === "local_file_source") return String(config.path || "");
  if (type === "http_api_source") return String(config.url || "HTTP API");
  if (type === "excel_source")
    return `${config.path || "excel"}${config.sheet_name ? ` · ${config.sheet_name}` : ""}`;
  if (type === "excel_destination") return String(config.path || "xlsx");
  if (type === "sqlite_source") return String(config.path || "demo.db");
  if (type === "sqlite_destination")
    return `${config.path || "demo.db"} · ${config.table || "table"}`;
  if (type === "sftp_source") return String(config.remote_path || config.host || "SFTP");
  if (type === "sftp_destination") return String(config.remote_path || "SFTP out");
  if (type === "postgres_source") return String(config.query || config.host || "Postgres");
  if (type === "postgres_destination") return String(config.table || "Postgres");
  if (type === "mysql_source") return String(config.query || config.host || "MySQL");
  if (type === "mysql_destination") return String(config.table || "MySQL");
  if (type === "json_parser") return String(config.json_path || config.path || "JSON → rows");
  if (type === "xml_parser")
    return String(config.record_tag || config.xpath || config.path || "XML → rows");
  if (type === "dedupe") {
    const k = config.keys as string[] | string | undefined;
    const n = Array.isArray(k) ? k.join(",") : k || "keys";
    return `unique: ${n}`;
  }
  if (type === "column_map") {
    const m = config.mappings as string[] | string | undefined;
    const n = Array.isArray(m) ? m.length : m ? String(m).split("\n").filter(Boolean).length : 0;
    return n ? `${n} mappings` : "map columns";
  }
  if (type === "tmap") {
    const m = config.mappings as string[] | string | undefined;
    const v = config.variables as string[] | string | undefined | object[];
    const n = Array.isArray(m) ? m.length : m ? String(m).split("\n").filter(Boolean).length : 0;
    const vn = Array.isArray(v)
      ? v.length
      : v
        ? String(v).split("\n").filter(Boolean).length
        : 0;
    if (n && vn) return `${vn} vars · ${n} outputs`;
    return n ? `${n} field maps` : "map fields";
  }
  if (type === "lookup_join") {
    const how = String(config.how || "left");
    const match = String(config.match || "all");
    return `${how} join · match ${match}`;
  }
  if (type === "sort") {
    const k = config.keys as string[] | string | undefined;
    const n = Array.isArray(k) ? k.join(", ") : k || "keys";
    return `sort: ${n}`;
  }
  if (type === "aggregate") {
    const g = config.group_by as string[] | string | undefined;
    const a = config.aggs as string[] | string | undefined;
    const gs = Array.isArray(g) ? g.join(",") : g || "*";
    const an = Array.isArray(a) ? a.length : a ? 1 : 0;
    return `group ${gs} · ${an} aggs`;
  }
  if (type === "python_row") return `${config.mode || "row"} · Python`;
  if (type === "lookup_join") {
    const how = String(config.how || "left");
    const match = String(config.match || "all");
    return `${how} join · match ${match}`;
  }
  if (type === "pgp_decrypt") return String(config.private_key_path || "private key");
  if (type === "pgp_encrypt") return String(config.public_key_path || "public key");
  if (type === "schema_validate") {
    const cols = config.columns as Record<string, string> | undefined;
    return cols ? `${Object.keys(cols).length} columns` : "schema";
  }
  if (type === "snowflake_destination")
    return `${config.database}.${config.schema}.${config.table}`;
  if (type === "local_file_destination") return String(config.path || "");
  if (type === "archive_files") return String(config.destination || "archive");
  if (type === "transform") return "cast / rename / map";
  if (type === "filter") return String(config.expression || "filter");
  if (type === "csv_parser") return "CSV → rows";
  if (type === "logger_metrics") return String(config.label || "metrics");
  return type;
}

export type RunVisual = "idle" | "running" | "success" | "error" | "reject";

export type EtlNodeData = {
  label: string;
  componentType: string;
  config: Record<string, unknown>;
  runVisual?: RunVisual;
};

const HANDLE_COLORS: Record<string, string> = { ...CAT_COLORS };

function friendlyLabel(type: string, label: string): string {
  const lower = (label || "").toLowerCase();
  if (type === "tmap") {
    if (!label || lower === "tmap" || lower === "t map" || lower.includes("tmap")) return "Field Mapper";
    return label;
  }
  if (type === "column_map" && (lower === "column map" || lower === "tmap" || !label)) return "Schema Map";
  if (type === "kafka_source") return label || "Kafka Source";
  if (type === "databricks_job") return label || "Databricks Job";
  if (type === "databricks_sql") return label || "Databricks SQL";
  if (type === "run_pipeline") return label || "Run Pipeline";
  return label || type;
}

export const EtlNode = memo(function EtlNode({ id, data, selected }: NodeProps) {
  const d = data as EtlNodeData;
  const actions = useStudioNodeActions();
  const cat = categoryForType(d.componentType);
  const accent = HANDLE_COLORS[cat] || HANDLE_COLORS.utility;
  const hasRejects =
    d.componentType === "schema_validate" ||
    (d.componentType === "tmap" && Boolean(d.config?.reject_unmatched));
  const runVisual = d.runVisual || "idle";
  const title = friendlyLabel(d.componentType, d.label);
  const isMapper = isMapperType(d.componentType);
  const isLookup = isLookupType(d.componentType);
  const maps = isMapper ? mappingCount(d.config) : 0;
  const bodySummary = useMemo(
    () => summary(d.componentType, d.config),
    [d.componentType, d.config],
  );

  return (
    <div
      className={`etl-node cat-${cat} ${selected ? "selected" : ""} run-${runVisual}${isMapper ? " is-mapper" : ""}${isLookup ? " is-lookup" : ""}`}
      data-testid={isMapper ? "etl-mapper-node" : isLookup ? "etl-lookup-node" : "etl-node"}
      onDoubleClick={(e) => {
        e.preventDefault();
        actions?.activateNode(id, d.componentType);
      }}
      title={
        isMapper
          ? "Double-click to open Field Mapper"
          : isLookup
            ? "Double-click to edit join keys — Main (upper) + Lookup (lower)"
            : "Double-click to configure in Node Inspector"
      }
    >
      {runVisual === "running" && selected && <span className="etl-progress-ring" aria-hidden />}
      {runVisual === "success" && (
        <span className="etl-run-badge ok" title="Completed" aria-hidden>
          <svg viewBox="0 0 16 16" fill="none">
            <path d="M4 8.2 6.8 11 12 5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </span>
      )}
      {runVisual === "error" && (
        <span className="etl-run-badge err" title="Failed" aria-hidden>
          !
        </span>
      )}
      {runVisual === "reject" && (
        <span className="etl-run-badge reject" title="Rejects" aria-hidden>
          ↺
        </span>
      )}
      {isLookup ? (
        <>
          <Handle
            type="target"
            id="in"
            position={Position.Left}
            className="etl-handle-main"
            style={{ background: "#0071e3", top: "32%" }}
            title="Main (primary) input — wire the driving row stream here"
          />
          <span
            className="etl-handle-label main"
            style={{ top: "32%" }}
            data-testid="handle-label-main"
          >
            Main
          </span>
          <Handle
            type="target"
            id="right"
            position={Position.Left}
            className="etl-handle-lookup"
            style={{ background: "#ff9f0a", top: "68%" }}
            title="Lookup input — wire the enrichment stream (or use Lookup file)"
          />
          <span
            className="etl-handle-label lookup"
            style={{ top: "68%" }}
            data-testid="handle-label-lookup"
          >
            Lookup
          </span>
        </>
      ) : isMapper ? (
        <Handle
          type="target"
          position={Position.Left}
          className="etl-handle-in"
          style={{ background: "#0071e3" }}
          title="Input — map columns on this stream"
        />
      ) : (
        <Handle type="target" position={Position.Left} style={{ background: "#aeaeb2" }} />
      )}
      <div className="etl-node-header">
        <span className="etl-node-icon" title={d.componentType}>
          <ComponentGlyph type={d.componentType} />
        </span>
        <span className="etl-node-title">{title}</span>
        {isMapper ? (
          <button
            type="button"
            className="etl-map-btn nodrag nopan"
            data-testid="etl-map-btn"
            title="Open Field Mapper"
            aria-label="Open Field Mapper"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              actions?.openMapper(id);
            }}
            onDoubleClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              actions?.openMapper(id);
            }}
          >
            <MapGlyph />
          </button>
        ) : (
          <button
            type="button"
            className="etl-open-btn nodrag nopan"
            data-testid="etl-open-btn"
            title="Open inspector"
            aria-label="Open inspector"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              actions?.activateNode(id, d.componentType);
            }}
          >
            ›
          </button>
        )}
      </div>
      <div className="etl-node-body" title={bodySummary}>
        {bodySummary}
      </div>
      {isMapper ? (
        <div className="etl-node-affordance">
          <span className="etl-map-badge" data-testid="etl-map-badge">
            {maps ? `Map · ${maps}` : "Map"}
          </span>
          <span className="etl-map-hint" data-testid="etl-map-hint">
            Double-click to map
          </span>
        </div>
      ) : isLookup ? (
        <div className="etl-node-affordance">
          <span className="etl-join-badge">Join</span>
          <span className="etl-map-hint" data-testid="etl-join-hint">
            Main + Lookup
          </span>
        </div>
      ) : (
        <div className="etl-node-affordance">
          <span className="etl-map-hint" data-testid="etl-configure-hint">
            Double-click to configure
          </span>
        </div>
      )}
      <Handle
        type="source"
        position={Position.Right}
        id="out"
        style={{ background: accent, top: hasRejects ? "40%" : "50%" }}
      />
      {hasRejects && (
        <Handle
          type="source"
          position={Position.Right}
          id="rejects"
          style={{ background: "#ff375f", top: "72%" }}
        />
      )}
    </div>
  );
});
