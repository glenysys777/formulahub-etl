# Customer001 LOCAL wedge (Mac + local Postgres)

**Classification labels (honest):**

| Label | Meaning |
|-------|---------|
| `LOCAL_PROVEN` | Real local filesystem + real local Postgres `INSERT` via **psycopg** (`FORMULAETL_DEMO=0`) |
| `LOCAL/DEMO` | Same DAG; Postgres node writes SQLite/CSV mirror under `data/out/` |
| `LOCAL_ONLY` | Skip / no Postgres marker — **not** a cloud claim |
| `LIVE_EXTERNAL` | **UNPROVEN / out of scope** (SFTP/S3/Snowflake/Databricks). Never claim LIVE from this wedge. |

Founder-chosen path: **prove on Mac files + Homebrew Postgres first.**

## Mac Postgres (founder pack — current)

| Item | Value |
|------|-------|
| Engine | **Postgres 16** via Homebrew |
| Locale fix | `export LC_ALL=en_US.UTF-8` (and `LANG`) before start — avoids postmaster multithreaded startup failure |
| Helper | Desktop pack: **`FormulaHub-ETL-Mac/START-POSTGRES.command`** (also `scripts/START-POSTGRES.command` in repo) |
| Listen | `localhost:5432` — **trust** / local socket OK |
| Database | **`formulahub_wedge`** |
| Table | **`customers_wedge`** `(customer_id, email, signup_date, loaded_at)` |
| Pack fixtures | `fixtures/keys/demo_*.asc`, `fixtures/sample/customers.csv`, orders CSVs |

### Start Postgres on Mac

```bash
# Double-click in the unzipped Mac pack:
#   FormulaHub-ETL-Mac/START-POSTGRES.command
#
# Or from a Terminal in the repo:
export LC_ALL=en_US.UTF-8
export LANG=en_US.UTF-8
bash scripts/START-POSTGRES.command
```

What the helper does:

1. Sets `LC_ALL` / `LANG` to `en_US.UTF-8`
2. `brew services start postgresql@16` (installs formula if missing)
3. Ensures DB `formulahub_wedge` exists
4. Applies `fixtures/sql/formulahub_wedge.sql` (`customers_wedge` DDL)
5. Prints a ready DSN for `FORMULAETL_DEMO=0` runs

### LOCAL_PROVEN write (real psycopg)

```bash
cd FormulaHub-ETL   # or repo root
python3 -m pip install -e packages/runner -e packages/api
python3 -m pip install pytest 'psycopg[binary]>=3.1' 'cryptography>=42.0'
python3 scripts/seed_demo.py

# Prefer DEMO=0 for real INSERT (not the SQLite/CSV mirror)
export FORMULAETL_DEMO=0
# Trust / local socket (no password) — Mac founder default:
export LOCAL_POSTGRES_DSN="host=localhost port=5432 dbname=formulahub_wedge"
# Optional explicit table (default customers_wedge):
export LOCAL_POSTGRES_TABLE=customers_wedge

python3 scripts/customer001_local_wedge.py --mode postgres
```

TCP + password form also works if you configured scram/md5:

```bash
export LOCAL_POSTGRES_DSN="host=127.0.0.1 port=5432 dbname=formulahub_wedge user=YOURUSER password=…"
```

### DEMO mirror (no Postgres required)

```bash
export FORMULAETL_DEMO=1
python3 scripts/customer001_local_wedge.py --mode demo
```

## Pipeline (customer001)

```
data/drop/customer001/orders.csv.pgp
  → pgp_decrypt (fixtures/keys/demo_private.asc)
  → csv_parser
  → schema_validate  ──rejects──► data/rejects/customer001/…
  → Field Mapper → lookup → dedupe
  → project → customers_wedge columns
  → postgres_destination  (formulahub_wedge.customers_wedge when DEMO=0)
  → archive_files
```

Artifacts: `demos/customer001-local-wedge/` · `fixtures/customer001_local_wedge/` · `scripts/customer001_local_wedge.py`

## Expected counts

| Symbol | Meaning | Value |
|--------|---------|------:|
| **N** | CSV parse `rows_out` | 12 |
| **R** | schema rejects | 2 |
| **D** | dedupe drops | 2 |
| **L** | Postgres `rows_out` | 8 |

**Invariant:** `N = R + D + L` → `12 = 2 + 2 + 8`.

## Adapted demos → local files + local Postgres

Original cloud/demo destinations stay as DEMO. **LOCAL_PROVEN** variants retarget to filesystem + `formulahub_wedge.customers_wedge` (never S3/Snowflake LIVE):

| Original | LOCAL Postgres variant |
|----------|------------------------|
| `demos/s3-pgp-snowflake/` | `demos/s3-pgp-snowflake/pipeline.local-postgres.json` |
| `demos/core-path/` | `demos/core-path/pipeline.local-postgres.json` |
| `demos/lookup-join-mapper/` | `demos/lookup-join-mapper/pipeline.local-postgres.json` |

```bash
export FORMULAETL_DEMO=0
export LOCAL_POSTGRES_DSN="host=localhost port=5432 dbname=formulahub_wedge"
python3 -m formulaetl.cli run demos/s3-pgp-snowflake/pipeline.local-postgres.json
python3 -m formulaetl.cli run demos/core-path/pipeline.local-postgres.json
python3 -m formulaetl.cli run demos/lookup-join-mapper/pipeline.local-postgres.json
```

These use pack fixtures (`fixtures/keys/demo_*.asc`, `fixtures/sample/*`). Classification: **LOCAL_PROVEN** when DEMO=0 + reachable Postgres; otherwise DEMO mirror / skip. **LIVE_EXTERNAL remains UNPROVEN.**

## Failure injections

| ID | Scenario | Script |
|----|----------|--------|
| F1–F6 | bad PGP, missing file, bad CSV, schema drift, dest down, retry | `scripts/customer001_fail_injections/` |

## Gaps — do **not** claim LIVE

| Path | Status |
|------|--------|
| Snowflake bulk | **GAP / UNPROVEN** |
| Databricks | **GAP / UNPROVEN** |
| External SFTP / S3 | **GAP / UNPROVEN** |

## Related

- Evidence matrix: `docs/CUSTOMER001_EVIDENCE_MATRIX.md`
- DDL: `fixtures/sql/formulahub_wedge.sql`
- Cloud live harness: `scripts/live_wedge_e2e.py` — **LIVE_EXTERNAL / UNPROVEN** by default
