# FormulaHub Studio — desktop shell

Electron shell that starts the local FormulaHub ETL API (if needed) and loads Studio in a native window.

**Why Electron (not Tauri) for this wave:** fastest path to a double-clickable shell on Mac while the cloud agent runs on Linux. Tauri 2 remains a future option; Mac `.dmg` still requires a **macOS** runner either way.

## Prerequisites

- Node.js 20+
- Python 3.11+ with FormulaHub packages installed (`make install` from repo root)
- Built Studio web UI (`cd apps/web && npm ci && npm run build`)

## Run from repo (any OS with Electron)

```bash
# from repo root
make install
make seed
make build          # apps/web → dist
make desktop        # opens FormulaHub Studio window
```

Or:

```bash
cd apps/desktop && npm install && npm start
```

Dev (reuse Vite if already on :18766):

```bash
make api &          # optional — shell will start API if missing
make web &
cd apps/desktop && npm run dev
```

## Build on Mac → open Studio.app

On a **macOS** machine (Apple Silicon or Intel):

```bash
# 1. Clone / open the FormulaHub ETL repo
cd formulahub-etl
make install && make seed
make build

# 2. Install desktop deps and package
cd apps/desktop
npm install
npm run dist:mac    # unsigned .app + .dmg under apps/desktop/release/
```

Then:

1. Open `apps/desktop/release/mac*/FormulaHub Studio.app` (or install from the `.dmg`).
2. First launch: Gatekeeper may block unsigned builds — **Right-click → Open** (or `xattr -cr` the app). Signed notarized builds are a later wave.
3. Double-click → shell starts API on `127.0.0.1:18765` if needed → Studio loads → status bar shows `workspace on this machine · {work_dir}`.
4. Quit the app → owned API process is stopped (best-effort SIGTERM).

Set workspace explicitly:

```bash
export FORMULAETL_WORK_DIR=/path/to/formulahub-etl
open "FormulaHub Studio.app"
```

Packaged apps look for the repo at `~/FormulaHub-ETL` or `FORMULAETL_HOME` / `FORMULAETL_WORK_DIR` so Python packages and `data/` stay on disk (local-path primary; no cloud auth in this wave).

## What the shell does / does not

| Does | Does not |
|------|----------|
| Spawn/reuse local API + embedded worker | Cloud login / SSO |
| Load Studio WebView at 127.0.0.1 | New connectors |
| Show `work_dir` via Studio status bar (`/health`) | Claim Linux CI produces signed Mac apps |
| Quit → stop API it started | Replace browser fallback |

Browser fallback remains: `make api` + `make web`.

## CI note

Linux CI runs `npm run build:check` (syntax + structure). **`.dmg` / `.app` require `runs-on: macos-*`** — see `.github/workflows/ci.yml` comments and `docs/studio/DESKTOP_SHELL.md`.
