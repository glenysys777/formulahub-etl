# CUSTOMER_001 — Production evidence matrix (PROVE+SELL)

**Audited tip:** `1549d6d` (`origin/main`) + LOCAL wedge PR (2026-09-14)  
**Mission:** Honest production-evidence for design-partner sell. **Never claim LIVE proven from `FORMULAETL_DEMO=1`.**  
**Sources:** code under `packages/runner`, `packages/api`, demos, `tests/`, and prior audits (`PRODUCTION_READINESS.md`, `PRODUCTION_EVIDENCE.md`, `CURRENT_STATE_MATRIX.md`). Sales copy is **not** evidence.

## Legend

| Column | Meaning |
|--------|---------|
| **STATUS** | `DEMO` / `ALPHA` / `ABSENT` — maturity of the shipped path |
| **DEMO PROVEN?** | Green under `FORMULAETL_DEMO=1` (fixtures, mock S3, CSV sidecars, Jobs-shaped JSON) |
| **LOCAL PROVEN?** | Agent/CI laptop proof (pytest, LOCAL/DEMO bench) — still **not** customer cloud |
| **LIVE EXTERNAL SYSTEM PROVEN?** | Real partner AWS / SFTP / Snowflake / Postgres / Databricks / Kafka with `FORMULAETL_DEMO=0` + pasted evidence |
| **CUSTOMER SAFE?** | OK to put **their** data/creds on this path **today** without overselling |
| **REMAINING RISK** | What still fails trust for CUSTOMER_001 |

**Rule:** DEMO sidecar SUCCESS ≠ LIVE warehouse / cluster / broker proof.

---

## FAIL list — LIVE wedge (must stay FAIL until real run)

Paste redacted JSON + SHA + date into `PRODUCTION_EVIDENCE.md` §C before flipping any row to YES.

| ID | LIVE claim | Status | Blocker |
|----|------------|--------|---------|
| C1 | Live AWS S3 read in wedge | **FAIL / UNPROVEN** | No partner creds in CI/agent |
| C2 | Live SFTP read in wedge | **FAIL / UNPROVEN** | Same |
| C3 | Live PGP with partner key | **FAIL / UNPROVEN** | Same |
| C4 | Live Postgres load | **FAIL / UNPROVEN** | Same |
| C5 | Live Snowflake load | **FAIL / UNPROVEN** | Same + live path is `INSERT…executemany` (not COPY) |
| C6 | Full live wedge E2E | **FAIL / UNPROVEN** | Harness exists (`scripts/live_wedge_e2e.py`); never run with real systems here |
| — | Live Databricks Jobs / SQL | **FAIL / UNPROVEN** | Sidecar ≠ workspace |
| — | Live Kafka broker consume | **FAIL / UNPROVEN** | Fixture jsonl ≠ broker |

Harness: `docs/design-partner/LIVE_WEDGE.md`. CI: `pytest -m "not live and not bench"` + `FORMULAETL_DEMO=1` only.

---

## Evidence matrix

