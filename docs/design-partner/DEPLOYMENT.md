# Deployment (design partner)

**Audience:** first customer / design partner operating FormulaHub ETL themselves.  
**Honesty:** default `FORMULAETL_DEMO=1` is **DEMO** (fixtures, mock hosts). Live connectors are **UNPROVEN in CI**.

## What you are deploying

| Piece | Role | Notes |
|-------|------|--------|
| `packages/api` | Control plane (CRUD, queue, validate, connections) | FastAPI |
| `packages/runner` | Data plane (DAG execution inside a worker) | In-process batches — laptop-sized |
| `apps/web` | Visual designer | Static Vite build; does **not** run jobs |
| SQLite `data/formulaetl.db` | Pipelines, versions, runs, node_runs, events, connections, secrets | Local file; not HA |

Vercel UI ([formulahub-etl.vercel.app](https://formulahub-etl.vercel.app)) is designer-only. Runs need an API + worker next to your data. See also `docs/deploy.md` and `docs/architecture/CONTROL_DATA_PLANE.md`.

## Minimal local stack

```bash
make install
make seed
make api          # :18765 — embeds worker when FORMULAETL_EMBEDDED_WORKER=1 (default)
make web          # :18766
```

Health:

```bash
curl -s http://127.0.0.1:18765/health | jq .
# expect: demo_mode, auth, run_store=sqlite, readiness_level
```

## Partner-shaped (recommended)

1. Set **`FORMULAETL_API_KEY`** and send `X-API-Key` (or Bearer) on all `/api/*` calls.
2. Set **`FORMULAETL_EMBEDDED_WORKER=0`** on the API process; run **`make worker`** (or compose worker service) next to data / credentials.
3. Prefer **`connection_id`** + secret refs over inline passwords (`docs/CONNECTIONS.md` / `docs/design-partner/CONNECTIONS.md`).
4. Keep **`FORMULAETL_DEMO=0`** only when pointing at real systems you control — then prove live paths yourself (not covered by GitHub Actions).

```bash
export FORMULAETL_API_KEY=...
export FORMULAETL_DEMO=0
export FORMULAETL_EMBEDDED_WORKER=0
export FORMULAETL_SECRETS_KEY=...   # or let the process create data/.formulaetl_secrets_key
make api &
make worker
```

Docker Compose: `make docker-up` — still DEMO-oriented unless you override env.

## Preflight before a partner run

```bash
# Validate graph + params + refs (no execution)
curl -s -X POST http://127.0.0.1:18765/api/pipelines/<id>/validate \
  -H "Content-Type: application/json" -H "X-API-Key: $FORMULAETL_API_KEY" \
  -d '{}' | jq .

# Then enqueue
curl -s -X POST http://127.0.0.1:18765/api/pipelines/<id>/run \
  -H "X-API-Key: $FORMULAETL_API_KEY" | jq .
# → 202 { run_id, status: queued }

# Inspect node_runs / events / summary
curl -s http://127.0.0.1:18765/api/runs/<run_id> -H "X-API-Key: $FORMULAETL_API_KEY" | jq '.summary, .node_runs, .events'
```

## What is not in this pack

- No Kubernetes operator, no Spark runtime, no billing, no SSO/RBAC, no HashiCorp Vault.
- No fake “live cloud green” in CI — see `docs/design-partner/TROUBLESHOOTING.md` and PRODUCTION_CHECKLIST.
