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
| **Field Mapper** | Field Mapper node | Expression mappings (`out=expr`), optional filter, `drop_unmapped`; visual drag source → target; Discover schema. **MVP** — not a multi-output lookup canvas IDE |

### Transform & quality

| Component | Type id | Notes |
|-----------|---------|-------|
| Transform | `transform` | Date / type casts, light maps |
| Schema Validate | `schema_validate` | Required columns + types; reject stream |
| Filter | `filter` | Expression filter |
| Sort Rows | `sort` | Keys as `col:asc` / `col:desc` |
| Aggregate | `aggregate` | `group_by` + sum / count / min / max / avg |
| Dedupe | `dedupe` | Keep first / last on keys |
| Lookup Join | `lookup_join` | Left / inner on keys; file or second input |
| Python Row | `python_row` | Per-row or batch **sandboxed Python** (row/rows + safe builtins; no open / network / os) |
| PGP Decrypt / Encrypt | `pgp_decrypt` / `pgp_encrypt` | Demo keys under `fixtures/keys/` |

### Destinations & ops

| Component | Type id | Notes |
|-----------|---------|-------|
| Local File Destination | `local_file_destination` | CSV / JSON paths under `data/out/` |
| Excel Destination | `excel_destination` | Write `.xlsx` |
| Snowflake Destination | `snowflake_destination` | Demo → filesystem mock; real needs warehouse creds |
| SFTP Destination | `sftp_destination` | Demo → `data/out/sftp_mock/` — **no real upload** |
| Postgres Destination | `postgres_destination` | Demo → SQLite + CSV under `data/out/postgres_demo/` |
| MySQL Destination | `mysql_destination` | Demo → SQLite pattern |
| SQLite Destination | `sqlite_destination` | Local DB write |
| Archive Files | `archive_files` | Move processed inputs |
| Logger / Metrics | `logger_metrics` | Rows in/out, duration |

### Schema discovery (product feature)

- Backend: `formulaetl.schema.discover` + `POST /api/schema/discover` `{ component_type, config }` → `{ columns, sample_rows? }`
- Sources: Excel / local CSV-JSON / HTTP API demo fixture / SQLite / Postgres+MySQL demo / S3 demo fixture
- UI: **Discover schema** on sources; **Field Mapper** modal for visual column mapping; mappings persist into node config
- Demo polish: discovering `fixtures/sample/orders.xlsx` returns **Orders** columns (`Order ID`, `Customer Name`, …)

---

## Visual Field Mapper — MVP (now)

What data engineers expect when mapping columns:

1. **Read schema** from connection / sample  
2. Show **all columns** from that schema  
3. **Editable + drag-and-drop** mapping (source → target)

**Shipped:** Discover + Field Mapper + auto-map by name + expression text for non-trivial `out=expr`.

**Not claiming:** full multi-output visual mapper IDE, lookup-join canvas designer, or Spark-scale mapper.

---

## Honest Python Row note

`python_row` is the escape hatch for custom per-row / batch logic: **restricted Python sandbox**, not unrestricted host scripting. Sales should say:

> “Per-row or batch script in a restricted namespace — reviewable on the canvas. We do not run arbitrary host OS or network calls from that sandbox.”

---

## Not claiming (roadmap / Enterprise)

| Gap | Status |
|-----|--------|
| Advanced multi-output visual mapper IDE | Field Mapper MVP shipped; advanced IDE later |
| Spark / Big Data batch | Explicitly out of Community MVP |
| Joblets, shared contexts, enterprise lineage UI | Enterprise tier *(planned)* |
| Full JDBC catalog (Oracle, SQL Server, …) | After Postgres / MySQL pattern |
| Kafka / event streams, Salesforce / SAP / mainframe | Later |
| Airflow / Kestra exporters | Orchestration roadmap |

---

## Demo paths to show

1. **Core path** — Excel → Field Mapper → Filter → Sort → Aggregate → File (open Field Mapper → Discover from upstream)  
2. `demos/excel-to-file` — Excel → Schema Map → Transform → File  
3. `demos/python-row-flex` — API → map → Python Row → File  
4. `demos/s3-pgp-snowflake` — S3 → PGP → Validate → Snowflake demo → Archive  
5. Existing Excel, SFTP, Postgres, API demos under `demos/`
