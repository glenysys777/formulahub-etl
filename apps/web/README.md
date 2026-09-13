# FormulaHub ETL — Web UI

Vite + React + React Flow designer for **FormulaHub ETL**.

## Local

```bash
npm install
npm run dev      # http://127.0.0.1:18766 (proxies /api → :18765)
npm run build    # → dist/
```

Set `VITE_API_URL` only when talking to a non-default API origin (Docker / hosted). Default is `http://127.0.0.1:18765`.

## Production (Vercel)

- **URL:** https://formulahub-etl.vercel.app  
- **Root:** this directory (`apps/web`)  
- **Config:** `vercel.json` (Vite build → `dist`, SPA rewrite)  

Full stack notes (API hosting, demo mode, custom domain): [docs/deploy.md](../../docs/deploy.md).
