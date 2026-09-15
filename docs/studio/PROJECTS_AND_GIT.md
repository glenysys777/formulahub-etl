# Projects, Save to disk, and Git

Community Studio persists pipelines in two places:

1. **SQLite control plane** (`data/formulaetl.db` by default) — versions, runs, schedules.
2. **Mirror JSON files** — `{work_dir}/pipelines/{pipeline_id}.json` written on every create / update / Save.

**Workspace folders** (`metadata.workspace_folder` + `{work_dir}/data/workspace.json`) organize pipelines in the Studio left tree — see `WORKSPACE.md`.

The status bar shows `workspace on this machine · {work_dir}` so you can find the folder on disk.

## Save from Studio

- Use **Save** in the header (or rely on auto-persist while editing).
- After save, Studio reports: `Saved to …/pipelines/{id}.json`.
- SQLite remains the live Studio source of truth; the JSON mirror is for Git, backup, and hand-off.

## Export / run elsewhere

- **Export JSON** — downloads the pipeline graph (`Content-Disposition` attachment).
- **Export zip** — same JSON plus a short `README.md` (via `GET /api/pipelines/{id}/export?format=zip`).
- **Import** — `POST /api/pipelines/import` with the JSON body (or paste into a new workspace’s `pipelines/` folder and open by id after restart / list refresh).

Secrets should be Connection / env refs, not literals. Reconnect on the target machine.

## Git (Community)

FormulaHub does **not** require GitHub OAuth for Community. Treat `work_dir` as a normal folder:

```bash
cd /path/to/your/work_dir
git init                    # once
git add pipelines/<id>.json
git commit -m "Save pipeline <name>"
# optional remote
git remote add origin git@github.com:you/your-etl-projects.git
git push -u origin main
```

Studio can **Copy git commands** for the current pipeline (cwd = `work_dir`). Open the folder in your file manager / IDE to browse `pipelines/`.

Pull on another machine:

```bash
cd /path/to/work_dir
git pull
# then Import JSON or ensure the API work_dir points here and open the pipeline
```

## Pro (later — not in this build)

One-click remote push/pull and hosted project sync are planned for **Pro**. This Community build stops at Save to disk + Export + copy-paste Git commands + docs — no OAuth.

## API cheat sheet

| Action | Endpoint |
|--------|----------|
| Save (also mirrors JSON) | `PUT /api/pipelines/{id}` / `POST /api/pipelines` |
| Export JSON | `GET /api/pipelines/{id}/export` |
| Export zip + README | `GET /api/pipelines/{id}/export?format=zip` |
| Import | `POST /api/pipelines/import` |

See also `FINISHED_PRODUCT.md` (component matrix) and `DESKTOP_SHELL.md` (future local shell).