| FEATURE | STATUS | DEMO PROVEN? | LOCAL PROVEN? | LIVE EXTERNAL SYSTEM PROVEN? | CUSTOMER SAFE? | REMAINING RISK |
|---------|--------|--------------|---------------|------------------------------|----------------|----------------|
| **SFTP source** | DEMO CI / ALPHA code (`paramiko`, timeouts, retries, host-key RejectPolicy) | **YES** (fixture copy) | **YES** (unit/integration under DEMO) | **NO** | **No** for their SFTP until LIVE run | Live path untested; prefer `connection_id` + key/password refs |
| **SFTP destination** | DEMO / ALPHA code | **YES** (demo) | **YES** (DEMO tests) | **NO** | **No** until LIVE | Same |
| **S3 source** | DEMO CI / ALPHA code (`boto3` stream + paginated list + retries) | **YES** (`data/s3/` mock) | **YES** (wedge bench LOCAL/DEMO) | **NO** | **No** until LIVE IAM/object read | Mock bucket ≠ AWS; IAM/role chain unproven |
| **PGP decrypt/encrypt** | ALPHA crypto (`pgpy` + optional `gpg` path-to-path) / DEMO keys | **YES** (fixture keys in git) | **YES** (wedge + large-file path) | **NO** (partner key ops) | **Partial** — crypto real; **key handling not customer-safe** if keys in repo/JSON | Prefer refs; no partner KMS; demo keys must never ship to prod |
| **CSV parse** | ALPHA (chunked batches, malformed policy) | **YES** | **YES** (incl. 10K–1M LOCAL/DEMO) | N/A (local format) | **Yes** for laptop/partner file sizes with streaming | Multi-GB still one process; not a distributed parser |
| **Schema validate** | ALPHA | **YES** | **YES** | N/A | **Yes** for typed column checks | Expression/type contract limited; silent edge cases possible |
| **Rejects fan-out** | ALPHA (JSONL spill) | **YES** (demo 3 rejects) | **YES** | N/A | **Yes** for DEMO/partner laptop | Need retention/ops story for prod volumes |
| **Column map / Schema Map** | ALPHA | **YES** | **YES** | N/A | **Yes** | Rename-only; not a full MDM layer |
| **Field Mapper (`tmap`)** | ALPHA (AST exprs + Studio UI) | **YES** | **YES** | N/A | **Yes** for scoped maps | AST subset; failures → null + log |
| **Lookup Join** | ALPHA (in-memory hash) | **YES** (demo) | **YES** (small N) | N/A | **Partial** — fine for thousands | Millions → RAM; materializes |
| **Dedupe** | ALPHA | **YES** | **YES** (`keep=first` streams; `keep=last` materializes) | N/A | **Partial** | Key-set RSS dominates at 10M LOCAL/DEMO |
| **Postgres source/dest** | DEMO CI / ALPHA live (`psycopg`) | **YES** (SQLite/CSV fallback) | **YES** (DEMO) | **NO** | **No** until LIVE DSN proof | SQL-as-config; live untested in CI |
| **Snowflake destination** | DEMO (CSV + `.load.json`) / weak live (`executemany`) | **YES** (sidecar) | **YES** (streaming demo sink to 1M+) | **NO** | **No** as “warehouse product” | **Do not sell high-volume Snowflake** until staging+COPY proven — see `docs/snowflake/BULK_LOAD.md` |
| **Databricks Job** | DEMO sidecar / ALPHA Jobs API client | **YES** (Jobs-shaped JSON) | **YES** (DEMO tests) | **NO** | **No** until workspace token run | Orchestration only — **not Spark**; FormulaETL does not run the cluster |
| **Databricks SQL** | DEMO sidecar / ALPHA Statement Execution API | **YES** (resolved SQL sidecar) | **YES** (DEMO + Contexts) | **NO** | **No** until warehouse_id + token | Control-plane SQL submit; LIVE UNPROVEN |
| **Archive** | ALPHA | **YES** | **YES** | N/A (local FS) | **Yes** for local/partner FS | Not object-store lifecycle / S3 Glacier |
| **Schedule (cron)** | DEMO / ALPHA bookkeeping | **YES** (UI + enqueue) | **YES** (unit) | N/A | **Partial** — single-process only | In-process poll; no HA / misfire / distributed lock |
| **Retries** | ALPHA on S3/SFTP I/O (`retry_call`); job-level retry **ABSENT** | **YES** (code paths under DEMO where exercised) | **Partial** | **NO** live retry proof | **Partial** | Status constant `retrying` exists; worker does not auto-retry failed runs |
| **Persistence (runs/versions)** | ALPHA (SQLite ledger + versions + queue) | **YES** | **YES** | N/A | **Yes** for single-node partner | Local file DB; no Postgres control plane yet; backup = file copy |
| **Secrets / Connections** | ALPHA (env + Fernet local store + `connection_id`) | **YES** | **YES** | N/A | **Partial** — set `FORMULAETL_API_KEY`; no Vault/KMS | Open API when key unset; not enterprise vault |
| **Logging / run events** | ALPHA (SQLite events + node_runs + CLI emit) | **YES** | **YES** | N/A | **Yes** for partner triage | No retention SLO / SIEM export |
| **Large files / memory bound** | ALPHA LOCAL/DEMO streaming | **YES** | **YES** (1M ≤~306 MB RSS; 10M completes) | **NO** live throughput | **Partial** — claim LOCAL/DEMO only | Sort/join/`keep=last` still materialize; live Snowflake materializes then `executemany` |
| **AI Pipeline Builder** | DEMO (heuristic + optional LLM) | **YES** | **YES** | N/A | **Demo only** — review before any live data | Auto-saves; do not auto-run unreviewed graphs on prod |
| **Job Contexts `${…}`** | ALPHA | **YES** | **YES** | N/A | **Yes** for non-secret params | Not a secrets vault |
| **Pipeline validate** | ALPHA (structural) | **YES** | **YES** | **NO** (not live connectivity) | **Yes** as preflight | Does not prove cloud reachability |
| **Studio (canvas / Save / Git mirror)** | ALPHA | **YES** | **YES** (build + UX) | N/A | **Yes** as designer | Vercel UI ≠ runner; API must be local/Docker |
| **Desktop shell** | ABSENT (plan only) | **NO** | **NO** | **NO** | N/A | `DESKTOP_SHELL.md` — do not merge/sell as shipped |
| **Hosted full ETL runtime** | ABSENT (Vercel UI only) | N/A | N/A | **NO** | **No** | Do not imply Vercel runs jobs |
| **Kafka source** | DEMO batch fixture / ALPHA clients | **YES** | **YES** | **NO** | **No** as “streaming” | Finite `max_messages` pull — not a streaming runtime |
| **Spark / K8s / Stripe / Talend importer** | ABSENT (correct freeze) | — | — | — | — | **Do not build** in PROVE+SELL |

