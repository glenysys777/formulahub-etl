# Desktop shell + Mac founder pack

Local-path Studio shell: **one clickable icon**, local runner, visible workspace path — browser remains an optional menu item. **No cloud auth in this wave.**

## Status

| Item | State |
|------|--------|
| Electron shell (`apps/desktop`) | **Shipped** |
| Double-click Mac `.app` / `.dmg` | Build **on macOS** (`npm run dist:mac`); pack always includes a clickable launcher `.app` |
| Menu: Open in Browser / Restart API | **Shipped** |
| API disconnect → auto-restart once | **Shipped** |
| Tauri 2 | Deferred |
| Linux CI signed Mac app | **Not claimed** — needs `macos-*` + signing secrets |

## Architecture

```
┌─────────────────────────────┐
│  FormulaHub Studio.app      │
│  ┌─────────┐  ┌──────────┐  │
│  │ Studio  │  │ Local    │  │
│  │ window  │──│ API +    │  │
│  │(Electron)│ │ runner   │  │
│  └─────────┘  └──────────┘  │
│         work_dir on disk     │
└─────────────────────────────┘
```

- Shell **spawns** `uvicorn formulaetl_api.main:app` on `127.0.0.1:18765` when `/health` is down; otherwise **reuses** an existing API.
- Serves built Studio (`apps/web/dist`) on `127.0.0.1:18766` inside the app (Vite OK in `--dev`).
- **Studio → Open in Browser** opens the same URL in a browser (optional, not primary).
- **Studio → Restart API** respawns the owned API; if the API dies, the shell **auto-restarts once** and shows a reconnect screen.
- Quit → best-effort `SIGTERM` on an API process **this shell started**.

## Founder Mac pack (unzip → double-click)

```bash
make mac-pack
# → data/out/mac-pack/FormulaHub-ETL-Mac.zip
```

After unzip:

| Item | Role |
|------|------|
| **FormulaHub Studio.app** | Primary — double-click icon |
| `README_MAC.md` | Short: unzip → double-click |
| `START-NATIVE.command` | Terminal fallback (ports can drop if Terminal closes) |
| `FormulaHub-ETL/` | Sources for `make install` / Docker |

On a Mac with Node + Python already set up from a prior `make install && make build`, the launcher starts Electron with no Terminal window. First-time packs may prompt once for setup.

Optional: embed a real electron-builder `.app` when building the pack on macOS:

```bash
MAC_PACK_BUILD_ELECTRON=1 make mac-pack
```

## Quick start (from repo)

```bash
make install && make seed && make build
make desktop
```

## Build on Mac → open Studio.app

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
2. App starts the local API if needed.
3. Studio loads in the **desktop window**; status bar shows workspace path.
4. Optional: **Studio → Open in Browser**.
5. Quit → owned API stops (best-effort).

| Variable | Purpose |
|----------|---------|
| `FORMULAETL_WORK_DIR` / `FORMULAETL_HOME` | Workspace root |
| `FORMULAETL_PYTHON` | Python binary (default `python3`) |
| `FORMULAETL_API_PORT` | Default `18765` |
| `FORMULAETL_UI_PORT` | Default `18766` |

## CI

- Linux: `apps/desktop` **lint / build:check** + API spawn smoke. Does **not** emit `.dmg`.
- Optional future: `runs-on: macos-14` + `npm run dist:mac`.

## Out of scope

- New connectors
- Cloud HA scheduler / cloud auth
- Relabeling Field Mapper / Lookup Join
- Competitor brand names in UI
