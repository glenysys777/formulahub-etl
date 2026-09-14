# Production readiness (Customer #1 bar)

**Audited main tip:** `b162987c3667525fcffa75135bbab54e391855f5`  
**Date:** 2026-09-14  
**Scope:** code inspection of `packages/runner`, `packages/api`, `apps/web`, `demos/`, `tests/`. README and sales copy were **not** treated as evidence.

**This document is Phase A** (code inspection at `b162987`, merged as PR #4). Phase B (batch/stream abstraction) landed later in-process — see `docs/PRODUCTION_EVIDENCE.md` section E. No Spark/K8s/billing in either phase.

---

## Levels (use these words only)

| Level | Meaning |
|-------|---------|
| **DEMO** | Works with `FORMULAETL_DEMO=1` (default), local fixtures, mock buckets, sidecar JSON/CSV. Not a customer production path. |
| **ALPHA** | Real libraries / APIs exist in code; CI does **not** prove live systems; small in-memory datasets only. |
| **DESIGN PARTNER** | Could be tried with one customer if secrets, monitoring, and a private worker exist. **We are not here** for warehouse/stream connectors. |
| **PRODUCTION** | Auth, durable runs, bounded memory or chunked I/O, retries, locking that scales, SLOs, live E2E evidence. **Not this repo today.** |
| **ENTERPRISE** | HA scheduler, SSO/RBAC, secrets vault, multi-tenant control plane, private data-plane workers, audit. **Not this repo today.** |

**Rule:** Demo fixtures, local CSV sidecars, and Jobs-API-shaped JSON files are **DEMO**. They are not production Snowflake, Kafka, S3, or Databricks.

**Overall product today: DEMO** (designer + in-process toy runner). A few transforms and local file I/O are **ALPHA** for laptop-sized jobs. Nothing is **PRODUCTION**.

---

## How the runtime actually works (from code)

### Data path — `list[dict]` **and** giant `bytes`

`PipelineRunner` (`packages/runner/formulaetl/engine/runner.py`) walks a DAG in **topological order, one node at a time**, in a single Python process.

- **Row path:** every transform/sink receives `input_rows: list[dict[str, Any]]`. Results are `ComponentResult.rows` (and optional `rejects` / named `streams`). The **entire working set is in RAM**. There is no Arrow, no chunk iterator, no spill-to-disk, no checkpoint.
- **Binary path:** S3 / SFTP / local file / PGP put the **full object** in `artifacts["bytes"]` and `ctx.variables["upstream_bytes"]`. The runner copies those bytes into the next component’s `config`. Decrypt + CSV parse then materializes **all rows** as dicts.
- Independent branches are **not** parallel. Metrics `rows_in`/`rows_out` are **summed across nodes**, so they are not a pipeline-level distinct row count.
- Default `FORMULAETL_DEMO=1` (`PipelineRunner.__init__` and API `DEMO_MODE`).

This is a **demo / laptop DAG**, not a data plane.

### Scheduler

`PipelineScheduler` (`packages/api/formulaetl_api/scheduler.py`):

- 5-field cron parser (not crontab, not APScheduler, not Airflow).
- File JSON under `data/schedules/` (`ScheduleStore`).
- **In-process daemon thread**, default poll 5s (`FORMULAETL_SCHEDULER_POLL`).
- `tick()` fires `run_callback` **synchronously** under `_fire_lock`.
- Comment in source: cloud HA scheduling is Enterprise later — **correct; not implemented**.

Single API process. Restart can miss or double-fire around minute boundaries. No distributed lock, no queue, no misfire policy.

### Run store and API locking

`RunStore` (`packages/api/formulaetl_api/store.py`): **in-memory `dict[str, RunResult]`**. Process restart **wipes run history**. Pipelines persist as JSON files (`PipelineStore`).

`packages/api/formulaetl_api/__init__.py`:

- Global `_runner_lock` — **one pipeline run at a time** per process.
- `POST /api/pipelines/{id}/run` **blocks** until the DAG finishes (not async worker).
- CORS `allow_origins=["*"]`, **no authentication**, no API keys.
- Scheduler callback uses the same lock and the same in-memory run store.

### Secrets in pipeline JSON

Yes. Node `config` is stored verbatim in `data/pipelines/*.json` and bundled demos.

- UI marks `password` / `token` / `passphrase` as `type: secret` (masked input only).
- Values are still JSON on disk and returned by `GET /api/pipelines/{id}`.
- No `${ENV}` interpolation, no vault, no secret refs.
- Demo PGP node includes `"passphrase": ""` and a **path to a demo private key** in-repo (`fixtures/keys/`).
- Live SFTP/Postgres/Snowflake/Databricks would put passwords/PATs in the same JSON.

Unauthenticated API + secrets-in-JSON is a **hard production blocker**.

---

## Connector honesty (DEMO vs live)

Default tests and `make demo*` set `FORMULAETL_DEMO=1`. Live branches exist in several files; **CI never talks to real AWS/SFTP/Kafka/Snowflake/Databricks/Postgres.**

| Connector | Demo path (what CI actually runs) | Live path in code | Proven live? |
|-----------|-----------------------------------|-------------------|--------------|
| **S3** | Read `data/s3/<bucket>/<key>`; optional paginated demo list | `boto3` `download_file` to temp + retries/timeouts; paginated `list_objects_v2` | **No** |
| **SFTP** | Copy `fixtures/sample/*` via `shutil` | `paramiko` stream `get`; timeouts/retries; **RejectPolicy** host keys by default; password and/or key | **No** |
| **PGP** | Real `pgpy` on demo keys / encrypted fixture; path/temp artifact | Same; `private_key_ref` / `passphrase_ref`; large outputs path-only | Crypto is real; **ops/secrets not production** |
| **CSV** | Chunked `iter_csv_batches` / DictReader; malformed policy | Same | **ALPHA** for laptop-sized jobs; adapter still materializes rows for sinks |
| **Snowflake** | Write CSV + `.load.json` under `data/out/snowflake` | Optional `snowflake-connector-python` `INSERT … executemany` (not COPY). Falls back to demo if `account` missing | **No** |
| **Postgres** | SQLite / CSV fixture / inline 3 rows | `psycopg` when `FORMULAETL_DEMO=0` + real host/DSN | **No** |
| **MySQL** | Same demo fallbacks | `pymysql` extra (not a default install extra) | **No** |
| **Kafka** | Read `fixtures/sample/kafka_orders.jsonl` | Batch consume `max_messages` then stop (`confluent-kafka` or `kafka-python`). **Not a streaming runtime** | **No** |
| **Databricks** | Jobs-API-**shaped** sidecar JSON | `POST /api/2.1/jobs/run-now` + poll. **Orchestration only — not Spark** | **No** |
| **HTTP API** | Fixture when URL contains `example.com` and demo mode | `httpx` JSON GET/POST | Fixture proven; live **unproven in CI** |

Snowflake destination SQL interpolates table/column names. Live insert is not warehouse-grade (no COPY, merge, schema evolution, or retries).

---

## Field Mapper / Lookup Join / AI builder

**Field Mapper** (`tmap` in `tmap.py` + `apps/web/src/SchemaMapper.tsx`):

- Real row-wise AST evaluator (`upper`, `col()`, arithmetic, Variables middle layer).
- UI: Input · Variables · Output.
- Still **one Python list of dicts**. Expression failures become `null` + a log line, not a typed contract.
- **Not** a multi-input Talend tMap; joins are a separate node.

**Lookup Join** (`lookup_join.py`):

- In-memory hash join: `left` / `inner` / `right` / `full`, `match=all|first`.
- Right side from `targetHandle=right` or `lookup_path` CSV/JSON.
- Fine for thousands of rows; unbounded RAM for millions.

**AI builder** (`ai_builder.py`):

- Offline **keyword heuristic** builds a demo DAG (`demo: true`, `host: demo`, fixture paths).
- Optional OpenAI/Anthropic if env keys exist; JSON parsed with **no allowlist enforcement beyond pydantic**.
- Schema discover then rewrites mappings — useful for demos.
- `POST /api/ai/build` **saves immediately** with no auth.
- **DEMO**, not a production pipeline architect.

---

## Tests / build / CI (this repo)

- Tests: `make test` → `python3 -m pytest tests` with `FORMULAETL_DEMO=1` (see `tests/conftest.py`).
- Web: `cd apps/web && npm run build`.
- **No `.github/workflows`.** There is no GitHub Actions gate on `main`.
- This audit run (2026-09-14): **pytest 87 passed**; **`npm run build` succeeded**. Details: `docs/PRODUCTION_EVIDENCE.md`.

---

## Capability matrix

| FEATURE | CURRENT LEVEL | TARGET (Customer #1) | PRODUCTION READY? | DEMO ONLY? | RISK | NEXT ACTION (Phase B — do not do in this PR) |
|---------|---------------|----------------------|-------------------|------------|------|-----------------------------------------------|
| Sequential DAG runner (`list[dict]` + full-object `bytes`) | DEMO | PRODUCTION (chunked/spill or worker data plane) | No | Default path yes | OOM; no restart; summed metrics lie | Design bounded batches; **do not claim Spark** |
| Parallel / streaming runtime | DEMO (absent) | PRODUCTION | No | N/A | Kafka “source” is a finite pull | Separate stream design later; not this PR |
| Pipeline JSON on disk | ALPHA | PRODUCTION (versioned, validated) | No | Demos yes | No migrations, no RBAC | Keep JSON; add schema + secret stripping |
| Run store | DEMO | PRODUCTION | No | Yes | History gone on restart | Persist runs (SQLite/Postgres) |
| API run locking | DEMO | DESIGN PARTNER | No | Yes | Global lock; sync HTTP | Per-pipeline lock + async jobs |
| HTTP API (FastAPI) | DEMO | DESIGN PARTNER | No | Hosted UI without API | CORS `*`; no auth | Authn first |
| Visual designer (Vite) | ALPHA | PRODUCTION UI | No (runtime not behind it) | UI can be static | Vercel ≠ ETL runtime | Keep UI; document API requirement |
| Community cron scheduler | DEMO | DESIGN PARTNER (single node) | No | Yes | In-process poll; no HA | External cron or queue; not K8s operator yet |
| Local file / Excel / CSV parse | ALPHA (CSV chunked + policy) | PRODUCTION (size limits) | No | Fixtures | Excel/JSON still whole-file; CSV adapter materializes | Keep chunking; spill later |
| Schema validate / transform / filter / sort / aggregate / dedupe | ALPHA | PRODUCTION | No | Sample data | In-memory algorithms | Same data-plane limits |
| Field Mapper (variables + exprs) | ALPHA | DESIGN PARTNER | No | Demo pipelines | AST subset; silent nulls | Typed errors; tests on customer schemas |
| Lookup Join | ALPHA | DESIGN PARTNER | No | File lookup demo | Nested-loop RAM | Spill / size guard |
| Python Row sandbox | DEMO | DESIGN PARTNER | No | Yes | `exec` + regex denylist ≠ sandbox | Don’t run untrusted code in prod |
| S3 source | DEMO CI / ALPHA code (stream + paginated list) | PRODUCTION | No | Default yes | Live path untested in CI | Design-partner live GET + IAM |
| SFTP source/dest | DEMO CI / ALPHA code (timeouts, host-key reject) | DESIGN PARTNER | No | Default yes | Live paramiko untested; password in JSON | Partner SFTP with env secrets |
| PGP encrypt/decrypt | ALPHA (library + path/temp/refs) / DEMO (keys) | PRODUCTION | No | Demo keys in git | Private key path still common in demos | External KMS/agent; prefer refs |
| Snowflake destination | DEMO | PRODUCTION | No | Yes unless live extra + account | CSV sidecar ≠ warehouse; live INSERT weak | Partner COPY INTO evidence |
| Postgres source/dest | DEMO | DESIGN PARTNER | No | Default yes | Live psycopg untested; SQL as config | Partner DSN via env; parameterized DDL |
| MySQL source/dest | DEMO | ALPHA | No | Yes | pymysql optional; same demo fallbacks | Do not expand; freeze |
| HTTP API source | DEMO / ALPHA | DESIGN PARTNER | No | `example.com` fixture | Bearer token in JSON | Secrets + retries/pagination |
| Kafka source | DEMO | DESIGN PARTNER (batch pull only) | No | Default yes | Not a consumer group streaming product | Honest batch ingest; live proof later |
| Databricks Job trigger | DEMO | DESIGN PARTNER (orchestration) | No | Default yes | Sidecar SUCCESS ≠ cluster job | Live Jobs API with partner token |
| AI pipeline builder | DEMO | ALPHA | No | Heuristic graphs | LLM can emit garbage types; auto-save | Keep offline heuristic; don’t sell as prod |
| Schema discover | ALPHA | DESIGN PARTNER | No | Demo files | Same demo/live split as sources | Cache schemas; no live in CI |
| Secrets / vault | DEMO (none) | PRODUCTION | No | N/A | Secrets in JSON + public GET | Env/vault refs; redact API |
| Auth / SSO / RBAC | DEMO (none) | ENTERPRISE / PRODUCTION | No | N/A | Open API | Token auth before any customer data |
| Multi-instance HA | DEMO (absent) | ENTERPRISE | No | Single process | Duplicate scheduled runs | Control plane vs workers (see architecture note) |
| Observability / lineage | DEMO (in-memory logs) | PRODUCTION | No | Logs in RunResult | No retention | Structured logs + persist |
| Hosted production runtime | DEMO | PRODUCTION | No | Vercel UI only | README “K8s” is roadmap, not code | Docker API with DEMO=0 only after auth |
| CI/CD gate | DEMO (no GHA) | PRODUCTION | No | Local pytest | `main` can break unnoticed | Add pytest + `npm run build` on PR |
| Billing / marketplace / Talend importer / Spark / K8s operator | Absent (correct) | — | — | — | Feature expansion vs trust | **Do not build** (mission freeze) |

---

## Bottlenecks for Phase B (review this list; do not implement here)

1. **Memory data path** — `list[dict]` + whole-file `bytes` cannot be Customer #1 production.
2. **No auth, secrets in pipeline JSON, CORS \*** — cannot put real credentials on this API.
3. **In-memory run history + global sync lock** — not an execution service.
4. **In-process cron** — not a scheduler product.
5. **Warehouse/stream connectors are fixtures** — Snowflake/Kafka/Databricks/S3/SFTP/Postgres live paths are **unproven**.
6. **No CI on GitHub** — production trust starts with a gate that matches `make test` + `npm run build`.
7. **Control plane vs data plane are the same process** — see `docs/architecture/CONTROL_DATA_PLANE.md` (north star only).

---

## What we will not claim

- “Production Snowflake / Kafka / Databricks / S3” based on demo sidecars.
- “Streaming ETL” (Kafka source stops after `max_messages`).
- “Spark engine” (Databricks node triggers a job API).
- “Deploy on Kubernetes” as a shipped operator (Docker Compose exists; no k8s manifests in this audit).
- “Enterprise scheduler / SSO / secrets.”
