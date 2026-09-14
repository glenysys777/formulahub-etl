# Production evidence log

Claims in sales/README are **not** evidence. Each row is a statement we are willing to make only with a command, git SHA, and date.

**Audit SHA (main / Phase A merge):** `cecb1af` (PR #4)  
**Phase B merge tip:** `f2d8b57`  
**Phase C merge tip:** `dce51a6`  
**Phase D+E merge tip:** `1b82aa5`  
**Phase F merge tip:** `3d1d9c9`  
**Phase G branch tip:** this PR  
**Agent run date:** 2026-09-14  
**Python:** 3.12.3 · **Node:** 22.x · **pytest:** 9.x

Fill status: `PROVEN` | `UNPROVEN` | `FAILED` | `EMPTY`

---

## A. Build and tests

| ID | Claim | Status | Command | Result | SHA | Date |
|----|-------|--------|---------|--------|-----|------|
| A1 | Pytest suite on `tests/` | PROVEN | `python3 scripts/seed_demo.py && python3 -m pytest tests -q -m "not live"` | **158 passed**, 1 skipped (`RUN_CSV_1M`), 1 deselected (`live`). Includes Phase G validate + live-harness unit tests. `FORMULAETL_DEMO=1`. Not live AWS/SFTP. | this PR | 2026-09-14 |
| A2 | Web production build | PROVEN | `cd apps/web && npm run build` | Optional CI job `web-build` | this PR | 2026-09-14 |
| A3 | GitHub Actions CI on `main` / PRs | PROVEN | `.github/workflows/ci.yml` | pytest + DEMO=1; optional npm build. **No live cloud checks.** | this PR | 2026-09-14 |
| A4 | Default env is demo | PROVEN | Read `tests/conftest.py` | Tests force `FORMULAETL_DEMO=1` | `cecb1af` | 2026-09-14 |
| A5 | CSV 10K streaming benchmark | PROVEN | Phase C | Unchanged | `dce51a6` | 2026-09-14 |

---

## B. Demo runs (fixtures, not customer systems)

| ID | Claim | Status | Command | Result | SHA | Date |
|----|-------|--------|---------|--------|-----|------|
| B1 | Flagship S3→PGP→Snowflake **demo** CLI | PROVEN **demo only** | `FORMULAETL_DEMO=1 python3 -m formulaetl.cli run demos/s3-pgp-snowflake/pipeline.json` | Inline demo hosts still work. | `3d1d9c9` | 2026-09-14 |
| B1b | Excel + API-map demos | PROVEN **demo only** | CLI / pytest | Unchanged | `1b82aa5` | 2026-09-14 |
| B2–B4 | Other demos / screenshots | PROVEN **demo only** | pytest / CLI | Unchanged intent | `dce51a6` | 2026-09-14 |

---

## C. Live systems (customer-shaped) — classification **LIVE_CLOUD**

| ID | Claim | Status | Command | Result | SHA | Date |
|----|-------|--------|---------|--------|-----|------|
| C0 | Live wedge harness exists (S3\|SFTP→PGP→CSV→validate→map→PG\|SF→archive) | PROVEN **harness only** | `python3 scripts/live_wedge_e2e.py --check` + unit tests | Gate skips without creds; CI uses `-m "not live"`. Does **not** prove cloud connectivity. | this PR | 2026-09-14 |
| C1 | Live AWS S3 read in wedge | UNPROVEN | `RUN_LIVE_WEDGE=1 FORMULAETL_DEMO=0` + `LIVE_S3_*` / AWS creds | Not run in this agent / CI | — | — |
| C2 | Live SFTP read in wedge | UNPROVEN | `LIVE_SOURCE=sftp` + `LIVE_SFTP_*` | Not run | — | — |
| C3 | Live PGP decrypt with partner key | UNPROVEN | `LIVE_PGP_PRIVATE_KEY_PATH` | Not run | — | — |
| C4 | Live Postgres load in wedge | UNPROVEN | `LIVE_DEST=postgres` + `LIVE_POSTGRES_*` | Not run | — | — |
| C5 | Live Snowflake load in wedge | UNPROVEN | `LIVE_DEST=snowflake` + `LIVE_SNOWFLAKE_*` | Not run | — | — |
| C6 | Full live wedge E2E (source→archive) | UNPROVEN | `docs/design-partner/LIVE_WEDGE.md` | **Do not mark PROVEN** until a real run’s JSON (redacted) is pasted here with SHA + date | — | — |

CI never sets `RUN_LIVE_WEDGE`. Green Actions ≠ LIVE_CLOUD PROVEN.

---

## D. Architecture facts (code, not a passing test)

| ID | Claim | Status | Evidence | SHA | Date |
|----|-------|--------|----------|-----|------|
| D1 | Runner DAG still sequential **inside** a worker | PROVEN | `PipelineRunner.run` topological loop | `1b82aa5` | 2026-09-14 |
| D2–D4 | ArtifactHandle / RowBatch / CSV chunking | PROVEN | Phase B/C | `dce51a6` | 2026-09-14 |
| D5 | Run history is durable SQLite | PROVEN | Phase D+E | `1b82aa5` | 2026-09-14 |
| D6 | Optional API key when `FORMULAETL_API_KEY` set | PROVEN | Phase F | `3d1d9c9` | 2026-09-14 |
| D7 | Secrets via SecretProvider refs | PROVEN | Phase F | `3d1d9c9` | 2026-09-14 |
| D8–D9 | SFTP host-key reject / S3 pagination | PROVEN | Phase C | `dce51a6` | 2026-09-14 |
| D10–D12 | Async 202 / concurrent workers / version pin | PROVEN | Phase D+E | `1b82aa5` | 2026-09-14 |
| D13 | GET run exposes summary + node_runs + events | PROVEN | Phase G `get_run` + tests | this PR | 2026-09-14 |

---

## E–G. Historical phases

Phase B `f2d8b57` · Phase C `dce51a6` · Phase D+E `1b82aa5` · Phase F `3d1d9c9` — see prior sections in git history.

---

## H. Phase F — Connections + Secret refs

Merged on main as `3d1d9c9`. See prior H1–H8 claims (connections CRUD, test, SecretProvider, mask, API key, CONNECTIONS.md).

---

## I. Phase G — Validate + design-partner docs + CI (this PR)

| ID | Claim | Status | Evidence |
|----|-------|--------|----------|
| I1 | `POST /api/pipelines/{id}/validate` structured checks | PROVEN | `formulaetl_api/validate.py` + `tests/api/test_validate.py` — graph/cycle, required params, connection_id, secret refs (no values), column_map/tmap mappings; ✓/⚠/✗ + codes |
| I2 | Optional body validates unsaved canvas | PROVEN | Validate accepts nodes/edges without requiring prior PUT |
| I3 | GET run `summary` + clear node_runs/events | PROVEN | `summary.{rows_*,duration_ms,nodes_*,event_count}`; UI Last run shows node table |
| I4 | Design-partner docs pack | PROVEN | `docs/design-partner/{DEPLOYMENT,SECURITY,CONNECTIONS,BACKUP,TROUBLESHOOTING,PRODUCTION_CHECKLIST}.md` — DEMO vs live honesty |
| I5 | GitHub Actions CI | PROVEN | `.github/workflows/ci.yml` — pytest DEMO=1 `-m "not live"` + npm build; no fake live cloud |
| I6 | UI Validate button | PROVEN | `apps/web` topbar → validate API |
| I7 | LIVE_CLOUD wedge harness (opt-in) | PROVEN **harness** / UNPROVEN **cloud** | `scripts/live_wedge_e2e.py`, `tests/live/`, `docs/design-partner/LIVE_WEDGE.md`; see section C |

### Remaining gaps (honest)

- Live connector E2E still **UNPROVEN** (harness only — section C).
- Validate ≠ live connectivity (use connection test + live wedge + partner checklist).
- Not SSO/Vault/Spark/billing/Talend importer/new connectors.
- Overall live-connector readiness remains **DEMO** until partner proofs.

---

## Notes

- Readiness: validate + CI move **trust/ops** toward design-partner; live connectors stay DEMO until external evidence.
- See `docs/design-partner/` for operational pack.
- CLI `formulaetl run` resolves env secret refs; ConnectionStore requires the API/DB path.
- Pytest **count** for Phase G: **154 passed**, 1 skipped (Phase F was 146; Phase D+E was 133).
