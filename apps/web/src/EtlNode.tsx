import { Handle, Position, type NodeProps } from "@xyflow/react";

/** Visual category → CSS class + accent */
const CATEGORY: Record<string, string> = {
  s3_source: "source",
  http_api_source: "source",
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

const CAT_ICON: Record<string, string> = {
  source: "↓",
  file: "📄",
  db: "▣",
  security: "🔐",
  transform: "⟳",
  quality: "✓",
  destination: "↑",
  utility: "⚙",
};

function Icon({ cat }: { cat: string }) {
  if (cat === "source") {
    return (
      <svg viewBox="0 0 16 16" fill="none" aria-hidden>
        <path d="M8 2v9M4.5 8.5 8 12l3.5-3.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M3 14h10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
    );
  }
  if (cat === "destination") {
    return (
      <svg viewBox="0 0 16 16" fill="none" aria-hidden>
        <path d="M8 14V5M4.5 7.5 8 4l3.5 3.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M3 2h10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
    );
  }
  if (cat === "file") {
    return (
      <svg viewBox="0 0 16 16" fill="none" aria-hidden>
        <path d="M4 2.5h5.5L12 5v8.5H4V2.5Z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
        <path d="M9.5 2.5V5H12" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
      </svg>
    );
  }
  if (cat === "db") {
    return (
      <svg viewBox="0 0 16 16" fill="none" aria-hidden>
        <ellipse cx="8" cy="4" rx="5" ry="2" stroke="currentColor" strokeWidth="1.4" />
        <path d="M3 4v4c0 1.1 2.2 2 5 2s5-.9 5-2V4" stroke="currentColor" strokeWidth="1.4" />
        <path d="M3 8v4c0 1.1 2.2 2 5 2s5-.9 5-2V8" stroke="currentColor" strokeWidth="1.4" />
      </svg>
    );
  }
  if (cat === "security") {
    return (
      <svg viewBox="0 0 16 16" fill="none" aria-hidden>
        <rect x="3.5" y="7" width="9" height="7" rx="1.2" stroke="currentColor" strokeWidth="1.4" />
        <path d="M5.5 7V5.2a2.5 2.5 0 0 1 5 0V7" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      </svg>
    );
  }
  if (cat === "transform") {
    return (
      <svg viewBox="0 0 16 16" fill="none" aria-hidden>
        <path d="M3 5h7.5M10.5 5l-2-2M10.5 5l-2 2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M13 11H5.5M5.5 11l2-2M5.5 11l2 2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  if (cat === "quality") {
    return (
      <svg viewBox="0 0 16 16" fill="none" aria-hidden>
        <circle cx="8" cy="8" r="5.5" stroke="currentColor" strokeWidth="1.4" />
        <path d="M5.5 8.2 7.2 10l3.5-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 16 16" fill="none" aria-hidden>
      <circle cx="8" cy="8" r="2.2" stroke="currentColor" strokeWidth="1.4" />
      <path d="M8 2.5v1.8M8 11.7v1.8M2.5 8h1.8M11.7 8h1.8M4.1 4.1l1.3 1.3M10.6 10.6l1.3 1.3M11.9 4.1l-1.3 1.3M5.4 10.6l-1.3 1.3" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  );
}

function summary(type: string, config: Record<string, unknown>): string {
  if (type === "s3_source") return `s3://${config.bucket}/${config.key}`;
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
    const n = Array.isArray(m) ? m.length : m ? String(m).split("\n").filter(Boolean).length : 0;
    return n ? `${n} field maps` : "map fields";
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
  if (type === "python_row") return `${config.mode || "row"} · Python (not Java)`;
  if (type === "lookup_join") return String(config.how || "left") + " join";
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

const HANDLE_COLORS: Record<string, string> = {
  source: "#0071e3",
  file: "#0d9488",
  db: "#5856d6",
  security: "#af52de",
  transform: "#ff9f0a",
  quality: "#ffd60a",
  destination: "#34c759",
  utility: "#8e8e93",
};

function friendlyLabel(type: string, label: string): string {
  const lower = (label || "").toLowerCase();
  if (type === "tmap") {
    if (!label || lower === "tmap" || lower === "t map" || lower.includes("tmap")) return "Field Mapper";
    return label;
  }
  if (type === "column_map" && (lower === "column map" || lower === "tmap" || !label)) return "Schema Map";
  return label || type;
}

export function EtlNode({ data, selected }: NodeProps) {
  const d = data as EtlNodeData;
  const cat = CATEGORY[d.componentType] || "utility";
  const accent = HANDLE_COLORS[cat] || HANDLE_COLORS.utility;
  const hasRejects =
    d.componentType === "schema_validate" ||
    (d.componentType === "tmap" && Boolean(d.config?.reject_unmatched));
  const runVisual = d.runVisual || "idle";
  const title = friendlyLabel(d.componentType, d.label);
  const isMapper = d.componentType === "tmap" || d.componentType === "column_map";

  return (
    <div
      className={`etl-node cat-${cat} ${selected ? "selected" : ""} run-${runVisual}${isMapper ? " is-mapper" : ""}`}
      title={isMapper ? "Map source columns to targets — double-click to open" : undefined}
    >
      {runVisual === "running" && <span className="etl-progress-ring" aria-hidden />}
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
      <Handle
        type="target"
        position={Position.Left}
        style={{ background: "#aeaeb2" }}
      />
      <div className="etl-node-header">
        <span className="etl-node-icon" title={CAT_ICON[cat]}>
          <Icon cat={cat} />
        </span>
        <span className="etl-node-title">{title}</span>
      </div>
      <div className="etl-node-body" title={summary(d.componentType, d.config)}>
        {summary(d.componentType, d.config)}
      </div>
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
}
