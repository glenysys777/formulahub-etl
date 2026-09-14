# Production evidence log

Claims in sales/README are **not** evidence. Each row is a statement we are willing to make only with a command, git SHA, and date.

**Audit SHA (main / Phase A merge):** `cecb1af` (PR #4)  
**Phase B merge tip:** `f2d8b57`  
**Phase C merge tip:** `dce51a6`  
**Phase D+E merge tip:** `1b82aa5`  
**Phase F branch tip:** this PR (`8efe72c` + docs tip)  
**Agent run date:** 2026-09-14  
**Python:** 3.12.3 · **Node:** 22.14.0 · **pytest:** 9.1.1

Fill status: `PROVEN` | `UNPROVEN` | `FAILED` | `EMPTY`

---

## A. Build and tests

| ID | Claim | Status | Command | Result | SHA | Date |
|----|-------|--------|---------|--------|-----|------|
| A1 | Pytest suite on `tests/` | PROVEN | `python3 scripts/seed_demo.py && python3 -m pytest tests -q` | **146 passed**, 1 skipped (`RUN_CSV_1M`), warnings (pgpy). Includes Phase F connections/secrets tests (+13). `FORMULAETL_DEMO=1` via conftest. Not live AWS/SFTP. | this PR | 2026-09-14 |
| A2 | Web production build | PROVEN | Phase D+E | Unchanged intent (no UI redesign this phase) | `1b82aa5` | 2026-09-14 |
| A3 | GitHub Actions CI on `main` | PROVEN **absent** | `ls .github/workflows` | Still no workflow files | `cecb1af` | 2026-09-14 |
| A4 | Default env is demo | PROVEN | Read `tests/conftest.py` | Tests force `FORMULAETL_DEMO=1` | `cecb1af` | 2026-09-14 |
| A5 | CSV 10K streaming benchmark | PROVEN | Phase C | Unchanged | `dce51a6` | 2026-09-14 |

---

## B. Demo runs (fixtures, not customer systems)

| ID | Claim | Status | Command | Result | SHA | Date |
|----|-------|--------|---------|--------|-----|------|
| B1 | Flagship S3→PGP→Snowflake **demo** CLI | PROVEN **demo only** | `FORMULAETL_DEMO=1 python3 -m formulaetl.cli run demos/s3-pgp-snowflake/pipeline.json` | Inline demo hosts still work (no connection_id required). | this PR | 2026-09-14 |
| B1b | Excel + API-map demos | PROVEN **demo only** | CLI | Unchanged | `1b82aa5` | 2026-09-14 |
| B2–B4 | Other demos / screenshots | PROVEN **demo only** | pytest / CLI | Unchanged intent | `dce51a6` | 2026-09-14 |

---

## C. Live systems (customer-shaped)

Unchanged — all **UNPROVEN**.

---

## D. Architecture facts (code, not a passing test)

| ID | Claim | Status | Evidence | SHA | Date |
|----|-------|--------|----------|-----|------|
| D1 | Runner DAG still sequential **inside** a worker | PROVEN | `PipelineRunner.run` topological loop | `1b82aa5` | 2026-09-14 |
| D2–D4 | ArtifactHandle / RowBatch / CSV chunking | PROVEN | Phase B/C | `dce51a6` | 2026-09-14 |
| D5 | Run history is durable SQLite | PROVEN | Phase D+E | `1b82aa5` | 2026-09-14 |
| D6 | Optional API key when `FORMULAETL_API_KEY` set | PROVEN | Middleware + `tests/api/test_connections.py`; Community open when unset; `/health` → `auth: none\|api_key` | this PR | 2026-09-14 |
| D7 | Secrets via SecretProvider refs (not only inline JSON) | PROVEN | Connections store + env/`secret:` refs; GET masks; demos may still use empty inline passwords | this PR | 2026-09-14 |
| D8–D9 | SFTP host-key reject / S3 pagination | PROVEN | Phase C | `dce51a6` | 2026-09-14 |
| D10–D12 | Async 202 / concurrent workers / version pin | PROVEN | Phase D+E | `1b82aa5` | 2026-09-14 |

---

## E–G. Historical phases

Phase B `f2d8b57` · Phase C `dce51a6` · Phase D+E `1b82aa5` — see prior sections in git history.

---

## H. Phase F — Connections + Secret refs (this PR)

| ID | Claim | Status | Evidence |
|----|-------|--------|----------|
| H1 | Connection CRUD (sftp/s3/snowflake/postgres/http) | PROVEN | `POST/GET/PUT/DELETE /api/connections` + kinds |
| H2 | Test Connection (demo path) | PROVEN | `POST /api/connections/{id}/test` → `mode=demo` under DEMO=1 |
| H3 | SecretProvider env + encrypted local store | PROVEN | `formulaetl.sdk.secrets` + SQLite `secrets` table; Fernet |
| H4 | Nodes resolve `connection_id` at runtime | PROVEN | `PipelineRunner` + `resolve_node_config`; worker wired |
| H5 | GET masks secrets (connections + pipelines) | PROVEN | `to_public_dict` / `_mask_pipeline_dict`; tests assert no plaintext leak |
| H6 | Optional `FORMULAETL_API_KEY` gate | PROVEN | Open when unset; 401 without header when set |
| H7 | Inline DEMO demos still run | PROVEN | `demo-s3-pgp-snowflake` run via API without connections |
| H8 | Docs: convert node → connection_id | PROVEN | `docs/CONNECTIONS.md` |

### Remaining gaps (honest)

- Not SSO/RBAC, not HashiCorp Vault / cloud KMS, not multi-tenant.
- Live connector E2E still **UNPROVEN** in CI.
- Worker may still be embedded; design-partner should prefer private worker + API key.
- Pipeline versions created **before** Phase F may still contain inline secrets if the author put them there — migrate with `connection_id` (see CONNECTIONS.md).
- Not Spark, not K8s, not billing, no new connectors.

---

## Notes

- Readiness: connections + secret refs + optional API key move **secrets/auth** from ABSENT toward **ALPHA** (Community local). Overall product for Customer #1 live connectors remains **DEMO** until live proofs.
- See `docs/CONNECTIONS.md` for create-connection + migration steps.
- CLI `formulaetl run` resolves env secret refs; ConnectionStore requires the API/DB path.
- Pytest **count** for Phase F: **146 passed**, 1 skipped (Phase D+E was 133; Phase C was 127).
