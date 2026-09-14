# Desktop shell plan (next wave)

**Not blocking** the Finished Product Studio polish PR. Same UI + local API; wrap for a first-class desktop feel.

## Goal

Ship a FormulaHub ETL **desktop app** that feels like a local Studio: one icon, local runner, visible workspace path — not a hosted SaaS tab.

## Approach (choose one in next wave)

| Option | Pros | Cons |
|--------|------|------|
| **Electron** | Fast to wrap Vite UI; mature | Heavier binary; Chromium ship size |
| **Tauri 2** | Small binary; Rust sidecar friendly | Slightly more packaging work |

Recommendation: **Tauri** if packaging bandwidth allows; **Electron** if we need the shell in days.

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

- Embed or spawn `formulaetl_api` + runner against a user-chosen **work_dir**
- Point WebView at `http://127.0.0.1:<port>` (same as today’s Studio)
- Surface `work_dir` in the status bar (already in Studio polish)
- Deep link: open pipeline JSON from Finder / Explorer

## Out of scope for shell wave

- New connectors
- Cloud HA scheduler
- Relabeling Field Mapper / Lookup Join

## Acceptance sketch

1. Double-click app → Studio loads with API healthy
2. Status bar shows workspace path on this machine
3. Run demo pipeline without opening a separate terminal
4. Quit stops embedded API cleanly
