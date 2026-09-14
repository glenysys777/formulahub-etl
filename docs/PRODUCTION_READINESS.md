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

**Overall product today: DEMO** (designer + fixture connectors). Control-plane bookkeeping (async runs, SQLite history, versions, **pipeline validate**) is **ALPHA**. Connections + local SecretProvider + optional API key are **ALPHA** (Community / design-partner path — not enterprise vault). CI gate (pytest + DEMO=1, optional web build) is **ALPHA**. A few transforms and local file I/O are **ALPHA** for laptop-sized jobs. Nothing is **PRODUCTION**. Live connectors remain **DEMO** until design-partner proofs (manual — not CI).

---

## How the runtime actually works (from code)

### Data path — bounded batches + optional spill (still one process)

`PipelineRunner` (`packages/runner/formulaetl/engine/runner.py`) walks a DAG in **topological order, one node at a time**, in a single Python process.

- **Row path:** the planner feeds row-wise nodes bounded `RowBatch`es. Large hops use a **lazy producer chain**; streaming sinks (`consume_dataset`) pull one pass. `ComponentResult.rows` is a small/debug adapter — above `FORMULAETL_SPILL_THRESHOLD` it stays empty. Rejects fan-out can spill JSONL. **Not Spark.** There is no Arrow runtime and no checkpoint/restart.
- **Binary path:** S3 / SFTP / local file / PGP prefer **on-disk `ArtifactHandle`**. Large PGP decrypt uses `gpg` file-to-file when present (pgpy fallback for small fixtures). The runner does **not** inject whole-object `bytes` into the next node when a path exists.
- Independent branches are **not** parallel. Metrics `rows_in`/`rows_out` are **summed across nodes**, so they are not a pipeline-level distinct row count.
- Default `FORMULAETL_DEMO=1` (`PipelineRunner.__init__` and API `DEMO_MODE`).

This is a **laptop/demo DAG with bounded batches**, not a distributed data plane. See `docs/PERFORMANCE.md`.

### Scheduler

`PipelineScheduler` (`packages/api/formulaetl_api/scheduler.py`):

- 5-field cron parser (not crontab, not APScheduler, not Airflow).
- Schedules in SQLite (`schedules` table; legacy JSON migrated on boot).
- **In-process daemon thread**, default poll 5s (`FORMULAETL_SCHEDULER_POLL`).
- `tick()` **enqueues** a run via callback (does not block on `PipelineRunner`).
- Comment in source: cloud HA scheduling is Enterprise later — **correct; not implemented**.

Single API process by default (embedded worker). Restart no longer wipes run history (SQLite). No distributed lock / misfire policy.

### Run store and API locking

`RunStore` (`packages/api/formulaetl_api/store.py`): **SQLite** durable ledger (`runs`, `node_runs`, `run_events`, `job_queue`). Pipeline definitions + immutable `pipeline_versions` in the same DB (`data/formulaetl.db` by default).

`packages/api/formulaetl_api/__init__.py`:

- **No** global `_runner_lock` — concurrent claimed jobs may run in parallel.
- `POST /api/pipelines/{id}/run` returns **202** with `status=queued` + `pipeline_version_id`; worker executes async.
- CORS `allow_origins=["*"]`.
- Optional **`FORMULAETL_API_KEY`**: when set, require `X-API-Key` or `Authorization: Bearer` (Community stays open when unset). `/health` reports `auth: none|api_key`.
- Embedded worker thread by default (`FORMULAETL_EMBEDDED_WORKER=1`); standalone: `make worker`.

### Secrets and Connections (Phase F)

- **Connections** CRUD: `sftp`, `s3`, `snowflake`, `postgres`, `http` — see `docs/CONNECTIONS.md`.
- **SecretProvider**: env refs (`env:NAME`, `${NAME}`) and Fernet-encrypted local SQLite store (`secret:<id>`).
- Nodes may set `connection_id`; runtime merges credentials in memory. Pipeline JSON should hold **refs**, not passwords.
- `GET` responses **mask** secret fields; refs are returned safely.
- Inline demo hosts (`host: "demo"`, empty passwords) still work under `FORMULAETL_DEMO=1` without a connection.
- AI builder strips secret literals; never send decrypted secrets to LLMs.
- **Not** HashiCorp Vault / cloud KMS / SSO — still a design-partner gap for ENTERPRISE.

Unauthenticated Community (no API key) + any leftover inline secrets remain a **partner risk**; set `FORMULAETL_API_KEY` and migrate nodes to `connection_id` before live credentials.

---

## Connector honesty (DEMO vs live)

Default tests and `make demo*` set `FORMULAETL_DEMO=1`. Live branches exist in several files; **CI never talks to real AWS/SFTP/Kafka/Snowflake/Databricks/Postgres.**

