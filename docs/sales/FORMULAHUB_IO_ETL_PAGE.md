# FormulaHub ETL — Product page copy

**Brand:** FormulaHub ETL (Lynkx)  
**Canonical URL:** [formulahub.io/etl](https://formulahub.io/etl)  
**Also:** formulahub.ai links here  
**Use:** Paste into formulahub.io/etl (hero → CTA). Keep claims MVP-honest.

---

## Hero

**Visual ETL for files, APIs, SFTP, and databases**  
Open source · AI-assisted · Deploy anywhere · Apache License 2.0

Drag-and-drop pipelines your team can own — React canvas, Python runner, JSON/YAML in Git. Build Source → Validate → Transform → Load without a six-figure license or a folder of tribal scripts.

**Primary CTA:** Try locally / Book a 15-min walkthrough  
**Secondary:** View components · See services

---

## Value props

| | |
|--|--|
| **Own the pipeline** | Visual DAG on a React Flow canvas; definitions as JSON/YAML you can version in Git. |
| **Modern stack** | Lightweight Python runner + component SDK — no Spark required for everyday file/API/SFTP/DB jobs. |
| **AI Build** | Describe the flow in English → get a pipeline graph (offline heuristic; optional BYO LLM key). |
| **Field Mapper** | Discover schema, drag columns, expression maps (`out=expr`) — MVP visual mapping, not a black box. |
| **Run anywhere** | Local Makefile or Docker Compose self-host. Demo mode mocks cloud so anyone can run end-to-end. |
| **Open-core honesty** | Community free forever (Apache 2.0). Cloud and Enterprise layers planned — we say what’s shipped vs roadmap. |

---

## Use cases

- **Encrypted file drop → warehouse** — S3/File → PGP → Parse → Validate → Transform → load → Archive  
- **API → map → load** — HTTP/REST → Field Mapper → Transform → Validate → DB/file/warehouse  
- **Excel / spreadsheet → database** — Excel Source → Discover schema → map → Validate → destination  
- **SFTP / partner files → staging** — SFTP → parse → map → file or DB (production needs real credentials)  
- **Reject handling** — Schema Validate isolates bad rows; good path continues  
- **Light transforms** — rename, cast, filter, sort, aggregate, dedupe, lookup join, sandboxed Python Row  

*ICP:* teams moving **file / API / SFTP / Excel → DB or warehouse**, who want visual, auditable pre-warehouse ETL.

---

## Components (summary)

**Sources:** S3, local file, Excel, HTTP/API, SFTP, Postgres, MySQL, SQLite  
**Parse & map:** CSV / JSON / XML parsers · Schema Map · **Field Mapper**  
**Transform & quality:** Transform · Schema Validate · Filter · Sort · Aggregate · Dedupe · Lookup Join · Python Row · PGP encrypt/decrypt  
**Destinations & ops:** Local file · Excel · Snowflake · SFTP · Postgres · MySQL · SQLite · Archive · Logger/Metrics  

MVP catalog — not a 200-connector suite. Demo mode mocks S3, SFTP, Snowflake, and some DB wires so you can try without cloud accounts. See the [component catalog](./COMPONENTS.md) for honest limits.

---

## AI Build + Field Mapper

**AI Pipeline Builder** — Paste English (“S3 CSV → validate → Snowflake”) → nodes and edges appear. Works offline with heuristics; optional `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` for richer builds.

**Field Mapper** — Discover schema from source sample → drag source → target columns → expression mappings, optional filter, `drop_unmapped`. Mappings persist in node config. **MVP:** visual column mapping — not a multi-output lookup IDE.

Together: prompt a starting graph, then refine maps and validation before you run.

---

## Docker / self-host

- **Local:** `make install && make seed` → API + web (UI `:18766` · API `:18765`)  
- **Docker:** Compose stack for UI + API — run on your laptop or private network  
- **Demo mode:** `FORMULAETL_DEMO=1` for mock S3/SFTP/Snowflake/DB staging — flip off with real credentials for production paths  
- **License:** Apache 2.0 — use, modify, redistribute per license  

No SaaS lock-in for Community. Hosted Cloud is *planned*.

---

## Services CTA

Need a production pipeline sooner than DIY?

- **90-min paid diagnostic** — scope sources, maps, rejects, and deploy shape  
- **First production pipeline + Field Mapper setup** — shipped with your team  
- **Monthly automation retainer** — keep pipelines healthy and growing  

→ [Services offer](./SERVICES_OFFER.md) · Book: `[CALENDAR_LINK]` · `[EMAIL]`

---

## Open-core tiers *(honest MVP)*

| Tier | Status | What |
|------|--------|------|
| **Community** | **Now — free forever** | Canvas, runner, core connectors, AI Build (heuristic / BYO key), Field Mapper, local + Docker self-host, Apache 2.0 |
| **Cloud** | *(planned)* | Hosted UI/API, schedules, shared workspaces — pricing TBD with design partners |
| **Enterprise** | *(planned)* | SSO, RBAC, lineage, support SLAs, air-gap guidance — custom |

We do not invent logos, ARR, or connector counts. Product is **MVP / demo-ready**; Cloud and Enterprise features are on the roadmap.

---

## Footer / SEO

**FormulaHub ETL (Lynkx)** — Visual ETL + modern stack + AI builder + Apache 2.0.  
Canonical: **https://formulahub.io/etl** · formulahub.ai → this page.

*Visual ETL that teams can actually own.*
