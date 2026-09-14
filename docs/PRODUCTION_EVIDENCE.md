# Production evidence log

Claims in sales/README are **not** evidence. Each row is a statement we are willing to make only with a command, git SHA, and date.

**Audit SHA (main / Phase A merge):** `cecb1af` (PR #4)  
**Phase B merge tip:** `f2d8b57`  
**Phase C merge tip:** `dce51a6`  
**Phase D+E branch tip:** `62c0c05` (impl `5d719a7`)  
**Agent run date:** 2026-09-14  
**Python:** 3.12.3 · **Node:** 22.14.0 · **pytest:** 9.1.1

Fill status: `PROVEN` | `UNPROVEN` | `FAILED` | `EMPTY`

---

## A. Build and tests

| ID | Claim | Status | Command | Result | SHA | Date |
|----|-------|--------|---------|--------|-----|------|
| A1 | Pytest suite on `tests/` | PROVEN | `python3 scripts/seed_demo.py && python3 -m pytest tests -q` | **133 passed**, 1 skipped (`RUN_CSV_1M`), warnings (pgpy). Includes Phase D+E async/durable tests. `FORMULAETL_DEMO=1` via conftest. Not live AWS/SFTP. | this PR | 2026-09-14 |
| A2 | Web production build | PROVEN **poll UI only** | `npm run build` in `apps/web` | Poll loop accepts `queued`; no layout redesign | this PR | 2026-09-14 |
| A3 | GitHub Actions CI on `main` | PROVEN **absent** | `ls .github/workflows` | Still no workflow files | `cecb1af` | 2026-09-14 |
| A4 | Default env is demo | PROVEN | Read `tests/conftest.py` | Tests force `FORMULAETL_DEMO=1` | `cecb1af` | 2026-09-14 |
| A5 | CSV 10K streaming benchmark | PROVEN | Phase C | Unchanged | `dce51a6` | 2026-09-14 |

---

## B. Demo runs (fixtures, not customer systems)

| ID | Claim | Status | Command | Result | SHA | Date |
|----|-------|--------|---------|--------|-----|------|
| B1 | Flagship S3→PGP→Snowflake **demo** CLI | PROVEN **demo only** | `FORMULAETL_DEMO=1 python3 -m formulaetl.cli run demos/s3-pgp-snowflake/pipeline.json` | CLI still sync in-process; API path is async+SQLite | this PR | 2026-09-14 |
| B2–B4 | Other demos / screenshots | PROVEN **demo only** | pytest / CLI | Unchanged intent | `dce51a6` | 2026-09-14 |

---

## C. Live systems (customer-shaped)

Unchanged — all **UNPROVEN**.

---

## D. Architecture facts (code, not a passing test)

| ID | Claim | Status | Evidence | SHA | Date |
|----|-------|--------|----------|-----|------|
| D1 | Runner DAG still sequential **inside** a worker | PROVEN | `PipelineRunner.run` topological loop; workers claim jobs concurrently across runs | this PR | 2026-09-14 |
| D2–D4 | ArtifactHandle / RowBatch / CSV chunking | PROVEN | Phase B/C | `dce51a6` | 2026-09-14 |
| D5 | Run history is durable SQLite (not process memory) | PROVEN | `formulaetl_api.db` + `RunStore`; `/health` → `run_store: sqlite` | this PR | 2026-09-14 |
| D6 | No API authentication | PROVEN | unchanged | `cecb1af` | 2026-09-14 |
| D7 | Secrets may still live in node `config` JSON | PROVEN | unchanged | Phase C | 2026-09-14 |
| D8–D9 | SFTP host-key reject / S3 pagination | PROVEN | Phase C | `dce51a6` | 2026-09-14 |
| D10 | `POST /api/pipelines/{id}/run` returns **202** + `status=queued` | PROVEN | API + `test_async_durable.py` | this PR | 2026-09-14 |
| D11 | Global `_runner_lock` removed; concurrent claimed runs allowed | PROVEN | worker `max_concurrent`; concurrent smoke test | this PR | 2026-09-14 |
| D12 | Runs pin immutable `pipeline_version_id` | PROVEN | versions table + pin test | this PR | 2026-09-14 |

---

## E. Phase B — what landed (historical)

| ID | Claim | Status | Evidence |
|----|-------|--------|----------|
| E1–E5 | RowBatch / DatasetHandle / ArtifactHandle + planner feeds | PROVEN | Phase B PR #5 / `f2d8b57` |

---

## F. Phase C — bounded I/O (historical)

See main at `dce51a6`. CSV/PGP/S3/SFTP hardening unchanged in D+E.

---

## G. Phase D+E — async control plane + durable history (this PR)

| ID | Claim | Status | Evidence |
|----|-------|--------|----------|
| G1 | Job queue accepts run; HTTP returns before DAG finishes | PROVEN | `POST …/run` → 202 `queued`; `tests/api/test_async_durable.py` |
| G2 | Worker claims + completes independently of request thread | PROVEN | `formulaetl_api.worker.RunWorker`; embedded by default; `make worker` for split process |
| G3 | State transitions persisted (`queued`→`running`→`success`/`failed`) | PROVEN | `run_events` table; GET `/api/runs/{id}` includes `events` |
| G4 | Node execution records persisted | PROVEN | `node_runs` (node_id, component_type, status, times, rows_*, error, duration_ms) |
| G5 | Restart: pipelines, versions, runs, schedules survive | PROVEN | `test_restart_persistence` |
| G6 | Version pin: edit does not rewrite yesterday’s run snapshot | PROVEN | `test_version_pin_survives_edit` |
| G7 | Concurrent runs smoke (no global lock) | PROVEN | `test_concurrent_runs_smoke` |
| G8 | Schema ready for Postgres later | PROVEN **shape only** | Portable SQL types in `db.py`; **no** Postgres runtime in this PR |

### API change (documented)

| Before | After |
|--------|-------|
| `POST /run` → **200** + terminal `status` (sync under global lock) | `POST /run` → **202** + `status=queued` + `pipeline_version_id` |
| Body fields `run_id`, `status` | Same fields kept; added `pipeline_version_id` |
| Status strings lowercase | Still lowercase: `queued`, `running`, `success`, `failed`, `cancelled`, `retrying`, `timed_out` (map to QUEUED/RUNNING/…) |
| `GET /runs/{id}` memory-only | SQLite; adds `pipeline_version_id`, `node_runs`, `events` |
| `/health` `run_store: memory` | `run_store: sqlite`; `readiness_level: ALPHA` |

### Remaining gaps (honest)

- Still **no auth**, no secrets vault, no live E2E in CI.
- Worker may be **embedded** in the API process (Community default); split process is optional (`FORMULAETL_EMBEDDED_WORKER=0` + `make worker`).
- Runner **inside** a job remains sequential; destinations may still materialize `list[dict]`.
- Not Spark, not K8s, not billing, no new connectors.
- Scheduler remains in-process cron poll (now **enqueues** instead of blocking).

---

## Notes

- Readiness: durable runs + async accept move control-plane bookkeeping to **ALPHA**; overall product for Customer #1 live connectors remains **DEMO** until auth + live proofs.
- Pytest **count** for Phase D+E: **133 passed**, 1 skipped (Phase C was 127; Phase B was 99; Phase A was 87).
- CLI `formulaetl run` is still synchronous (no queue) — intentional for local demos.
