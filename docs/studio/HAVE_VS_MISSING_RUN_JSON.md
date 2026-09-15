# Have vs Missing — Live run counters + JSON write / schema

Founder-facing Soft-PASS notes for Studio (FormulaHub names only).  
Sell sheet: [`docs/sales/FOUNDER_WIN_2027.md`](../sales/FOUNDER_WIN_2027.md).

## Live run feel (records moving)

| Have | Missing / later |
|------|-----------------|
| `GET /api/runs/{id}` returns `node_runs` **while status=running** (worker flushes after each node start/finish) | SSE / WebSocket stream (poll is enough for DEMO Soft-PASS) |
| Studio Run poll (~250ms) updates canvas **rows in → rows out** badges before the run completes | Per-batch counters inside a single long node |
| Active-path edge flow (capped at 8) + reject edges stay pink / distinct | Spark-style distributed stage timelines |
| Last run rail still shows final summary + per-node `in→out` after finish | — |
| DEMO pacing via `FORMULAETL_PROGRESS_TICK_MS` (default **75** in DEMO, **0** when `FORMULAETL_DEMO=0`) | Mandatory artificial delay on LIVE |

**Demo:** Studio → **JSON write demo** (or `?pipeline=demo-api-json-write`) → **Run** → badges tick and edges flow; Last run still lists `node_runs` after finish.

**Gate:** `tests/api/test_softpass_live_json_gates.py::test_demo_run_live_progress_must_update_during_run` **fails** if mid-run `node_runs` never update.

## JSON target schema + Write JSON

| Have | Missing / later |
|------|-----------------|
| **Schema from JSON** — load JSON Schema or sample JSON; exposes fields via Discover / `target_schema` / artifacts | Full nested Schema Map UI for deep JSON Schema `$ref` graphs |
| **Write JSON** — JSON array or JSON Lines; optional pretty; optional nest map (`parent=field1,field2`) | Cloud object-store destinations (out of scope) |
| Palette registration + demo `demos/api-json-write` | Auto-wire Validate columns from Schema from JSON without Discover |
| Soft-PASS fixtures: `fixtures/sample/orders_target_sample.json`, `orders_target_schema.json` | — |
| Schema Validate can fall back to upstream `target_schema` when `columns` empty | — |

**Demo:** **JSON write demo** → Run → inspect `data/out/api_orders.json` (nested `order` / `customer`).

**Gates:** fixture presence + nested write Soft-PASS in `tests/api/test_softpass_live_json_gates.py`.

## DEMO Soft-PASS vs LIVE Soft-PASS

| Label | Meaning here |
|-------|----------------|
| **DEMO Soft-PASS** | Works under `FORMULAETL_DEMO=1` / fixtures; good for founder selling demos. Not customer cloud proof. |
| **LIVE Soft-PASS** | Only claims with redacted evidence + SHA in `docs/PRODUCTION_EVIDENCE.md` (e.g. Databricks Free Edition smokes). |
| **UNPROVEN** | Do not sell as live (full S3/SFTP/Snowflake wedge until partner evidence lands). |

Never claim unproven LIVE. CI green ≠ customer cloud green.

## Soft-PASS evidence

- Mid-run `node_runs` + Write JSON / Schema from JSON Soft-PASS fixtures — `tests/api/test_softpass_live_json_gates.py`
- Palette names — `tests/api/test_palette_components.py`
- Evidence matrix D14 / D15 — `docs/PRODUCTION_EVIDENCE.md`
