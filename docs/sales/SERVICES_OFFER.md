# FormulaHub ETL — Services Offer

**One-pager for founders / GTM** · Paste into proposals or attach after a demo.  
**Product:** FormulaHub ETL (Lynkx) · [formulahub.io/etl](https://formulahub.io/etl)  
**Stage:** MVP / demo-ready open-core + hands-on services to get to production.

---

## Who this is for (ICP)

Ops, data, and integration teams who need **reliable pre-warehouse ETL**:

**Sources:** partner **files**, **APIs**, **SFTP**, **Excel** / spreadsheets  
**Targets:** **databases** and **warehouses** (Postgres, MySQL, Snowflake paths, files/staging)  
**Pain:** tribal scripts, weak mid-pipeline validation/rejects, or heavyweight platforms for a common file→DB job

If the job is Source → Decrypt/Parse → Map → Validate → Load → Archive, we fit.

---

## How we use FormulaHub ETL

We deliver on the open-core product your team can keep:

| Capability | In the engagement |
|------------|-------------------|
| **Visual canvas** | Pipeline as a React Flow DAG; JSON/YAML in Git |
| **Field Mapper** | Schema discover, drag maps, expression fields — configured for *your* columns |
| **AI Build** | Optional: English → starting graph, then we harden |
| **Components** | File/S3, Excel, HTTP, SFTP, PGP, parse, validate, transform, DB/warehouse destinations |
| **Deploy** | Self-host (Makefile / Docker) on your network; demo mode for PoC, real creds for prod |

You own the pipelines. We accelerate the first production path and optional ongoing automation.

---

## Offers

### 1. 90-minute paid diagnostic

**Goal:** Decide fit, scope, and next step — not a free discovery call that goes nowhere.

- Review sources, volumes, SLAs, reject/error needs  
- Sketch the FormulaHub ETL graph (map + validate + load)  
- Call out MVP vs roadmap (honest: what’s demo-ready vs needs credentials / custom)  
- Written one-pager: recommended path, risks, ballpark  

**Ballpark:** **$2k–$5k** (fixed)

---

### 2. First production pipeline + Field Mapper setup

**Goal:** One live path from your source → validated load, with mapping your team can maintain.

**Typical deliverables:**
- Pipeline design (canvas + Git-friendly definition)  
- Source → parse → **Field Mapper** (schema + expressions) → Schema Validate → destination  
- Reject handling and basic run logs / metrics  
- Credentials & env wiring (`FORMULAETL_DEMO=0` production path)  
- Docker or Makefile deploy notes for your environment  
- Handoff session: how to edit maps, re-run, and extend  

**Ballpark:** **$8k–$25k** (scoped to complexity: PGP, multi-file, multi-target, custom Python Row)

---

### 3. Monthly automation retainer

**Goal:** Keep pipelines healthy and grow the catalog without hiring a full ETL squad.

- Pipeline changes, new maps, new partner feeds  
- Monitoring hygiene, fail/reject triage  
- Priority Slack/email response during business hours  
- Optional: next pipeline sketches, AI Build prompts → hardened graphs  

**Ballpark:** **$3k–$10k / month** (hours + pipeline count)

---

## Deliverable checklist (first pipeline)

- [ ] Scoped source(s) and destination(s) documented  
- [ ] Working FormulaHub ETL pipeline (canvas + YAML/JSON)  
- [ ] Field Mapper configured (discover + drag/expression maps)  
- [ ] Schema Validate + reject path  
- [ ] Successful production-style run (or staging with real shapes)  
- [ ] Deploy notes (Docker / self-host)  
- [ ] Short runbook for your team  

---

## Engagement flow

1. **Diagnostic** (90 min + write-up) → go / no-go  
2. **First pipeline** SOW → build → handoff  
3. **Retainer** (optional) → iterate and add feeds  

CTA: `[CALENDAR_LINK]` · `[EMAIL]` · Product: [formulahub.io/etl](https://formulahub.io/etl)

---

## Pricing note

Ranges are **ballpark for early engagements**, not a public rate card. Final quote follows diagnostic scope. Community software remains **free (Apache 2.0)**; services are how we help you ship faster.

*FormulaHub ETL — visual ETL you own · services when you want speed.*
