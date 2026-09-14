# Production evidence log

Claims in sales/README are **not** evidence. Each row is a statement we are willing to make only with a command, git SHA, and date.

**Audit SHA (main at start of this work):** `b162987c3667525fcffa75135bbab54e391855f5`  
**This docs PR branch tip:** fill after evidence commit (see git log on `cursor/production-readiness-audit-71a1`)  
**Agent run date:** 2026-09-14  
**Python:** 3.12.3 · **Node:** 22.14.0 · **pytest:** 9.1.1

Fill status: `PROVEN` | `UNPROVEN` | `FAILED` | `EMPTY`

---

## A. Build and tests (this agent run)

| ID | Claim | Status | Command | Result | SHA | Date |
|----|-------|--------|---------|--------|-----|------|
| A1 | Pytest suite on `tests/` | PROVEN | `python3 scripts/seed_demo.py && python3 -m pytest tests -v --tb=short` | **87 passed**, 163 warnings (pgpy deprecations), 9.18s. `FORMULAETL_DEMO=1` via conftest. Not live AWS/Kafka/Snowflake. | `b162987` code + this PR docs | 2026-09-14 |
| A2 | Web production build | PROVEN | `cd apps/web && npm run build` | **success** — `tsc -b && vite build`; vite 8.3.0; `dist/assets/index-BNQ76Tv6.js` 453.64 kB | this PR | 2026-09-14 |
| A3 | GitHub Actions CI on `main` | PROVEN **absent** | `ls .github/workflows` | No workflow files in repo at `b162987` | `b162987` | 2026-09-14 |
| A4 | Default env is demo | PROVEN | Read `tests/conftest.py`, `Makefile` `FORMULAETL_DEMO ?= 1` | Tests force `FORMULAETL_DEMO=1` | `b162987` | 2026-09-14 |

---

## B. Demo runs (fixtures, not customer systems)

| ID | Claim | Status | Command | Result | SHA | Date |
|----|-------|--------|---------|--------|-----|------|
| B1 | Flagship S3→PGP→Snowflake **demo** CLI | PROVEN **demo only** | `FORMULAETL_DEMO=1 python3 -m formulaetl.cli run demos/s3-pgp-snowflake/pipeline.json` | `status=success`; S3Source **[demo]** 1073 bytes; PGPDecrypt real pgpy; CSV 13 rows; SnowflakeDestination **[demo]** CSV under `data/out/snowflake/`; archive moved mock object. Metrics `rows_in=49` are **summed node counts**, not 13 source rows. | this run | 2026-09-14 |
| B2 | Kafka→Databricks **demo** CLI | PROVEN **demo only** | `FORMULAETL_DEMO=1 python3 -m formulaetl.cli run demos/api-kafka-databricks/pipeline.json` | `status=success`; KafkaSource **[demo]** 8 msgs from `kafka_orders.jsonl`; DatabricksJob **[demo]** sidecar `result_state=SUCCESS`. Not a broker or workspace. | this run | 2026-09-14 |
| B3 | Lookup Join + Field Mapper demo | PROVEN **demo only** | `FORMULAETL_DEMO=1 python3 -m formulaetl.cli run demos/lookup-join-mapper/pipeline.json` | `status=success`; left join 13×12→13; Field Mapper logged `variable failed for total=... 'abc'` then kept 13/13 (silent null). | this run | 2026-09-14 |
| B4 | Historical founder screenshots / sidecar JSON | PROVEN as **demo artifacts only** | `docs/artifacts/EVIDENCE.md` | Documents fixture Kafka/Databricks UI; not live clusters | `b162987` | 2026-09-14 |

---

## C. Live systems (customer-shaped)

| ID | Claim | Status | Command | Result | SHA | Date |
|----|-------|--------|---------|--------|-----|------|
| C1 | Live AWS S3 `get_object` E2E | UNPROVEN | `FORMULAETL_DEMO=0` + real bucket | Not run (no credentials in this environment) | `b162987` | 2026-09-14 |
| C2 | Live SFTP paramiko E2E | UNPROVEN | `FORMULAETL_DEMO=0` + real host | Not run | `b162987` | 2026-09-14 |
| C3 | Live Postgres psycopg E2E | UNPROVEN | `FORMULAETL_DEMO=0` + DSN | Not run | `b162987` | 2026-09-14 |
| C4 | Live Snowflake COPY/INSERT E2E | UNPROVEN | extra `formulaetl[snowflake]` + account | Not run | `b162987` | 2026-09-14 |
| C5 | Live Kafka consumer E2E | UNPROVEN | `formulaetl[kafka]` + brokers | Not run | `b162987` | 2026-09-14 |
| C6 | Live Databricks Jobs API E2E | UNPROVEN | workspace host + PAT | Not run | `b162987` | 2026-09-14 |

Do **not** promote C-rows to PROVEN from demo sidecars or `docs/artifacts/screenshots/*.json`.

---

## D. Architecture facts (code, not a passing test)

| ID | Claim | Status | Evidence | SHA | Date |
|----|-------|--------|----------|-----|------|
| D1 | Runner passes `list[dict]` between nodes | PROVEN | `packages/runner/formulaetl/engine/runner.py` `input_rows: list[dict[str, Any]]` | `b162987` | 2026-09-14 |
| D2 | Binary connectors pass full `bytes` in artifacts | PROVEN | `source_s3.py`, `sftp_source.py`, `pgp_decrypt.py`; runner copies `bytes` into next config | `b162987` | 2026-09-14 |
| D3 | RunStore is process memory | PROVEN | `RunStore._runs: dict[str, RunResult]` | `b162987` | 2026-09-14 |
| D4 | API serializes runs with one global `threading.Lock` | PROVEN | `_runner_lock` in `formulaetl_api/__init__.py` | `b162987` | 2026-09-14 |
| D5 | Scheduler is an in-process poll thread | PROVEN | `PipelineScheduler._loop` daemon thread | `b162987` | 2026-09-14 |
| D6 | No API authentication | PROVEN | FastAPI routes have no Depends/auth | `b162987` | 2026-09-14 |
| D7 | Secrets live in node `config` JSON | PROVEN | `PipelineStore.save` dumps full model; demos include `passphrase` | `b162987` | 2026-09-14 |
| D8 | Kafka live path is a bounded batch pull | PROVEN | `max_messages` loop then close consumer | `b162987` | 2026-09-14 |
| D9 | Databricks component is Jobs API orchestration | PROVEN | `databricks_job.py` docstring + `jobs/run-now` | `b162987` | 2026-09-14 |
| D10 | Snowflake default path writes local CSV | PROVEN | `SnowflakeDestination` `use_demo` CSV writer | `b162987` | 2026-09-14 |

---

## Notes

- Pytest **count** is only valid for the command output attached to A1 on this date. This run: **87 passed** (prior `docs/artifacts/EVIDENCE.md` said 84 — stale).
- C-rows remain UNPROVEN. Empty cells stay EMPTY until stdout is pasted.
