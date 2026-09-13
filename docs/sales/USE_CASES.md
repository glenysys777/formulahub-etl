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
| Lookup / light join | Lookup Join (left/inner on keys; file or second input) |
| Local DB pattern | SQLite Source / SQLite Destination (`data/demo.db`) |
| **Sort rows** | **Sort** (`col:asc` / `col:desc`) |
| **Expression field mapping** | **Field Mapper** — `out=expr`, filter, drop_unmapped (MVP visual mapper; not a full multi-output IDE) |
| **Aggregate (lite)** | **Aggregate** — group_by + sum/count/min/max/avg |
| **Custom per-row logic** | **Python Row** — sandboxed Python |
| **PGP encrypt + decrypt** | `pgp_encrypt` / `pgp_decrypt` |
| **XML records → rows** | `xml_parser` (tag / xpath-lite) |
| **MySQL param shape** | `mysql_source` / `mysql_destination` (demo → SQLite) |

### Honesty on SFTP & Postgres demos

| Component | What demo does (`FORMULAETL_DEMO=1` or host=`demo`) | What production needs |
|-----------|-----------------------------------------------------|------------------------|
| `sftp_source` | Copies from `fixtures/sample/` into staging — **no real SFTP** | host, port, username, password or key_path, `FORMULAETL_DEMO=0` |
| `sftp_destination` | Writes under `data/out/sftp_mock/` — **no real upload** | same credentials + `FORMULAETL_DEMO=0` |
| `postgres_source` | Reads **SQLite** `data/demo.db` or fixture rows — **not live Postgres** | DSN or host/db/user/password + `FORMULAETL_DEMO=0` + network |
| `postgres_destination` | Writes SQLite + CSV under `data/out/postgres_demo/` | real DSN + `FORMULAETL_DEMO=0` |

## Partial / params-only today

| Use case | Status |
|----------|--------|
| Real AWS S3 / real Snowflake | Component exists; needs credentials + `FORMULAETL_DEMO=0` |
| Real SFTP / real Postgres | Components exist; need credentials + `FORMULAETL_DEMO=0` (demo mocks the wire) |
| Filter rows | Component exists |
| Multi-step transforms | Chain Transform nodes |

## Not matched yet (roadmap — say this clearly)

| Use case | Planned |
|----------|---------|
| SQL Server / Oracle / full JDBC catalog | Next after Postgres pattern |
| Kafka / event streams | Later |
| Salesforce / SAP / mainframe | Later |
| Spark large-scale | Later |
| Shared joblets / contexts / enterprise lineage UI | Enterprise tier *(planned)* |

## How to talk to clients

> “We match the visual ETL jobs that keep renewals: **Field Mapper expressions, sort, aggregate, filter, PGP encrypt/decrypt, Excel/API/XML, SFTP, Postgres/MySQL shapes**, plus **Python Row** for custom logic in a sandbox. Demo mode mocks SFTP/DB so you can run without credentials. We’re not claiming Spark or a full multi-output mapper IDE on day one.”