---

## What is sellable TODAY (design-partner **services**)

Sell **implementation + honesty**, not “LIVE proven warehouse”:

1. **Paid diagnostic / workshop** — canvas walkthrough, DEMO wedge, written gap list (this matrix).
2. **First pipeline build** on Community open-core — map/validate/rejects/archive on **their** sample files under DEMO or private worker.
3. **LIVE wedge engagement** — scoped CREDENTIALS + `FORMULAETL_DEMO=0` proof for SFTP|S3 → PGP → CSV → validate → map → Postgres|Snowflake → archive; evidence pasted into §C.
4. **Databricks orchestration consulting** — FormulaETL triggers Jobs / SQL; **customer Spark stays in Databricks** (see architecture note below).

Do **not** sell as proven today: high-volume Snowflake COPY, live Kafka streaming, Spark-inside-FormulaETL, HA scheduler, SSO/Vault, Vercel-hosted runner.

## Architecture honesty (Databricks)

```
FormulaETL (control / orchestration)          Customer Databricks (data plane)
─────────────────────────────────────         ────────────────────────────────
Studio + API + sequential PipelineRunner  →   Jobs API run-now / SQL Warehouse
DEMO sidecars prove graph shape only      →   Distributed Spark / SQL compute
```

LIVE Databricks = real `workspace_host` + token (+ `warehouse_id` for SQL) with `FORMULAETL_DEMO=0`. Until then: **UNPROVEN**.

## Cross-links

