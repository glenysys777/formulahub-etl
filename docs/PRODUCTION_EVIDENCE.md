# Production evidence log

Claims in sales/README are **not** evidence. Each row is a statement we are willing to make only with a command, git SHA, and date.

**Audit SHA (main / Phase A merge):** `cecb1af` (PR #4)  
**Phase B merge tip:** `f2d8b57`  
**Phase C merge tip:** `dce51a6`  
**Phase D+E merge tip:** `1b82aa5`  
**Phase F merge tip:** `3d1d9c9`  
**Phase G merge tip:** `5525b26`  
**Phase I (wedge evidence) tip:** `a4978a1`  
**Phase Perf (this PR) tip:** `0067c52`  
**Agent run date:** 2026-09-14  
**Python:** 3.12.3 · **Node:** 22.x · **pytest:** 9.x

Fill status: `PROVEN` | `UNPROVEN` | `FAILED` | `EMPTY`

**Classification legend:** `LOCAL/DEMO` = fixtures / mock S3 / snowflake-demo CSV. `LIVE_CLOUD` = real partner credentials. This document never equates green CI with LIVE_CLOUD.

---

## A. Build and tests

| ID | Claim | Status | Command | Result | SHA | Date |
|----|-------|--------|---------|--------|-----|------|
| A1 | Pytest suite on `tests/` (default CI) | PROVEN | `python3 scripts/seed_demo.py && python3 -m pytest tests -q -m "not live and not bench"` | **167 passed**, 1 skipped (`RUN_CSV_1M`), 6 deselected (`live`+`bench`). `FORMULAETL_DEMO=1`. Not live AWS/SFTP. | this PR (`0067c52`) | 2026-09-14 |
| A2 | Web production build | PROVEN | `cd apps/web && npm run build` | Optional CI job `web-build` | `5525b26` | 2026-09-14 |
| A3 | GitHub Actions CI on `main` / PRs | PROVEN | `.github/workflows/ci.yml` | pytest DEMO=1 `-m "not live and not bench"`; optional npm build. **No live cloud. No heavy bench.** | `a4978a1` | 2026-09-14 |
| A4 | Default env is demo | PROVEN | Read `tests/conftest.py` | Tests force `FORMULAETL_DEMO=1` | `cecb1af` | 2026-09-14 |
| A5 | CSV 10K streaming benchmark | PROVEN | Phase C | Unchanged | `dce51a6` | 2026-09-14 |

---

## B. Demo runs (fixtures, not customer systems)

| ID | Claim | Status | Command | Result | SHA | Date |
|----|-------|--------|---------|--------|-----|------|
| B1 | Flagship S3→PGP→Snowflake **demo** CLI | PROVEN **demo only** | `FORMULAETL_DEMO=1 python3 -m formulaetl.cli run demos/s3-pgp-snowflake/pipeline.json` | Inline demo hosts still work. | `3d1d9c9` | 2026-09-14 |
| B1b | Excel + API-map demos | PROVEN **demo only** | CLI / pytest | Unchanged | `1b82aa5` | 2026-09-14 |
| B2–B4 | Other demos / screenshots | PROVEN **demo only** | pytest / CLI | Unchanged intent | `dce51a6` | 2026-09-14 |

---

## C. Live systems (customer-shaped) — classification **LIVE_CLOUD**

| ID | Claim | Status | Command | Result | SHA | Date |
|----|-------|--------|---------|--------|-----|------|
| C0 | Live wedge harness exists (S3\|SFTP→PGP→CSV→validate→map→PG\|SF→archive) | PROVEN **harness only** | `python3 scripts/live_wedge_e2e.py --check` + unit tests | Gate skips without creds; CI uses `-m "not live"`. Does **not** prove cloud connectivity. | `5525b26` | 2026-09-14 |
| C1 | Live AWS S3 read in wedge | UNPROVEN | `RUN_LIVE_WEDGE=1 FORMULAETL_DEMO=0` + `LIVE_S3_*` / AWS creds | Not run in this agent / CI — **H blocked on credentials** | — | — |
| C2 | Live SFTP read in wedge | UNPROVEN | `LIVE_SOURCE=sftp` + `LIVE_SFTP_*` | Not run | — | — |
| C3 | Live PGP decrypt with partner key | UNPROVEN | `LIVE_PGP_PRIVATE_KEY_PATH` | Not run | — | — |
| C4 | Live Postgres load in wedge | UNPROVEN | `LIVE_DEST=postgres` + `LIVE_POSTGRES_*` | Not run | — | — |
| C5 | Live Snowflake load in wedge | UNPROVEN | `LIVE_DEST=snowflake` + `LIVE_SNOWFLAKE_*` | Not run | — | — |
| C6 | Full live wedge E2E (source→archive) | UNPROVEN | `docs/design-partner/LIVE_WEDGE.md` | **Do not mark PROVEN** until a real run’s JSON (redacted) is pasted here with SHA + date. **Do not fake LIVE PROVEN.** | — | — |
| C7 | Databricks Free Edition SQL smoke (`SELECT 1` via Statement Execution API) | **PROVEN Soft-PASS LIVE_EXTERNAL SQL only** | Founder Free Edition workspace + Serverless Starter Warehouse; `FORMULAETL_DEMO=0`; PAT **not** stored in repo | Redacted: [`docs/evidence/databricks_sql_smoke_redacted.json`](./evidence/databricks_sql_smoke_redacted.json) (`host`/`warehouse_id`/`SUCCEEDED`/`total_row_count=1`). SQL only — Jobs Soft-PASS is C8. | `9f8fc2b` | 2026-09-14 |
| C8 | Databricks Free Edition Jobs smoke (Jobs API `run-now` + poll via FormulaETL) | **PROVEN Soft-PASS LIVE_EXTERNAL Jobs only** | `via`=`formulaetl.components.databricks_job.DatabricksJob.run`; `FORMULAETL_DEMO=0`; Free Edition Jobs API; PAT **not** stored in repo | Redacted: [`docs/evidence/databricks_job_smoke_redacted.json`](./evidence/databricks_job_smoke_redacted.json) (`side_effects.state=SUCCESS`, `life=TERMINATED`, `duration_ms≈21443`; notebook `/Shared/formulahub_etl_smoke`). **Does not** prove Spark-inside-FormulaETL or full LIVE wedge. After merge onto `main`, record merge SHA here. | this PR — **replace with merge SHA on main** | 2026-09-14 |

CI never sets `RUN_LIVE_WEDGE`. Green Actions ≠ LIVE_CLOUD PROVEN. C7/C8 are manual founder evidence outside CI.

---

## D. Architecture facts (code, not a passing test)

| ID | Claim | Status | Evidence | SHA | Date |
|----|-------|--------|----------|-----|------|
| D1 | Runner DAG still sequential **inside** a worker | PROVEN | `PipelineRunner.run` topological loop | `1b82aa5` | 2026-09-14 |
| D2–D4 | ArtifactHandle / RowBatch / CSV chunking | PROVEN | Phase B/C | `dce51a6` | 2026-09-14 |
| D14 | Lazy RowBatch chain + streaming sinks + gpg path-to-path | PROVEN | `sdk/adapter.py` `run_batched`, `consume_dataset`, `pgp_decrypt` gpg | this PR (`0067c52`) | 2026-09-14 |
| D5 | Run history is durable SQLite | PROVEN | Phase D+E | `1b82aa5` | 2026-09-14 |
| D6 | Optional API key when `FORMULAETL_API_KEY` set | PROVEN | Phase F | `3d1d9c9` | 2026-09-14 |
| D7 | Secrets via SecretProvider refs | PROVEN | Phase F | `3d1d9c9` | 2026-09-14 |
| D8–D9 | SFTP host-key reject / S3 pagination | PROVEN | Phase C | `dce51a6` | 2026-09-14 |
| D10–D12 | Async 202 / concurrent workers / version pin | PROVEN | Phase D+E | `1b82aa5` | 2026-09-14 |
| D13 | GET run exposes summary + node_runs + events | PROVEN | Phase G `get_run` + tests | `5525b26` | 2026-09-14 |

---

## E–G. Historical phases

Phase B `f2d8b57` · Phase C `dce51a6` · Phase D+E `1b82aa5` · Phase F `3d1d9c9` · Phase G `5525b26` — see prior sections in git history.

---

## H. Phase F — Connections + Secret refs

Merged on main as `3d1d9c9`. See prior H1–H8 claims (connections CRUD, test, SecretProvider, mask, API key, CONNECTIONS.md).

---

## I. Phase G — Validate + design-partner docs + CI

Merged on main as `5525b26`. Validate API, design-partner pack, CI `-m "not live"`, live harness (UNPROVEN cloud). See prior I1–I7.

---

## J. LOCAL/DEMO wedge correctness + scale evidence (Phase Perf `0067c52`)

**Classification: LOCAL/DEMO only — never LIVE_CLOUD.**

Harness: `scripts/local_wedge_bench.py`  
Path: **S3-demo → PGP → CSV → validate → column_map → dedupe → snowflake-demo → archive** (+ rejects file).  
Reconciliation invariant (must hold or test fails): **`N = R + D + L`** where  
- `N` = CSV parse `rows_out`  
- `R` = schema_validate `rows_rejected`  
- `D` = dedupe `rows_rejected` (duplicate drops)  
- `L` = destination `rows_out`  

| ID | Claim | Status | Command | Result | SHA | Date |
|----|-------|--------|---------|--------|-----|------|
| J0 | Bench harness + pytest markers | PROVEN **LOCAL/DEMO** | `tests/bench/`, `pytest` marker `bench`, `make bench` / `RUN_BENCH=1` | Heavy scales skipped unless `RUN_BENCH=1`; CI excludes `-m bench` | `a4978a1` | 2026-09-14 |
| J1 | Always-on correctness (small N) | PROVEN **LOCAL/DEMO** | `pytest tests/bench -m "not bench"` | plan math + 200-row + file→file reconcile | this PR (`0067c52`) | 2026-09-14 |
| J2 | Scale 10K full wedge | PROVEN **LOCAL/DEMO** | `RUN_BENCH=1 … --scales 10000` | See after table | this PR (`0067c52`) | 2026-09-14 |
| J3 | Scale 100K full wedge | PROVEN **LOCAL/DEMO** | `--scales 100000` | See after table | this PR (`0067c52`) | 2026-09-14 |
| J4 | Scale 1M full wedge | PROVEN **LOCAL/DEMO** | `--scales 1000000` | See after table | this PR (`0067c52`) | 2026-09-14 |
| J5 | Scale 10M optional | PROVEN **LOCAL/DEMO** | `BENCH_INCLUDE_10M=1 make bench-10m` | Completes (not ≤400 MB). See 10M row | this PR (`0067c52`) | 2026-09-14 |
| J6 | No full materialization regression | PROVEN | `pytest tests/unit/test_no_full_materialization.py` | Lazy/spill path keeps `result.rows` empty above threshold | this PR (`0067c52`) | 2026-09-14 |

### LOCAL/DEMO scale numbers (agent host, 2026-09-14)

**Phase I before** (`a4978a1`, in-process `ru_maxrss`, includes prior scales / fixture encrypt pollution at 1M):

| Scale | elapsed_s | peak_rss_mb | rows/sec | N=R+D+L |
|------:|----------:|------------:|---------:|:-------:|
| 10 000 | 0.296 | 62 | 33 759 | ✓ |
| 100 000 | 2.267 | 199 | 44 111 | ✓ |
| 1 000 000 | 23.298 | 1 432 | 42 921 | ✓ |
| 10 000 000 | — | — | skipped (likely OOM) | — |

**Phase Perf after** (child-process RSS; excludes fixture encrypt). Command:

```bash
make bench          # 10K + 100K + 1M → data/out/bench/local_wedge_results.json
# optional:
BENCH_INCLUDE_10M=1 make bench-10m
```

Host: Linux cloud agent, **4× Intel Xeon**, **~15 GiB RAM**, Python 3.12.3. `FORMULAETL_BATCH_SIZE` default 32768. Large PGP via **gpg** path-to-path.

| Scale | elapsed_s | peak_rss_mb | rows/sec | N | R | D | L | N=R+D+L |
|------:|----------:|------------:|---------:|--:|--:|--:|--:|:-------:|
| 10 000 | 0.107 | 39 | 93 306 | 10 000 | 100 | 198 | 9 702 | ✓ |
| 100 000 | 0.766 | 81 | 130 545 | 100 000 | 1 000 | 1 980 | 97 020 | ✓ |
| 1 000 000 | 6.901 | 306 | 144 899 | 1 000 000 | 10 000 | 19 800 | 970 200 | ✓ |
| 10 000 000 | 74.479 | 2 755 | 134 267 | 10 000 000 | 100 000 | 198 000 | 9 702 000 | ✓ |

1M vs Phase I: **RSS 1432→306 MB** (≤400 MB goal; stretch ≤250 MB not met). **Throughput 43k→145k rows/sec** (≥80k / ≥100k). 100K RSS 199→81 MB (≤150 MB). 10M **completes** (streaming + memory ceiling — no full-file RAM choke); RSS is mostly the dedupe key set, not a second full row copy.

Fixture encrypt/prep time is **excluded** from `elapsed_s` (pipeline wall in the child). Peak RSS via `resource.getrusage` in that child (Linux KB→MiB).

**Honesty:** these numbers are **LOCAL/DEMO** (mock S3 under `data/s3`, demo Snowflake CSV under `data/out`). They do **not** prove live AWS/SFTP/Snowflake throughput.

### How to re-run

```bash
make bench          # 10K + 100K + 1M → data/out/bench/local_wedge_results.json
make bench-pytest   # same scales via pytest -m bench
# optional:
BENCH_INCLUDE_10M=1 make bench-10m
```

See `docs/PERFORMANCE.md` for knobs and what is still DEMO.

---

---

## K. Customer001 LOCAL wedge (filesystem + optional local Postgres)

**Classification: LOCAL_PROVEN / LOCAL/DEMO — never LIVE_EXTERNAL.**

Docs: [`CUSTOMER001_LOCAL_WEDGE.md`](./CUSTOMER001_LOCAL_WEDGE.md) · Matrix: [`CUSTOMER001_EVIDENCE_MATRIX.md`](./CUSTOMER001_EVIDENCE_MATRIX.md)  
Harness: `scripts/customer001_local_wedge.py`  
Path: **local encrypted drop → PGP → CSV → validate → Field Mapper → lookup → dedupe → rejects → Postgres → archive**  
Reconciliation: **N=12 = R=2 + D=2 + L=8**.

| ID | Claim | Status | Command | Result | Date |
|----|-------|--------|---------|--------|------|
| K0 | Fixture + pipeline + docs | PROVEN **LOCAL_ONLY** | paths under `fixtures/customer001_local_wedge/`, `demos/customer001-local-wedge/` | Pack present | 2026-09-14 |
| K1 | DEMO reconcile always-on | PROVEN **LOCAL/DEMO** | `python3 scripts/customer001_local_wedge.py --mode demo` + pytest integration | N=R+D+L | 2026-09-14 |
| K2 | Real local Postgres INSERT → `formulahub_wedge.customers_wedge` | PROVEN **LOCAL_PROVEN** when DSN up; else skip **LOCAL_ONLY** | `FORMULAETL_DEMO=0 LOCAL_POSTGRES_DSN='host=localhost dbname=formulahub_wedge'` + Mac `START-POSTGRES.command` (LC_ALL=en_US.UTF-8) | Not LIVE_EXTERNAL; trust/local socket OK | 2026-09-14 |
| K3 | Adapted demos (s3-pgp / core-path / lookup) → local PG | PROVEN **LOCAL_PROVEN** when PG up | `demos/*/pipeline.local-postgres.json` | Files + customers_wedge; cloud dest UNPROVEN | 2026-09-14 |
| K4 | Snowflake bulk / external SFTP·S3 | **GAP / UNPROVEN** | — | Document only — do not claim LIVE. Databricks **SQL**/Jobs Soft-PASS are §C C7/C8 (not this LOCAL wedge). | 2026-09-14 |

---

## Notes

- Phase Perf adds streaming/lazy-chain + LOCAL/DEMO scale evidence; live wedge E2E (C1–C6) remains **UNPROVEN** until partner credentials exist.
- §C **C7**: Databricks Free Edition SQL smoke Soft-PASS (SQL only).
- §C **C8**: Databricks Free Edition Jobs smoke Soft-PASS (Jobs API via FormulaETL only; not Spark-inside-FormulaETL / full wedge).
- Customer001 LOCAL wedge (§K) proves filesystem + optional local Postgres only — **not** LIVE_EXTERNAL wedge.
- Readiness: validate + CI move **trust/ops** toward design-partner; live connectors stay DEMO until external evidence.
- See `docs/design-partner/` for operational pack.
- Pytest **count** this PR (default markers): **190 passed**, 1 skipped, 6 deselected (`live` + `bench`). Includes Customer001 LOCAL wedge tests.