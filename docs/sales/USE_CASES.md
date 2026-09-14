# FormulaHub ETL — Use cases matched vs roadmap

Honest MVP map for client conversations.  
**Product:** FormulaHub ETL (Lynkx) · [formulahub.io/etl](https://formulahub.io/etl)

For step-by-step “how to build” each major case, see [USE_CASES_HOW.md](./USE_CASES_HOW.md).

## Matched now (demo-ready)

| Use case | Flow |
|----------|------|
| Encrypted file drop → warehouse | S3/File → PGP → Parse → Validate → Transform → Snowflake/File → Archive |
| Reject handling | Schema Validate → good path + rejects file |
| Column rename / date cast | Schema Map / Field Mapper + Transform |
| AI from English | AI Build → graph + params |
| **API → map → transform → load** | HTTP API → Schema Map / Field Mapper → Transform → Validate → Destination |
| **Excel / spreadsheet → load** | **Excel Source → Schema Map / Field Mapper → Transform → Validate → CSV and/or Excel Destination** |
| **SFTP → Excel/file → load** | **SFTP Source → Excel/CSV → Map → File (+ optional SFTP Destination)** |
| **DB / Postgres → file** | **Postgres Source → File / Postgres Destination** |
| JSON array → rows | JSON Parser (+ optional path / json_path) |
| Dedupe on keys | Dedupe (keep first/last) |
| Lookup / join | Lookup Join (left/inner/right/full; match all/first; file or second input on right handle) |
| Local DB pattern | SQLite Source / SQLite Destination (`data/demo.db`) |
| **Sort rows** | **Sort** (`col:asc` / `col:desc`) |
| **Expression field mapping** | **Field Mapper** — Input · Variables · Output; `out=expr`, filter, drop_unmapped |
| **Aggregate (lite)** | **Aggregate** — group_by + sum/count/min/max/avg |
| **Custom per-row logic** | **Python Row** — sandboxed Python |
| **PGP encrypt + decrypt** | `pgp_encrypt` / `pgp_decrypt` |
| **XML records → rows** | `xml_parser` (tag / xpath-lite) |
| **MySQL param shape** | `mysql_source` / `mysql_destination` (demo → SQLite) |
| **Kafka → map → job trigger** | **Kafka Source** (demo fixture) → Field Mapper → **Databricks Job** (demo sidecar) |
| **S3 → Databricks orchestration** | **S3 Source** → **Databricks Job** trigger (not embedded Spark) |
| **Schedule in one place** | Enable cron + timezone on a pipeline (Community self-hosted poller) |

### Honesty on SFTP & Postgres demos

| Component | What demo does (`FORMULAETL_DEMO=1` or host=`demo`) | What production needs |
|-----------|-----------------------------------------------------|------------------------|
| `sftp_source` | Copies from `fixtures/sample/` into staging — **no real SFTP** | host, port, username, password or key_path, `FORMULAETL_DEMO=0` |
| `sftp_destination` | Writes under `data/out/sftp_mock/` — **no real upload** | same credentials + `FORMULAETL_DEMO=0` |
| `postgres_source` | Reads **SQLite** `data/demo.db` or fixture rows — **not live Postgres** | DSN or host/db/user/password + `FORMULAETL_DEMO=0` + network |
| `postgres_destination` | Writes SQLite + CSV under `data/out/postgres_demo/` | real DSN + `FORMULAETL_DEMO=0` |
| `kafka_source` | Reads `fixtures/sample/kafka_orders.jsonl` — **no broker** | brokers + topic; optional `pip install formulaetl[kafka]` or `confluent-kafka` |
| `databricks_job` | Writes SUCCESS sidecar under `data/out/databricks_demo/` | workspace_host + token + job_id + `FORMULAETL_DEMO=0` |

## Partial / params-only today

| Use case | Status |
|----------|--------|
| Real AWS S3 / real Snowflake | Component exists; needs credentials + `FORMULAETL_DEMO=0` |
| Real SFTP / real Postgres | Components exist; need credentials + `FORMULAETL_DEMO=0` (demo mocks the wire) |
| Real Kafka / real Databricks Jobs API | Components exist; need broker/workspace creds + optional extras + `FORMULAETL_DEMO=0` |
| Filter rows | Component exists |
| Multi-step transforms | Chain Transform nodes |

## Not matched yet (roadmap — say this clearly)

| Use case | Planned |
|----------|---------|
| SQL Server / Oracle / full JDBC catalog | Next after Postgres pattern |
| Salesforce / SAP / mainframe | Later |
| Embedded Spark large-scale engine | Out of scope — orchestrate *their* Databricks jobs instead |
| Shared joblets / contexts / enterprise lineage UI | Enterprise tier *(planned)* |
| Cloud HA multi-node scheduler | Enterprise / paid *(planned)* — Community ships self-hosted cron |

## How to talk to clients

> **Honesty:** Kafka Source + Databricks Job Trigger are production-shaped (real client libraries / Jobs API when credentials set) but **CI and default DEMO=1 use fixtures/sidecars — live Kafka/Databricks against customer clusters is unproven until a design-partner run.** Do not claim live E2E in CI.

> “We match the visual ETL jobs companies run now: **API read, Kafka read, S3 → Databricks job trigger, Field Mapper with Variables, Lookup Join (left/inner/right/full), schedule in one place**. AI Build is a shortcut — the palette and params stand alone. Demo mode mocks Kafka/Databricks/SFTP/DB so you can run without credentials. Community includes a self-hosted scheduler; HA cloud scheduling is a later Enterprise lock. We’re not claiming an embedded Spark engine or fabricated price lists.”
