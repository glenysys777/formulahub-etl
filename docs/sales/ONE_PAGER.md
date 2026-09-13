# FormulaHub ETL (Lynkx) — Product One-Pager

**Visual ETL for files, APIs, SFTP, and databases**  
Open source · AI-assisted · Deploy anywhere · Apache License 2.0  
[formulahub.io/etl](https://formulahub.io/etl)

---

## The problem

Data teams still need **visual, auditable, pre-warehouse ETL** for file drops, PGP, validation, rejects, and warehouse loads — without a six-figure license or a folder of tribal scripts. The modern stack filled only part of the job:

| Gap | Reality |
|-----|---------|
| Airbyte | Excellent EL syncs — weak on mid-pipeline transform, validation, PGP, reject handling |
| NiFi / Hop | Powerful, but heavyweight ops and a steep learning curve |
| dbt | Best-in-class *in-warehouse* T — not Source → Decrypt → Validate → Route *before* the warehouse |
| “Just Python” | Works until the 3rd engineer can’t read the 4th script |
| Legacy desktop ETL | Familiar canvas mental model, but teams want a modern, open, Git-friendly stack |

Teams want **drag-and-drop pipelines they can own** — React canvas, Python runner, JSON/YAML in Git.

---

## The solution

**FormulaHub ETL** is an open-source visual ETL studio (product line **Lynkx**):

- **React Flow canvas** — drag-and-drop DAG (nodes + edges), JSON/YAML under the hood  
- **Python runner** — lightweight component SDK; no Spark required for MVP  
- **AI Pipeline Builder** — English prompt → pipeline graph (LLM optional; offline heuristic works)  
- **Field Mapper** — discover schema, drag columns, expression maps  
- **Honest demo mode** — mock S3 + Snowflake (and SFTP/DB staging) so anyone can run end-to-end without cloud accounts  

**Mental model:** familiar visual ETL. **Stack:** modern Python + React. **License:** Apache 2.0.

---

## Demo flow (90 seconds)

**S3 → PGP Decrypt → CSV Parse → Schema Validate → Transform → Snowflake (demo) → Archive**

| Beat | What you see |
|------|----------------|
| Load demo | Full graph on canvas |
| Run | Live logs, rows in/out, duration |
| Rejects | **3** bad rows isolated; **10** good rows loaded |
| Node params | Click Validate / Transform / Snowflake — inspect config |
| AI Build | Paste English → graph appears |

Local: UI `http://127.0.0.1:18766` · API `http://127.0.0.1:18765`

---

## Differentiation (one line each)

| vs | FormulaHub ETL |
|----|----------------|
| **Airbyte** | Full ETL (transform, validate, PGP, rejects) — not only syncs |
| **NiFi / Hop** | Lighter UX + Python runtime for the common file/API/SFTP/DB case |
| **dbt** | Complements dbt: Source → Validate → Encrypt → Load *into* the warehouse |
| **Just Python** | Same Python power, plus a visual DAG and Git-friendly JSON/YAML |
| **Legacy desktop ETL** | Same visual mental model; browser UI, open-core, no desktop lock-in |

**Tagline:** Visual ETL + modern stack + AI builder + Apache 2.0 (no lock-in).

---

## Open-core pricing sketch *(aspirational — MVP stage)*

| Tier | Who | What |
|------|-----|------|
| **Community** | Individuals, OSS, PoCs | Free forever — canvas, runner, core connectors, AI builder (heuristic / BYO key) |
| **Cloud** *(planned)* | Teams who want hosted | Hosted UI/API, scheduled runs, shared workspaces — pricing TBD |
| **Enterprise** *(planned)* | Regulated / large orgs | SSO, RBAC, lineage, support SLAs, air-gap options — pricing TBD |

No fake ARR or customer logos. Product is at **MVP / demo-ready** stage; Cloud and Enterprise features are on the roadmap.

---

## Proof (verified locally)

- 17 pytest passed  
- Playwright: Run + AI Build OK  
- Goal verify: PASS  

Origin: open-source codebase (Formula Hub / FormulaHub ETL).

---

## CTA

**See it live (15 min):** [CALENDAR_LINK]  
**Try locally:** clone → `make install && make seed && make api` + `make web` → Load demo → Run  
**Talk to founder:** [EMAIL] · [LINKEDIN]  
**Product:** [formulahub.io/etl](https://formulahub.io/etl)

*FormulaHub ETL — visual ETL that teams can actually own.*