| Connector | Demo path (what CI actually runs) | Live path in code | Proven live? |
|-----------|-----------------------------------|-------------------|--------------|
| **S3** | Read `data/s3/<bucket>/<key>`; optional paginated demo list | `boto3` `download_file` to temp + retries/timeouts; paginated `list_objects_v2` | **No** |
| **SFTP** | Copy `fixtures/sample/*` via `shutil` | `paramiko` stream `get`; timeouts/retries; **RejectPolicy** host keys by default; password and/or key | **No** |
| **PGP** | Real `pgpy` on demo keys / encrypted fixture; path/temp artifact | Same; `private_key_ref` / `passphrase_ref`; large outputs path-only | Crypto is real; **ops/secrets not production** |
| **CSV** | Chunked `iter_csv_batches` / DictReader; malformed policy; large files producer-only | Same | **ALPHA** for laptop-sized jobs; sinks stream in DEMO |
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
- **Not** a multi-input visual join mapper; joins are a separate node.

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
- **GitHub Actions:** `.github/workflows/ci.yml` — pytest (DEMO=1) + optional npm build. **No live cloud E2E.**
- Design-partner ops: `docs/design-partner/` (deploy, security, connections link, backup, troubleshooting, checklist).
- Details: `docs/PRODUCTION_EVIDENCE.md`.

---

## Capability matrix

| FEATURE | CURRENT LEVEL | TARGET (Customer #1) | PRODUCTION READY? | DEMO ONLY? | RISK | NEXT ACTION (Phase B — do not do in this PR) |
|---------|---------------|----------------------|-------------------|------------|------|-----------------------------------------------|
| Sequential DAG runner (`list[dict]` + full-object `bytes`) | DEMO | PRODUCTION (chunked/spill or worker data plane) | Partial | Default path yes | OOM on blocking nodes (sort/join/keep-last); no restart | Batches + lazy chain + gpg path are in; **do not claim Spark** |
| Parallel / streaming runtime | DEMO (absent) | PRODUCTION | No | N/A | Kafka “source” is a finite pull | Separate stream design later; not this PR |
| Pipeline JSON on disk | ALPHA | PRODUCTION (versioned, validated) | No | Demos yes | No migrations, no RBAC | Keep JSON; add schema + secret stripping |
| Run store | ALPHA (SQLite) | PRODUCTION | No | Demos yes | Local file DB; no Postgres yet | Optional Postgres later |
| API run locking | ALPHA (async queue; no global lock) | DESIGN PARTNER | No | Yes | Embedded worker default | Split worker + auth |
| Observability / lineage | ALPHA (durable events + node_runs + run summary) | PRODUCTION | No | Logs in SQLite | No retention policy | Structured export |
| HTTP API (FastAPI) | ALPHA (optional API key + validate) | DESIGN PARTNER | No | Hosted UI without API | CORS `*`; open when unset | Keep key on for partners |
| Pipeline validate preflight | ALPHA | DESIGN PARTNER | No | Structural only | Not live connectivity | Partner connection test |
| CI/CD gate | ALPHA (GHA pytest + npm build, DEMO=1) | PRODUCTION | No | No live cloud in CI | Live E2E still manual | Keep honesty; partner checklist |
| Visual designer (Vite) | ALPHA | PRODUCTION UI | No (runtime not behind it) | UI can be static | Vercel ≠ ETL runtime | Keep UI; document API requirement |
| Community cron scheduler | DEMO | DESIGN PARTNER (single node) | No | Yes | In-process poll; no HA | External cron or queue; not K8s operator yet |
| Local file / Excel / CSV parse | ALPHA (CSV producer + streaming sinks) | PRODUCTION (size limits) | No | Fixtures | Excel/JSON still whole-file; sort/join materialize | Keep chunking; gpg+lazy chain for wedge |
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
| Secrets / vault | ALPHA (env + local encrypted + connections) | PRODUCTION | No | Prefer refs | Not enterprise vault; migrate inline | Prefer `connection_id`; see CONNECTIONS.md |
| Auth / SSO / RBAC | ALPHA (optional API key) / ABSENT SSO | ENTERPRISE / PRODUCTION | No | Open when unset | Set key before live data | Token auth before any customer data |
| Multi-instance HA | DEMO (absent) | ENTERPRISE | No | Single process | Duplicate scheduled runs | Control plane vs workers (see architecture note) |
| Hosted production runtime | DEMO | PRODUCTION | No | Vercel UI only | README “K8s” is roadmap, not code | Docker API with DEMO=0 only after auth |
| Billing / marketplace / legacy-ETL importer / Spark / K8s operator | Absent (correct) | — | — | — | Feature expansion vs trust | **Do not build** (mission freeze) |

---

## Bottlenecks for Customer #1 (honest remaining)

1. **Memory data path** — `list[dict]` + whole-file hops still bound laptop-sized jobs.
2. **Live connectors unproven in CI** — S3/SFTP/Snowflake/Kafka/Databricks/Postgres live paths need partner evidence (manual checklist).
3. **API key is optional** — Community defaults open; partners must set `FORMULAETL_API_KEY`.
4. **Local secret store ≠ enterprise vault** — migrate nodes to `connection_id`; see `docs/CONNECTIONS.md`.
5. **In-process cron** — not a scheduler product.
6. **CI proves DEMO pytest only** — green Actions ≠ live cloud; see `docs/design-partner/PRODUCTION_CHECKLIST.md`.
7. **Control plane vs data plane** — queue exists; prefer private worker next to customer data (`docs/architecture/CONTROL_DATA_PLANE.md`).

---

## What we will not claim

- “Production Snowflake / Kafka / Databricks / S3” based on demo sidecars.
- “Streaming ETL” (Kafka source stops after `max_messages`).
- “Spark engine” (Databricks node triggers a job API).
- “Deploy on Kubernetes” as a shipped operator (Docker Compose exists; no k8s manifests in this audit).
- “Enterprise scheduler / SSO / secrets vault.”