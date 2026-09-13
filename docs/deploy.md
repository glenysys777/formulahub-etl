# Hosting FormulaHub ETL

Product brand: **FormulaHub ETL**. Marketing site: [formulahub.io/etl](https://formulahub.io/etl) (separate repo). This repo is the OSS visual ETL app.

## Production UI (Vercel)

| | |
|---|---|
| **Live UI** | https://formulahub-etl.vercel.app |
| **Project** | `formulahub-etl` on team MYNQ (`glenysys777s-projects`) |
| **Project ID** | `prj_NpC95o7qIgzkfd0r8ZIGzpYgNRXs` |
| **Root Directory** | `apps/web` |
| **Build** | `npm run build` → `dist` |
| **SPA** | `apps/web/vercel.json` rewrites → `index.html` |

The hosted UI is the Vite + React Flow designer only. Pipeline **runs, AI builder, schema discover, and demos** need the FastAPI backend (`packages/api` + `packages/runner`). Without an API, the footer shows `api offline` and the UI still defaults to `http://127.0.0.1:18765` (`VITE_API_URL` unset).

Demo honesty: local/Docker API uses `FORMULAETL_DEMO=1` (mock S3 / Snowflake). That env is for the API/runner — not the static Vercel site.

### Optional custom domain

Point `etl.formulahub.io` at Vercel (do not buy domains here):

1. In Vercel → Project → Domains → add `etl.formulahub.io`
2. DNS: `CNAME etl` → `cname.vercel-dns.com` (or the target Vercel shows)

## API / runner (not on Vercel static)

FastAPI + the Python DAG runner are long-running processes with a work dir (`data/`, `fixtures/`, `demos/`). Prefer hosting them next to Docker:

| Option | Notes |
|--------|--------|
| **Docker Compose** (local / VM) | `make docker-up` — API `:18765`, UI `:18766` |
| **Railway / Render / Fly.io** | Deploy `packages/api/Dockerfile` with `FORMULAETL_DEMO=1`, mount or bake `demos/`, `fixtures/`, `data/` |
| **Any container host** | Same image; set `FORMULAETL_WORK_DIR` |

There is **no** Vercel serverless Python bridge in this repo. Do not treat the static UI deploy as a full hosted ETL runtime.

After the API is public, set Vercel env `VITE_API_URL` to that origin and redeploy `apps/web` (Vite inlines it at build time). Enable CORS on the API for the Vercel origin.
