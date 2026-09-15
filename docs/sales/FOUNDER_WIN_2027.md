# Founder win — Customer 001 Soft-PASS (sell into 2027)

Short, honest demo sheet. FormulaHub component names only. **Never claim unproven LIVE.**

## What you can sell today (Soft-PASS)

| Win | Mode | Proof |
|-----|------|--------|
| **Records moving** on canvas while Run is in progress (rows in → rows out badges + edge flow) | **DEMO Soft-PASS** (also works when `FORMULAETL_DEMO=0` on local runners — still not “LIVE cloud”) | Studio Run + `GET /api/runs/{id}` mid-run `node_runs` |
| **Schema from JSON** + **Write JSON** (target structure → nested JSON file on disk) | **DEMO Soft-PASS** | `demos/api-json-write` → `data/out/api_orders.json` |

**LIVE Soft-PASS** in this repo means only evidence already pasted in `docs/PRODUCTION_EVIDENCE.md` (e.g. Databricks Free Edition SQL/Jobs smokes). It does **not** include live S3/SFTP/Snowflake/Kafka wedges unless marked PROVEN there.

**Do not say:** “production LIVE ETL to your warehouse” unless that partner run is PROVEN with redacted evidence + SHA.

## 90-second founder demo (records + JSON)

Prereqs: `make seed` (or `python3 scripts/seed_demo.py`), API + Studio up (`make api` / desktop app).

1. Open Studio. Click **JSON write demo** (or open `?pipeline=demo-api-json-write`).
2. Graph: **HTTP API Source → Schema Map → Schema from JSON → Schema Validate → Write JSON** (rejects branch visible).
3. Click **Run**. Point at node badges ticking **in → out** and flowing edges **before** the run finishes.
4. When done, open Last run (still works) + show file `data/out/api_orders.json` — nested `order` / `customer`.
5. Say: “Same canvas for live credentials later — today this is DEMO Soft-PASS on fixtures; we only call LIVE what we’ve proven with you.”

## Honest language card

| Say | Don’t say |
|-----|-----------|
| DEMO Soft-PASS — fixtures / local workspace | “Live production proven” without evidence |
| LIVE Soft-PASS — only for claims in PRODUCTION_EVIDENCE | Equating CI green with customer cloud green |
| Design-partner path: wire creds, `FORMULAETL_DEMO=0`, paste evidence | New cloud connectors “coming this sprint” as sold |

## Where to dig

- Have vs missing: `docs/studio/HAVE_VS_MISSING_RUN_JSON.md`
- Evidence matrix: `docs/PRODUCTION_EVIDENCE.md` (D14 / D15 Soft-PASS)
- Demo pipeline: `demos/api-json-write/pipeline.json`
- Gates: `tests/api/test_softpass_live_json_gates.py`
