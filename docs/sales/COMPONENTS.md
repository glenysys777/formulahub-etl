# FormulaHub ETL — Component catalog & honest limits

**Product:** FormulaHub ETL (Lynkx) · [formulahub.io/etl](https://formulahub.io/etl)  
**License:** Apache 2.0 (open-core)  
**Stage:** MVP / demo-ready — catalog grows; we do not claim a 200-connector suite today.

For client conversations: what ships now, what demo mode mocks, and what is roadmap.

---

## Shipped now (demo-ready with `FORMULAETL_DEMO=1`)

### Sources & ingest

| Component | Type id | Notes |
|-----------|---------|-------|
| S3 Source | `s3_source` | Demo → local mock under `data/s3/`; real needs AWS creds + `FORMULAETL_DEMO=0` |
| Local File Source | `local_file_source` | Path on disk |
| Excel Source | `excel_source` | `.xlsx` sheets; Discover schema supported |
| HTTP / REST API Source | `http_api_source` | Demo fixture for example.com / `demo=true` |
| **Kafka Source** | `kafka_source` | Demo → `fixtures/sample/kafka_orders.jsonl` when `FORMULAETL_DEMO=1` or brokers=`demo`. Live needs optional `formulaetl[kafka]` or `confluent-kafka` |

> **Honesty:** Kafka Source + Databricks Job Trigger are production-shaped (real client libraries / Jobs API when credentials set) but **CI and default DEMO=1 use fixtures/sidecars — live Kafka/Databricks against customer clusters is unproven until a design-partner run.** Do not claim live E2E in CI.

> **Honesty:** Kafka Source + Databricks Job Trigger are production-shaped (real client libraries / Jobs API when credentials set) but **CI and default `FORMULAETL_DEMO=1` use fixtures/sidecars — live Kafka/Databricks against customer clusters is unproven until a design-partner run.** Do not claim live E2E in CI.
| SFTP Source | `sftp_source` | Demo copies fixtures into staging — **no real SFTP wire** |
| Postgres Source | `postgres_source` | Demo → SQLite `data/demo.db` or fixture rows |
| MySQL Source | `mysql_source` | Demo → SQLite; live needs PyMySQL + `FORMULAETL_DEMO=0` |
| SQLite Source | `sqlite_source` | Local DB pattern |

### Parse & map

| Component | Type id | Notes |
|-----------|---------|-------|
| CSV Parser | `csv_parser` | Delimited → rows |
| JSON Parser | `json_parser` | Array / path / `json_path` → rows |
| XML Parser | `xml_parser` | Record tag / xpath-lite → rows |
| Schema Map | `column_map` | Rename / simple column map; **Field Mapper** UI |
| **Field Mapper** | Field Mapper node | **Input · Variables · Output** canvas: named intermediate expressions + `out=expr` mappings, optional filter, `drop_unmapped`; Discover schema; Variables persist in node config |

### Transform & quality

| Component | Type id | Notes |
|-----------|---------|-------|
| Transform | `transform` | Date / type casts, light maps |
| Schema Validate | `schema_validate` | Required columns + types; reject stream |
| Filter | `filter` | Expression filter |
| Sort Rows | `sort` | Keys as `col:asc` / `col:desc` |
| Aggregate | `aggregate` | `group_by` + sum / count / min / max / avg |
| Dedupe | `dedupe` | Keep first / last on keys |
| Lookup Join | `lookup_join` | Join types: **left / inner / right / full**; match mode **all** (one-to-many) or **first**; file or second input on the **right** handle |
| Python Row | `python_row` | Per-row or batch **sandboxed Python** (row/rows + safe builtins; no open / network / os) |
| PGP Decrypt / Encrypt | `pgp_decrypt` / `pgp_encrypt` | Demo keys under `fixtures/keys/` |

### Destinations & ops

| Component | Type id | Notes |
|-----------|---------|-------|
| Local File Destination | `local_file_destination` | CSV / JSON paths under `data/out/` |
| Excel Destination | `excel_destination` | Write `.xlsx` |
| Snowflake Destination | `snowflake_destination` | Demo → filesystem mock; real needs warehouse creds |
| **Databricks Job** | `databricks_job` | Orchestration: trigger Jobs API run (workspace + token + job_id). Demo → sidecar JSON under `data/out/databricks_demo/`. **Not** an embedded Spark engine |
| SFTP Destination | `sftp_destination` | Demo → `data/out/sftp_mock/` — **no real upload** |
| Postgres Destination | `postgres_destination` | Demo → SQLite + CSV under `data/out/postgres_demo/` |
| MySQL Destination | `mysql_destination` | Demo → SQLite pattern |
| SQLite Destination | `sqlite_destination` | Local DB write |
| Archive Files | `archive_files` | Move processed inputs |
| Logger / Metrics | `logger_metrics` | Rows in/out, duration |

### Scheduler (Community self-hosted)

- **In-process cron scheduler** — enable per pipeline (cron + timezone); persists under `data/schedules/`; survives API restart
- UI: Enable schedule / cron expression / timezone in the sidebar
- API: `GET/PUT /api/pipelines/{id}/schedule`, `POST /api/scheduler/tick`
- **Open-core note:** Community = self-hosted single-process scheduler. **Cloud HA scheduler** is a planned Enterprise / paid lock — do not invent list prices

### Schema discovery (product feature)

- Backend: `formulaetl.schema.discover` + `POST /api/schema/discover` `{ component_type, config }` → `{ columns, sample_rows? }`
- Sources: Excel / local CSV-JSON / HTTP API demo fixture / SQLite / Postgres+MySQL demo / S3 demo fixture
- UI: **Discover schema** on sources; **Field Mapper** modal for visual column mapping; mappings persist into node config
- Demo polish: discovering `fixtures/sample/orders.xlsx` returns **Orders** columns (`Order ID`, `Customer Name`, …)

---

## Component palette — primary non-AI path (now)

The left **Components** palette lists every registered type from `GET /api/components`, grouped by category, with original colorful SVG icons and clear labels (no vendor trademark logos).

- **Drag** a component onto the React Flow canvas, or **click** to add it with sensible defaults
- **New blank** starts an empty pipeline so users can build API → map → transform → load without AI Build or Load demo
- AI Build and Load demo remain shortcuts; the palette is the main manual path

## Visual Field Mapper — Input · Variables · Output

What data engineers expect when mapping columns:

1. **Read schema** from connection / sample  
2. Show **all input columns** from that schema  
3. **Variables** middle pane — named intermediate expressions (reference input cols; outputs reference vars)  
4. **Editable + drag-and-drop** mapping (input → var → output)

**Shipped:** Near-fullscreen 3-pane Field Mapper + Discover + auto-map by name + Variables persistence + expression text for `out=expr`.

**Not claiming:** multi-output reject/lookup IDE tabs, or Spark-scale mapper.

### Lookup Join — wiring two sources

1. Drop **Lookup Join** on the canvas (two target handles: **left/in** = primary, **right** = lookup).  
2. Wire source A → left/in, source B → right (or set Lookup file instead of B).  
3. Set **Primary (left) join keys** and **Lookup (right) join keys**, choose **Join type** (`left` / `inner` / `right` / `full`) and **Match mode** (`all` / `first`).  
4. Optionally chain **Field Mapper** for Variables + output column logic.

**Field Mapper** does column/expression logic — it does **not** merge two streams; use Lookup Join for that.

---

## Honest Python Row note

`python_row` is the escape hatch for custom per-row / batch logic: **restricted Python sandbox**, not unrestricted host scripting. Sales should say:

> “Per-row or batch script in a restricted namespace — reviewable on the canvas. We do not run arbitrary host OS or network calls from that sandbox.”

---

## Not claiming (roadmap / Enterprise)

| Gap | Status |
|-----|--------|
| Advanced multi-output visual mapper IDE | Field Mapper 3-pane (Input/Variables/Output) shipped; multi-output reject tabs later |
| Spark / Big Data batch engine | Explicitly out of Community MVP — use **Databricks Job** to trigger *their* jobs |
| Joblets, shared contexts, enterprise lineage UI | Enterprise tier *(planned)* |
| Full JDBC catalog (Oracle, SQL Server, …) | After Postgres / MySQL pattern |
| Salesforce / SAP / mainframe | Later |
| Cloud HA multi-node scheduler | Enterprise / paid *(planned)* — Community ships self-hosted poller |
| Airflow / Kestra exporters | Orchestration roadmap |

---

## Demo paths to show

1. **Kafka → Databricks** — `demos/api-kafka-databricks` (fixture Kafka → Field Mapper → Databricks Job demo)
2. **S3 → Databricks** — `demos/s3-databricks` (S3 mock → Databricks Job trigger)
3. **Lookup + Variables** — `demos/lookup-join-mapper` — two CSV sources → Lookup Join → Field Mapper (Variables) → File
4. **Core path** — Excel → Field Mapper → Filter → Sort → Aggregate → File
5. `demos/excel-to-file` — Excel → Schema Map → Transform → File  
6. `demos/python-row-flex` — API → map → Python Row → File  
7. `demos/s3-pgp-snowflake` — S3 → PGP → Validate → Snowflake demo → Archive  
8. Existing Excel, SFTP, Postgres, API demos under `demos/`

## Open-core honesty

- **OSS core stays:** visual canvas, runner, Field Mapper Variables, Lookup Join, Kafka Source, Databricks Job orchestration, Community scheduler, AI Build shortcut  
- **Enterprise locks later *(planned)*:** SSO, RBAC, lineage UI, HA scheduler — no fabricated prices  
- Icons are **original SVG/CSS** with text labels (S3 Source, Kafka Source, Databricks Job) — never official AWS / Kafka / Databricks trademark logo assets
