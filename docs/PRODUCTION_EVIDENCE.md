# Production evidence log

Claims in sales/README are **not** evidence. Each row is a statement we are willing to make only with a command, git SHA, and date.

**Audit SHA (main / Phase A merge):** `cecb1af` (PR #4)  
**Phase B merge tip:** `f2d8b57`  
**Phase C merge tip:** `dce51a6`  
**Phase D+E merge tip:** `1b82aa5`  
**Phase F merge tip:** `3d1d9c9`  
**Phase G merge tip:** `5525b26`  
**Phase I (this PR) tip:** see SHA below after merge / this branch tip  
**Agent run date:** 2026-09-14  
**Python:** 3.12.3 · **Node:** 22.x · **pytest:** 9.x

Fill status: `PROVEN` | `UNPROVEN` | `FAILED` | `EMPTY`

**Classification legend:** `LOCAL/DEMO` = fixtures / mock S3 / snowflake-demo CSV. `LIVE_CLOUD` = real partner credentials. This document never equates green CI with LIVE_CLOUD.

---

## A. Build and tests

| ID | Claim | Status | Command | Result | SHA | Date |
|----|-------|--------|---------|--------|-----|------|
| A1 | Pytest suite on `tests/` (default CI) | PROVEN | `python3 scripts/seed_demo.py && python3 -m pytest tests -q -m "not live and not bench"` | **162 passed**, 1 skipped (`RUN_CSV_1M`), 6 deselected (`live`+`bench`). `FORMULAETL_DEMO=1`. Not live AWS/SFTP. | this PR | 2026-09-14 |
| A2 | Web production build | PROVEN | `cd apps/web && npm run build` | Optional CI job `web-build` | `5525b26` | 2026-09-14 |
| A3 | GitHub Actions CI on `main` / PRs | PROVEN | `.github/workflows/ci.yml` | pytest DEMO=1 `-m "not live and not bench"`; optional npm build. **No live cloud. No heavy bench.** | this PR | 2026-09-14 |
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

CI never sets `RUN_LIVE_WEDGE`. Green Actions ≠ LIVE_CLOUD PROVEN.

---

## D. Architecture facts (code, not a passing test)

| ID | Claim | Status | Evidence | SHA | Date |
|----|-------|--------|----------|-----|------|
| D1 | Runner DAG still sequential **inside** a worker | PROVEN | `PipelineRunner.run` topological loop | `1b82aa5` | 2026-09-14 |
| D2–D4 | ArtifactHandle / RowBatch / CSV chunking | PROVEN | Phase B/C | `dce51a6` | 2026-09-14 |
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

## J. Phase I — LOCAL/DEMO wedge correctness + scale evidence (**this PR**)

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
| J0 | Bench harness + pytest markers | PROVEN **LOCAL/DEMO** | `tests/bench/`, `pytest` marker `bench`, `make bench` / `RUN_BENCH=1` | Heavy scales skipped unless `RUN_BENCH=1`; CI excludes `-m bench` | this PR | 2026-09-14 |
| J1 | Always-on correctness (small N) | PROVEN **LOCAL/DEMO** | `pytest tests/bench -m "not bench"` | plan math + 200-row + file→file reconcile | this PR | 2026-09-14 |
| J2 | Scale 10K full wedge | PROVEN **LOCAL/DEMO** | `RUN_BENCH=1 … local_wedge_bench.py --scales 10000` | See table below | this PR | 2026-09-14 |
| J3 | Scale 100K full wedge | PROVEN **LOCAL/DEMO** | `--scales 100000` | See table below | this PR | 2026-09-14 |
| J4 | Scale 1M full wedge | PROVEN **LOCAL/DEMO** | `--scales 1000000` | See table below | this PR | 2026-09-14 |
| J5 | Scale 10M optional | UNPROVEN / skipped | `BENCH_INCLUDE_10M=1 make bench-10m` | Not run (memory/timeboxed; ~1.4 GiB RSS at 1M suggests 10M may OOM on this host) | — | — |

### LOCAL/DEMO scale numbers (agent host, 2026-09-14)

Command:

```bash
RUN_BENCH=1 FORMULAETL_DEMO=1 python3 scripts/local_wedge_bench.py \
  --require-run-bench --scales 10000,100000,1000000 \
  --source s3 --dest snowflake \
  --out data/out/bench/local_wedge_results.json
```

| Scale | elapsed_s | peak_rss_mb | rows/sec | N | R | D | L | N=R+D+L |
|------:|----------:|------------:|---------:|--:|--:|--:|--:|:-------:|
| 10 000 | 0.296 | 62 | 33 759 | 10 000 | 100 | 198 | 9 702 | ✓ |
| 100 000 | 2.267 | 199 | 44 111 | 100 000 | 1 000 | 1 980 | 97 020 | ✓ |
| 1 000 000 | 23.298 | 1 432 | 42 921 | 1 000 000 | 10 000 | 19 800 | 970 200 | ✓ |

Fixture encrypt/prep time is **excluded** from `elapsed_s` (pipeline wall only). Peak RSS via `resource.getrusage` (Linux KB→MiB). Host: Linux cloud agent, ~15 GiB RAM, Python 3.12.3.

**Honesty:** these numbers are **LOCAL/DEMO** (mock S3 under `data/s3`, demo Snowflake CSV under `data/out`). They do **not** prove live AWS/SFTP/Snowflake throughput.

### How to re-run

```bash
make bench          # 10K + 100K + 1M → data/out/bench/local_wedge_results.json
make bench-pytest   # same scales via pytest -m bench
# optional:
BENCH_INCLUDE_10M=1 make bench-10m
```

---

## Notes

- Phase I adds LOCAL/DEMO wedge scale evidence; live connector E2E (section C / H) remains **UNPROVEN** until partner credentials exist.
- Readiness: validate + CI move **trust/ops** toward design-partner; live connectors stay DEMO until external evidence.
- See `docs/design-partner/` for operational pack.
- Pytest **count** this PR (default markers): **162 passed**, 1 skipped, 6 deselected (`live` + `bench`).
