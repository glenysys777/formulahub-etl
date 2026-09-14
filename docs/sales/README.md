# FormulaHub ETL — Sales & Demo Pack

Client-ready copy for founders and GTM. All files are markdown — copy-paste into email or docs.  
**Intent:** founder syncs this folder to Desktop `FormulaETL-sales`.

**Product:** FormulaHub ETL (Lynkx) — open-source visual ETL (React Flow canvas, Python runner, Field Mapper, AI Pipeline Builder).  
**Site:** [formulahub.io/etl](https://formulahub.io/etl)  
**Demo:** S3 → PGP → Parse → Validate → Transform → Snowflake (demo) → Archive.  
**Model:** Open-core — Community free · Cloud hosted *(planned)* · Enterprise SSO/RBAC/lineage *(planned)*.  
**Stage:** MVP / demo-ready. Do **not** invent logos, revenue, or fake benchmarks.

**Honesty — Kafka / Databricks:** Kafka Source + Databricks Job Trigger are production-shaped (real client libraries / Jobs API when credentials set) but **CI and default DEMO=1 use fixtures/sidecars — live Kafka/Databricks against customer clusters is unproven until a design-partner run.** Do not claim live E2E in CI.

**Honesty — Kafka / Databricks:** Kafka Source + Databricks Job Trigger are production-shaped (real client libraries / Jobs API when credentials set) but **CI and default `FORMULAETL_DEMO=1` use fixtures/sidecars — live Kafka/Databricks against customer clusters is unproven until a design-partner run.** Do not claim live E2E in CI.

**Local demo:** UI `http://127.0.0.1:18766` · API `http://127.0.0.1:18765`  
**Verified (as of pack creation context):** 17 pytest passed · Playwright Run + AI Build OK · Goal verify PASS.

**Competitive framing:** Airbyte / NiFi / Hop / dbt / “just Python.” For legacy desktop ETL, speak in **features** (visual canvas, field mapping, file/API/SFTP/DB) — not rival product names.

---

## Files

| File | Use when |
|------|----------|
| [ONE_PAGER.md](./ONE_PAGER.md) | Attach to email, leave-behind PDF source, LinkedIn doc |
| [PITCH_EMAIL.md](./PITCH_EMAIL.md) | Cold outreach · warm follow-up · LinkedIn DM |
| [DEMO_SCRIPT.md](./DEMO_SCRIPT.md) | Live 90-second screen share |
| [CLIENT_DEMO.md](./CLIENT_DEMO.md) | 60-second studio walkthrough + Field Mapper |
| [OBJECTIONS.md](./OBJECTIONS.md) | Call prep vs Airbyte / NiFi / Hop / dbt / “just Python” / legacy desktop |
| [USE_CASES.md](./USE_CASES.md) | Matched vs roadmap honesty table |
| [USE_CASES_HOW.md](./USE_CASES_HOW.md) | Per use case: what / components / AI Build + Field Mapper + Run |
| [COMPONENTS.md](./COMPONENTS.md) | Component catalog + honest limits |
| [PRICING_SKETCH.md](./PRICING_SKETCH.md) | Honest Community / Cloud / Enterprise sketch |
| [FORMULAHUB_IO_ETL_PAGE.md](./FORMULAHUB_IO_ETL_PAGE.md) | Paste-ready copy for formulahub.io/etl |
| [SERVICES_OFFER.md](./SERVICES_OFFER.md) | Diagnostic · first pipeline · retainer one-pager |

---

## Suggested flow

1. Send **cold** or **LinkedIn** from `PITCH_EMAIL.md` → book call.  
2. Run **DEMO_SCRIPT.md** or **CLIENT_DEMO.md** live.  
3. Follow up with **warm** email + `ONE_PAGER.md`.  
4. Handle pushback from `OBJECTIONS.md`; share `USE_CASES_HOW.md` / `COMPONENTS.md` for technical depth; share `PRICING_SKETCH.md` only when they ask about commercial.

---

## Placeholders to replace before send

- `[CALENDAR_LINK]` — booking URL  
- `[EMAIL]` / `{{EMAIL}}` — founder email  
- `{{YourName}}` / `{{Title}}` / `{{LINKEDIN}}`  
- `{{FirstName}}` / `{{TOPIC_OR_PAIN}}` / `{{Colleague}}`

---

## Related product docs

- Repo root [`README.md`](../../README.md) — positioning, quickstart, architecture  
- [`demos/s3-pgp-snowflake/`](../../demos/s3-pgp-snowflake/) — spectacular demo  
- [`docs/screenshots/`](../screenshots/) — capture canvas / AI Build / metrics when ready  

---

*Keep claims tight. Prefer “show the demo” over “claim the market.”*
