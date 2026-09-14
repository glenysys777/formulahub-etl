# PROVE+SELL freeze (CUSTOMER_001)

**Locked mode:** BUILD → **PROVE+SELL**  
**Audited tip:** `e38605d` · 2026-09-14 (Desktop ALPHA `cc04ebc` / #20; LOCAL wedge #22)  
**Companion:** [`CUSTOMER001_EVIDENCE_MATRIX.md`](./CUSTOMER001_EVIDENCE_MATRIX.md)

This freeze protects founder credibility. Demo fixtures and green CI are **not** LIVE proof.

---

## Frozen (do not start in this mode)

| Area | Why frozen |
|------|------------|
| New connectors | Dilutes the LIVE wedge; matrix already covers the path |
| Stripe / billing / marketplace | Wrong layer for design-partner proof |
| Kubernetes operator / manifests | Roadmap only; Docker Compose is enough for partner deploys |
| Talend / legacy-ETL importer | Expansion vs trust |
| Embedded Spark / Polars “runtime product” | Databricks Job/SQL already orchestrate; do not fake a Spark engine |
| Cosmetic website HTML redesign | Separate repo; not evidence |
| Selling Desktop as LIVE proof | Studio.app / Electron Mac pack is **ALPHA** (`cc04ebc` / #20) — DEMO/LOCAL launch path only; not LIVE_EXTERNAL wedge proof |
| Claiming LIVE from `FORMULAETL_DEMO=1` | Hard rule — sidecars / mock S3 / CSV “Snowflake” are DEMO |
| High-volume Snowflake sales claim | Live path is still `INSERT…executemany` — see `snowflake/BULK_LOAD.md` |
| “Streaming Kafka” / “we run Spark” marketing | Batch pull + Jobs API only |

---

## Allowed (PROVE+SELL work)

| Work | Notes |
|------|-------|
| **Trust / credibility docs** | Evidence matrix, freeze, LIVE FAIL list, honest architecture |
| **Design-partner ops pack** | Deploy, security, connections, backup, troubleshooting, checklist |
| **DEMO=0 LIVE wedge** | When partner credentials exist: run `scripts/live_wedge_e2e.py`, paste redacted evidence |
| **Snowflake bulk follow-on** | Document staging + `COPY INTO`; implement only with tests when scheduled — not claimed until proven |
| **Databricks honesty** | Control-plane orchestration vs customer Spark data plane |
| **Founder / sales scripts** | 3-minute DEMO script; internal implementation price guidelines |
| **Bugfixes that unblock DEMO or partner deploy** | Startup hangs, validate, secret masking — keep narrow |
| **LOCAL/DEMO performance evidence** | Benches stay labeled LOCAL/DEMO; never rebrand as LIVE |

---

## DEMO=0 wedge gate (when credentials arrive)

```bash
python3 scripts/live_wedge_e2e.py --check   # must show ready, not skip
export RUN_LIVE_WEDGE=1 FORMULAETL_DEMO=0
python3 scripts/live_wedge_e2e.py           # real network
# Paste redacted JSON → docs/PRODUCTION_EVIDENCE.md §C with SHA + date
```

Until that paste exists: every LIVE row stays **UNPROVEN / FAIL**.

Preferred partner path:

`SFTP | S3 → PGP → CSV → validate → map → (dedupe) → Postgres | Snowflake → archive`

Databricks Jobs/SQL are a **separate** LIVE proof (workspace token), not a substitute for the file→warehouse wedge.

---

## Sell vs prove (one line each)

| Motion | OK to say | Forbidden |
|--------|-----------|-----------|
| Design-partner services | “We implement and prove your path on your systems” | “Already proven on live Snowflake in CI” |
| Product demo | “DEMO mode fixtures so you can run without cloud accounts” | “This CSV under `data/out/snowflake` is your warehouse” |
| Databricks | “We orchestrate their Jobs/SQL; Spark stays in Databricks” | “FormulaETL is a Spark engine” |
| CI green | “DEMO pytest + web build” | “Production connectors verified” |

---

## Exit criteria for “LIVE proven” on CUSTOMER_001 wedge

1. `FORMULAETL_DEMO=0` + real creds  
2. Harness or equivalent E2E success JSON (redacted) in evidence log  
3. `FORMULAETL_API_KEY` on + secrets via Connections/refs  
4. Private worker next to data preferred (`docs/architecture/CONTROL_DATA_PLANE.md`)  
5. Snowflake: if volume matters, staging+`COPY INTO` implemented **and** tested — not `executemany` alone  
