# Have vs Missing — Live run counters + JSON write / schema

Founder-facing Soft-PASS notes for Studio (FormulaHub names only).

## Live run feel (records moving)

| Have | Missing / later |
|------|-----------------|
| `GET /api/runs/{id}` returns `node_runs` **while status=running** (worker flushes after each node start/finish) | SSE / WebSocket stream (poll is enough for DEMO Soft-PASS) |
| Studio Run poll (~250ms) updates canvas **rows in → rows out** badges before the run completes | Per-batch counters inside a single long node |
| Active-path edge flow (capped at 8) + reject edges stay pink / distinct | Spark-style distributed stage timelines |
| Last run rail still shows final summary + per-node `in→out` after finish | — |
| DEMO pacing via `FORMULAETL_PROGRESS_TICK_MS` (default **75** in DEMO, **0** when `FORMULAETL_DEMO=0`) | Mandatory artificial delay on LIVE |

**Demo:** open any demo pipeline → **Run** → watch node badges tick and spine edges flow; when finished, Last run still lists node_runs.

## JSON target schema + Write JSON

| Have | Missing / later |
|------|-----------------|
| **Schema from JSON** — load JSON Schema or sample JSON; exposes fields via Discover / `target_schema` / artifacts | Full nested Schema Map UI for deep JSON Schema `$ref` graphs |
| **Write JSON** — JSON array or JSON Lines; optional pretty; optional nest map (`parent=field1,field2`) | Cloud object-store destinations (out of scope) |
| Palette registration + demo `demos/api-json-write` | Auto-wire Validate columns from Schema from JSON without Discover |
| Schema Validate can fall back to upstream `target_schema` when `columns` empty | — |

**Demo:** load **API → Map → Schema from JSON → Write JSON** → Run → inspect `data/out/api_orders.json` (nested `order` / `customer`).

## Soft-PASS evidence

- API: mid-run `node_runs` + palette types `write_json` / `schema_from_json` — see `tests/api/test_live_progress_json.py`, `tests/api/test_palette_components.py`.
- Integration: demo pipeline writes nested JSON — Soft-PASS under `FORMULAETL_DEMO=1`.
