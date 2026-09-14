# Customer001 LOCAL wedge (Mac + local Postgres)

**Classification labels (honest):**

| Label | Meaning |
|-------|---------|
| `LOCAL_PROVEN` | Real local filesystem drop + real local Postgres `INSERT` (`FORMULAETL_DEMO=0`) |
| `LOCAL/DEMO` | Same DAG; Postgres node writes SQLite/CSV mirror under `data/out/customer001/` |
| `LOCAL_ONLY` | Marker for skip / no Postgres — **not** a cloud claim |
| `LIVE_EXTERNAL` | **Out of scope** here (SFTP/S3/Snowflake/Databricks). Do **not** claim LIVE from this wedge. |

This path is the founder-chosen production-shaped wedge: **prove on Mac files + Postgres first**.

## Pipeline

```
data/drop/customer001/orders.csv.pgp
  → pgp_decrypt (fixtures/keys/demo_private.asc)
  → csv_parser
  → schema_validate  ──rejects──► data/rejects/customer001/orders_rejects.csv
  → Field Mapper (tmap)
  → lookup_join (fixtures/customer001_local_wedge/customers_lookup.csv)
  → dedupe (order_id)
  → logger_metrics
  → postgres_destination
  → archive_files → data/archive/customer001/
```

Artifacts:

- Pipeline: `demos/customer001-local-wedge/pipeline.json`
- Fixtures: `fixtures/customer001_local_wedge/`
- Harness: `scripts/customer001_local_wedge.py`
- Fail drills: `scripts/customer001_fail_injections/`
- Evidence matrix: `docs/CUSTOMER001_EVIDENCE_MATRIX.md`

## Expected counts (mathematical reconciliation)

From `fixtures/customer001_local_wedge/expected_counts.json`:

| Symbol | Meaning | Value |
|--------|---------|------:|
| **N** | CSV parse `rows_out` | 12 |
| **R** | schema_validate `rows_rejected` (bad email) | 2 |
| **D** | dedupe `rows_rejected` (dup `order_id`) | 2 |
| **L** | postgres_destination `rows_out` | 8 |

**Invariant:** `N = R + D + L` → `12 = 2 + 2 + 8`.

Also recorded by the harness: input bytes, archived files/bytes, per-node `duration_ms`, peak RSS (process).

## Mac setup (Homebrew Postgres)

```bash
# 1) Tools
brew install postgresql@16
brew services start postgresql@16

# 2) Role + DB (once)
createuser -s formula || true
psql postgres -c "ALTER USER formula WITH PASSWORD 'formula';"
createdb -O formula formulaetl || true

# 3) Repo
cd formulahub-etl
python3 -m pip install -e packages/runner -e packages/api
python3 -m pip install pytest 'psycopg[binary]>=3.1' 'cryptography>=42.0'
python3 scripts/seed_demo.py

# 4a) DEMO mirror (no Postgres required)
python3 scripts/customer001_local_wedge.py --mode demo

# 4b) LOCAL_PROVEN real Postgres write
export FORMULAETL_DEMO=0
export LOCAL_POSTGRES_DSN="host=127.0.0.1 port=5432 dbname=formulaetl user=formula password=formula"
python3 scripts/customer001_local_wedge.py --mode postgres

# CLI (DEMO dest unless you edit pipeline host/DSN):
FORMULAETL_DEMO=1 python3 -m formulaetl.cli run demos/customer001-local-wedge/pipeline.json
```

Linux (apt) equivalent used in CI agents:

```bash
sudo apt-get install -y postgresql postgresql-client
sudo service postgresql start
sudo -u postgres createuser -s formula
sudo -u postgres psql -c "ALTER USER formula PASSWORD 'formula';"
sudo -u postgres createdb -O formula formulaetl
```

## Pytest

```bash
# Always-on LOCAL/DEMO reconcile (CI-safe):
python3 -m pytest tests/integration/test_customer001_local_wedge.py -q

# Real Postgres path (skips with LOCAL_ONLY if DSN unreachable):
FORMULAETL_DEMO=0 LOCAL_POSTGRES_DSN='host=127.0.0.1 dbname=formulaetl user=formula password=formula' \
  python3 -m pytest tests/integration/test_customer001_local_wedge.py -q -k postgres
```

CI: GitHub Actions may attach a Postgres service and set `LOCAL_POSTGRES_DSN`. If the service is absent, the postgres test **skips** with a clear `LOCAL_ONLY` marker — that is **not** LIVE_EXTERNAL evidence.

## Failure injections (documented)

| ID | Scenario | How |
|----|----------|-----|
| F1 | Bad PGP payload | `bash scripts/customer001_fail_injections/01_bad_pgp.sh` |
| F2 | Missing drop file | `…/02_missing_file.sh` |
| F3 | Malformed CSV inside PGP | `…/03_malformed_csv.sh` |
| F4 | Schema drift (new required col) | `…/04_schema_drift.sh` |
| F5 | Destination down (bad PG port) | `…/05_destination_down.sh` |
| F6 | Retry / re-run replace | `…/06_retry.sh` |

Run all: `bash scripts/customer001_fail_injections/run_all.sh`

## Gaps — do **not** claim LIVE

| Path | Status |
|------|--------|
| Snowflake bulk load | **GAP** — document only; demo Snowflake CSV is not LIVE |
| Databricks Jobs / SQL | **GAP** — not exercised by this wedge |
| External SFTP / S3 | **GAP** — local drop only; see `docs/design-partner/LIVE_WEDGE.md` for cloud harness (UNPROVEN without partner creds) |

## Related

- Scale bench (mock S3 → snowflake-demo): `scripts/local_wedge_bench.py` — classification **LOCAL/DEMO**, not this customer001 LOCAL Postgres path
- Cloud live harness: `scripts/live_wedge_e2e.py` — **LIVE_CLOUD / UNPROVEN** by default