- Freeze: [`PROVE_SELL_FREEZE.md`](./PROVE_SELL_FREEZE.md)
- Evidence log: [`PRODUCTION_EVIDENCE.md`](./PRODUCTION_EVIDENCE.md)
- Readiness levels: [`PRODUCTION_READINESS.md`](./PRODUCTION_READINESS.md)
- Snowflake bulk gap: [`snowflake/BULK_LOAD.md`](./snowflake/BULK_LOAD.md)
- Live harness: [`design-partner/LIVE_WEDGE.md`](./design-partner/LIVE_WEDGE.md)
- Founder demo script: [`demo/THREE_MINUTE_FOUNDER_DEMO.md`](./demo/THREE_MINUTE_FOUNDER_DEMO.md)
- Internal price bands: [`sales/IMPLEMENTATION_PRICE_GUIDELINES.md`](./sales/IMPLEMENTATION_PRICE_GUIDELINES.md)

---

## LOCAL wedge pack (this PR) — filesystem + optional local Postgres

**Classification honesty:** rows below are **LOCAL_PROVEN / LOCAL/DEMO / LOCAL_ONLY** only. They do **not** flip any LIVE EXTERNAL FAIL row above to YES.

| ID | Claim | Classification | Status | Command / evidence | Notes |
|----|-------|----------------|--------|--------------------|-------|
| L0 | Fixture pack + pipeline JSON exist | LOCAL_ONLY | PROVEN | `fixtures/customer001_local_wedge/`, `demos/customer001-local-wedge/pipeline.json` | Encrypted drop + lookup + expected counts |
| L1 | DEMO path reconciles N=R+D+L | LOCAL/DEMO | PROVEN | `python3 scripts/customer001_local_wedge.py --mode demo` | Postgres node → SQLite/CSV mirror |
| L2 | Pytest always-on reconcile | LOCAL/DEMO | PROVEN | `pytest tests/integration/test_customer001_local_wedge.py` | CI-safe |
| L3 | Real local Postgres INSERT → `formulahub_wedge.customers_wedge` | LOCAL_PROVEN | PROVEN* | `FORMULAETL_DEMO=0` + `LOCAL_POSTGRES_DSN=host=localhost dbname=formulahub_wedge` + `--mode postgres`; Mac `START-POSTGRES.command` (`LC_ALL=en_US.UTF-8`) | *When Postgres up; CI skips → LOCAL_ONLY. **Not** LIVE cloud Postgres. |
| L4 | Rejects file written | LOCAL/DEMO | PROVEN | `data/rejects/customer001/…` | R=2 |
| L5 | Archive copy of drop | LOCAL/DEMO | PROVEN | `data/archive/customer001/…` | copy mode |
| L6 | Metrics + node timings + peak RSS | LOCAL_ONLY | PROVEN | harness JSON | `data/out/customer001/wedge_report.json` |
| L7–L12 | Fail injects (bad PGP, missing file, bad CSV, schema drift, dest down, retry) | LOCAL_ONLY | PROVEN | `scripts/customer001_fail_injections/` | Expect fail / retry OK |
| L13 | Adapted demos → local PG | LOCAL_PROVEN | PROVEN* | `demos/*/pipeline.local-postgres.json` (s3-pgp-snowflake, core-path, lookup-join-mapper) | Local files + `customers_wedge`; S3/Snowflake remain LIVE **UNPROVEN** |
| L14 | Mac pack `START-POSTGRES.command` | LOCAL_ONLY | PROVEN | `scripts/START-POSTGRES.command` → FormulaHub-ETL-Mac pack | Locale fix + DDL |

**Expected counts:** `N=12 = R=2 + D=2 + L=8`.

**Mac LOCAL_PROVEN quick path:**

```bash
# Double-click FormulaHub-ETL-Mac/START-POSTGRES.command
export FORMULAETL_DEMO=0
export LOCAL_POSTGRES_DSN="host=localhost port=5432 dbname=formulahub_wedge"
python3 scripts/customer001_local_wedge.py --mode postgres
```

**Do not** use L* rows to mark C1–C6 or LIVE Databricks/Kafka as proven.

Docs: [`CUSTOMER001_LOCAL_WEDGE.md`](./CUSTOMER001_LOCAL_WEDGE.md) · Harness: `scripts/customer001_local_wedge.py`
