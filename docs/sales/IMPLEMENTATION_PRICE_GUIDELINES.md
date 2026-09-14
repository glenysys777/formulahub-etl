# Implementation price guidelines — INTERNAL ONLY

**Classification:** Internal founder / GTM guidance. **Not** website prices. **Not** for formulahub.io or public decks as a rate card.  
**Product stage:** DEMO-ready open-core + design-partner services (see `CUSTOMER001_EVIDENCE_MATRIX.md`).  
**Currency:** USD. Adjust for India entity (Formula Hub Pvt Ltd) separately when quoting INR/GST.

Do **not** publish these bands on the marketing site. Public packaging stays Community free + Cloud/Enterprise *planned* (`PRICING_SKETCH.md`).

---

## How to use

- Quote a **scoped statement of work**, not a SKU barcode.
- Always attach honesty: DEMO proven ≠ LIVE proven; Snowflake COPY and live connectors need evidence.
- Prefer fixed-fee with clear out-of-scope over open-ended “platform license” talk until LIVE wedge exists.

---

## Bands

### A. Wedge / diagnostic — **$10k–$15k**

**Fit:** First design partner, one path, decide go / no-go.

**Typical scope:**
- 1 workshop + written evidence gap list (matrix-aligned)
- DEMO environment on their laptop or our Docker
- Pipeline sketch: SFTP|S3 → PGP → CSV → validate → map → archive (destination stub or DEMO Snowflake/Postgres)
- Credential readiness checklist for LIVE (`LIVE_WEDGE.md`)
- One revision of the SOW for the production engagement

**Not included:** Guaranteed LIVE cloud success without their systems; HA; SSO; new connectors.

---

### B. First LIVE pipeline + prove — **$20k–$50k**

**Fit:** CUSTOMER_001-shaped engagement with real credentials.

**Typical scope:**
- Private worker + `FORMULAETL_API_KEY` + Connections/secret refs
- One LIVE wedge E2E with redacted evidence log entry
- Field Mapper / validate / rejects tuned to their schema
- Destination: Postgres **or** Snowflake (if Snowflake volume is non-trivial, include staging+`COPY INTO` as a named deliverable — see `docs/snowflake/BULK_LOAD.md`)
- Handoff: runbooks from `docs/design-partner/`
- Optional: Databricks Job **or** SQL orchestration (control plane only) as an add-on inside this band when workspace access is ready

**Price moves up inside the band when:** PGP key ceremony, multiple file layouts, SFTP + S3 both live, strict change windows, or COPY INTO + partner security review.

**Not included:** Multi-tenant SaaS, enterprise SSO/Vault, Spark runtime inside FormulaETL, unlimited pipelines.

---

### C. Custom / program — **custom (typically $50k+)**

**Fit:** Multiple pipelines, retainer + build, regulated ops, or platform hardening beyond one wedge.

**Examples:**
- Several partner feeds + shared reject/ops standards  
- Monthly automation retainer layered on B  
- Control-plane hardening (Postgres ledger, split workers, backup drills)  
- Snowflake bulk + Databricks orchestration + on-call style support  

Price from discovery; do not invent list prices in email without founder approval.

---

## Alignment with public services one-pager

`SERVICES_OFFER.md` uses overlapping ballparks ($2–5k diagnostic, $8–25k first pipeline, retainer). **This file is the tighter PROVE+SELL internal ladder** for CUSTOMER_001:

| Internal band | Maps to public offer | Push upward when |
|---------------|----------------------|------------------|
| $10–15k | Paid diagnostic + light build | They need a written LIVE plan + demo on their sample files |
| $20–50k | First production pipeline | LIVE proof + secrets + COPY or dual systems |
| Custom | Retainer / multi-pipeline | Program, not a single wedge |

If public and internal conflict in a live quote, **founder decides**; default to the higher band when LIVE credentials and security review are in scope.

---

## Credibility rules (non-negotiable)

1. Never price “proven live Snowflake” unless evidence §C is PROVEN.  
2. Never bundle Stripe, K8s operator, or new connectors into these bands as if shipped.  
3. Separate license talk (Apache 2.0 core remains free) from **services** fees.  
4. Mark DEMO vs LIVE in every proposal appendix.

## Related

- Matrix: [`../CUSTOMER001_EVIDENCE_MATRIX.md`](../CUSTOMER001_EVIDENCE_MATRIX.md)  
- Freeze: [`../PROVE_SELL_FREEZE.md`](../PROVE_SELL_FREEZE.md)  
- Public sketch: [`PRICING_SKETCH.md`](./PRICING_SKETCH.md) · Services: [`SERVICES_OFFER.md`](./SERVICES_OFFER.md)
