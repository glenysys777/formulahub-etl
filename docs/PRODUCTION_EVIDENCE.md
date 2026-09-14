# Production evidence log

Claims in sales/README are **not** evidence. Each row is a statement we are willing to make only with a command, git SHA, and date.

**Audit SHA (main at start of this work):** `b162987c3667525fcffa75135bbab54e391855f5`  
**This docs PR SHA:** _fill after commit_  
**Date:** 2026-09-14

Fill status: `PROVEN` | `UNPROVEN` | `FAILED` | `EMPTY`

---

## A. Build and tests (this agent run)

| ID | Claim | Status | Command | Result | SHA | Date |
|----|-------|--------|---------|--------|-----|------|
| A1 | Pytest suite on `tests/` | EMPTY | `python3 -m pytest tests -v --tb=short` (after seed) | _pending this run_ | | 2026-09-14 |
| A2 | Web production build | EMPTY | `cd apps/web && npm run build` | _pending this run_ | | 2026-09-14 |
| A3 | GitHub Actions CI on `main` | PROVEN **absent** | `ls .github/workflows` | No workflow files in repo at `b162987` | `b162987` | 2026-09-14 |
| A4 | Default env is demo | PROVEN | Read `tests/conftest.py`, `Makefile` `FORMULAETL_DEMO ?= 1` | Tests force `FORMULAETL_DEMO=1` | `b162987` | 2026-09-14 |

---

## B. Demo runs (fixtures, not customer systems)

| ID | Claim | Status | Command | Result | SHA | Date |
|----|-------|--------|---------|--------|-----|------|
| B1 | Flagship S3→PGP→Snowflake **demo** CLI | EMPTY | `FORMULAETL_DEMO=1 python3 -m formulaetl.cli run demos/s3-pgp-snowflake/pipeline.json` | _pending this run_ | | 2026-09-14 |
| B2 | Kafka→Databricks **demo** CLI | EMPTY | `FORMULAETL_DEMO=1 python3 -m formulaetl.cli run demos/api-kafka-databricks/pipeline.json` | _pending this run_ | | 2026-09-14 |
| B3 | Lookup Join + Field Mapper demo | EMPTY | `FORMULAETL_DEMO=1 python3 -m formulaetl.cli run demos/lookup-join-mapper/pipeline.json` | _pending this run_ | | 2026-09-14 |
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

- Pytest **count** is only valid for the command output attached to A1 on the stated SHA.
- `docs/artifacts/EVIDENCE.md` previously cited “84 passed”; treat that as historical unless A1 matches.
- Empty cells must stay EMPTY until a human or agent pastes stdout.
