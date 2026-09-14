# FormulaHub ETL — Pricing Sketch

**Status:** Honest sketch for conversations. Product is at **MVP / demo-ready** stage.  
**Brand:** FormulaHub ETL (Lynkx) · [formulahub.io/etl](https://formulahub.io/etl)  
**Do not** present Cloud or Enterprise as fully shipped. Mark anything not yet built as *(planned)*.  
**No** fabricated list prices, discount tables, or customer logos.

License for core: **Apache License 2.0**.

---

## Community — Free forever

**Who:** Individuals, open-source users, students, internal PoCs, early adopters.

**Includes (available now):**
- Visual React Flow canvas  
- Python DAG runner + component SDK  
- Core connectors/components in the MVP catalog (file, Excel, API, **Kafka**, SFTP, DB shapes, S3 mock/real path, PGP, CSV/JSON/XML, validate, transform, Field Mapper, filter, sort, aggregate, Python Row, Snowflake demo/real path, **Databricks Job trigger**, archive, metrics)  
- **Community self-hosted cron scheduler** (per-pipeline enable / cron / timezone)  
- AI Pipeline Builder (offline heuristic; BYO `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` optional)  
- Local / self-hosted deploy (Makefile, Docker Compose)  
- Apache 2.0 — use, modify, redistribute per license  

**Does not include:** Hosted SaaS, SSO, formal support SLAs, enterprise lineage UI, **HA multi-node scheduler**.

**CTA:** Clone, `make install && make seed`, run the demo. No credit card. See formulahub.io/etl.

---

## Cloud — Hosted *(planned / aspirational)*

**Who:** Teams that want FormulaHub ETL without running the stack themselves.

**Direction (not a firm SKU yet):**
- Hosted UI + API  
- Scheduled / triggered runs  
- Shared workspaces and basic multi-user access  
- Managed upgrades of the open core  
- Usage or seat-based pricing — **TBD** after design partners  

**Explicitly aspirational:** No public price list yet. Do not quote a number in outbound email unless leadership has approved one.

**CTA:** “[CALENDAR_LINK] — design-partner conversation; we’ll scope a hosted PoC when ready.”

---

## Enterprise — Governance & support *(planned / aspirational)*

**Who:** Regulated industries, large orgs, teams with security/compliance gates.

**Direction (roadmap — not all shipped):**
- **SSO** (SAML/OIDC) *(planned)*  
- **RBAC** *(planned)*  
- **Lineage** / audit-friendly pipeline history *(planned)*  
- **HA / multi-node scheduler** *(planned — Community ships self-hosted single-process)*  
- Priority support / SLAs *(planned)*  
- Air-gap / private deploy guidance *(planned)*  
- Commercial terms for support and extras while core stays Apache 2.0  

**Pricing:** Custom — based on seats, environments, and support tier. **TBD.** Do not invent list prices.

**CTA:** “[EMAIL] — enterprise evaluation; we’ll share current MVP boundaries and roadmap in writing.”

---

## How to talk about money without overselling

| Do | Don’t |
|----|-------|
| Say “Community is free; Cloud/Enterprise are planned open-core layers” | Claim “Enterprise SSO available today” if it isn’t shipped |
| Say “MVP — happy to show what works in the demo” | Invent ARR, logos, or connector counts |
| Offer a scoped PoC (their S3/SFTP + validate + warehouse) | Promise NiFi-scale processor catalogs on day one |
| Align price conversation to value (visual ETL + ownership) | Compete only on “cheaper than legacy desktop suites” without product fit |

---

## Packaging one-liner (for decks / emails)

> **Community free (Apache 2.0) · Cloud hosted *(planned)* · Enterprise SSO/RBAC/lineage *(planned)*.**  
> We’re early, demo-ready, and transparent about what’s real vs roadmap.  
> formulahub.io/etl
