# Studio Workspace

Folder tree for pipelines in FormulaHub Studio (Desktop and web).  
Product labels: **Workspace**, **Pipelines**, **Masters**, **Reusable** (Child pipelines).

## What you see

The left rail shows a collapsible Workspace tree above the component palette:

| Folder | Purpose |
|--------|---------|
| `Pipelines/Demos` | Bundled demo pipelines |
| `Pipelines/My pipelines` | Default home for blank / new pipelines |
| `Masters` | Master pipelines that call children via **Run Pipeline** |
| `Reusable` | Child / reusable pipelines invoked from Masters |

- Click a pipeline → loads it on the canvas (`GET /api/pipelines/{id}`).
- **New** (Workspace) or **New blank** (top bar) creates a blank pipeline in the **selected** folder (or My pipelines).
- The open pipeline is highlighted in the tree.
- **Move to…** (hover) reassigns a pipeline to another folder.
- **File → Open from Workspace** focuses the tree.

## Persistence

1. **Pipeline metadata** — `metadata.workspace_folder` (string path, e.g. `Pipelines/Demos`).  
   Survives Save, versions, and mirror JSON under `{work_dir}/pipelines/{id}.json`.
2. **Workspace index** — `{work_dir}/data/workspace.json`:

```json
{
  "folders": [
    "Pipelines/Demos",
    "Pipelines/My pipelines",
    "Masters",
    "Reusable"
  ],
  "pipelineFolders": {
    "demo-lookup-join-mapper": "Pipelines/Demos"
  }
}
```

API:

- `GET /api/workspace` — folders + map (seeds defaults; syncs from pipeline metadata)
- `PUT /api/workspace` — replace folder list / index
- `POST /api/workspace/move` — `{ "pipeline_id", "folder" }` updates metadata + index

SQLite remains the control-plane source of truth; disk mirrors and `workspace.json` are for Studio navigation and Git-friendly files.

## Where pipeline files live

| Store | Path |
|-------|------|
| SQLite head + versions | `{work_dir}/data/formulaetl.db` |
| Mirror JSON | `{work_dir}/pipelines/{id}.json` |
| Workspace folders | `{work_dir}/data/workspace.json` |
| Bundled demos (seed) | `demos/**/pipeline.json` (+ master children) |

## Desktop Studio

Electron loads `apps/web/dist` against the local API with the same `FORMULAETL_WORK_DIR`.  
Workspace folders and pipeline assignments are identical to the browser Studio — one work dir, one tree.

## Related

- Projects + Git: `PROJECTS_AND_GIT.md`
- Finished product matrix: `FINISHED_PRODUCT.md`
- Job Contexts / Run Pipeline: `docs/CONTEXTS.md`
