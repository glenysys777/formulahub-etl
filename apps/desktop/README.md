# FormulaHub Studio — desktop shell

Electron shell that starts the local FormulaHub ETL API (if needed) and loads Studio in a **native window**. Browser is optional (**Studio → Open in Browser**).

## Prerequisites

- Node.js 20+
- Python 3.11+ with FormulaHub packages installed (`make install` from repo root)
- Built Studio web UI (`make build`)

## Run from repo

```bash
make install && make seed && make build
make desktop
```

Dev (reuse Vite if already on :18766):

```bash
make api &
make web &
cd apps/desktop && npm run dev
```

## Build on Mac → FormulaHub Studio.app

```bash
make install && make seed && make build
cd apps/desktop && npm install && npm run dist:mac
open release/mac*/FormulaHub\ Studio.app
```

Unsigned Gatekeeper: Right-click → **Open**.

### What happens on double-click

1. Starts (or reuses) API on `127.0.0.1:18765` — no Terminal required
2. Serves Studio UI and loads it in the Electron window
3. Status bar shows `workspace on this machine · {work_dir}`
4. If the API dies: auto-restart **once**, then prompt to use **Studio → Restart API**
5. Quit stops an API this shell started

### Menu

| Item | Action |
|------|--------|
| Studio → Open in Browser | Optional browser at `http://127.0.0.1:18766` |
| Studio → Restart API | Stop owned API + spawn again |
| Studio → API health… | Show `/health` JSON |

## Mac pack

```bash
make mac-pack
# → data/out/mac-pack/FormulaHub-ETL-Mac.zip
```

Unzip → double-click **FormulaHub Studio.app**. `START-NATIVE.command` is a Terminal fallback only.

See `docs/studio/DESKTOP_SHELL.md`.

## CI note

Linux CI runs `npm run build:check` + `smoke:api`. **`.dmg` / signed `.app` require macOS** — see workflow comments.
