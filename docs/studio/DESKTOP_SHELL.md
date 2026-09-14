# Desktop shell plan + Mac build guide

Local-path Studio shell: one icon, local runner, visible workspace path — browser remains the fallback. **No cloud auth in this wave.**

## Status

| Item | State |
|------|--------|
| Electron shell (`apps/desktop`) | **Shipped** (this wave) |
| Double-click Mac `.app` / `.dmg` | Build **on macOS** (unsigned OK for founder) |
| Tauri 2 | Deferred — revisit if binary size becomes a priority |
| Linux CI signed Mac app | **Not claimed** — needs `macos-*` runner + signing secrets |

## Architecture

```
┌─────────────────────────────┐
│  Desktop shell (.app / exe) │
│  ┌─────────┐  ┌──────────┐  │
│  │ Studio  │  │ Local    │  │
│  │ (Vite)  │──│ API+     │  │
│  │ WebView │  │ runner   │  │
│  └─────────┘  └──────────┘  │
│         work_dir on disk     │
└─────────────────────────────┘
```

- Shell **spawns** `uvicorn formulaetl_api.main:app` on `127.0.0.1:18765` when `/health` is down; otherwise **reuses** an existing API.
- Serves built Studio (`apps/web/dist`) on `127.0.0.1:18766` inside the app.
- Studio status bar already shows `workspace on this machine · {work_dir}` from `GET /health`.
- Quit → best-effort `SIGTERM` on an API process **this shell started** (does not kill a pre-existing `make api`).

Preserved Studio UX (unchanged): Field Mapper, Job Contexts, sidebar collapse, type-to-place.

## Quick start (from repo)

```bash
make install && make seed && make build
make desktop
```

## Build on Mac → open Studio.app

On a Mac (required for `.app` / `.dmg`; Linux agents cannot produce a signed Mac app):

```bash
cd formulahub-etl
make install && make seed && make build

cd apps/desktop
npm install
npm run dist:mac
# → apps/desktop/release/mac*/FormulaHub Studio.app
# → apps/desktop/release/FormulaHub-Studio-*-*.dmg
```

**Double-click flow**

1. Open **FormulaHub Studio.app** (Right-click → Open if Gatekeeper blocks unsigned builds).
2. App starts the local API if needed (`FORMULAETL_DEMO=1`, `FORMULAETL_WORK_DIR` → repo / `~/FormulaHub-ETL`).
3. Studio WebView loads; footer/status shows workspace path on this machine.
4. Run a demo pipeline with no separate terminal.
5. Quit the app → owned API stops cleanly (best-effort).

Optional env:

| Variable | Purpose |
|----------|---------|
| `FORMULAETL_WORK_DIR` / `FORMULAETL_HOME` | Workspace root (pipelines, `data/`, packages) |
| `FORMULAETL_PYTHON` | Python binary (default `python3`) |
| `FORMULAETL_API_PORT` | Default `18765` |

## Docker Mac pack

One-command zip for handoff (Docker + desktop sources, no `node_modules`):

```bash
make mac-pack
# → data/out/mac-pack/FormulaHub-ETL-Mac.zip
```

See `START_HERE_MAC.md` inside the zip.

## CI

- Linux: `apps/desktop` **lint / build:check** only (syntax + structure). Does **not** emit `.dmg`.
- Optional future job: `runs-on: macos-14` + `npm run dist:mac` for unsigned artifacts. Signing/notarization needs Apple secrets — out of scope here.

## Out of scope

- New connectors
- Cloud HA scheduler / cloud auth
- Relabeling Field Mapper / Lookup Join
- Competitor brand names in UI
