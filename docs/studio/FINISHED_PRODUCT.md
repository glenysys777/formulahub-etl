# FormulaHub Studio — Finished Product Matrix

Honest status of basic Studio components as of this polish wave.  
**DEMO** = works with `FORMULAETL_DEMO=1` / fixtures / sidecars. **ALPHA** = real code path exists; live credentials often UNPROVEN in CI. **PLANNED** = not shipped.

No competitor product names. Studio names only: **Field Mapper**, **Schema Map**, **Lookup Join**, **Main** / **Lookup** inputs.

| Component | Key functions / features | Status |
|-----------|--------------------------|--------|
| S3 Source | Read object; DEMO local mock under `data/s3/` | DEMO / ALPHA live |
| Local File Source | Path relative to workspace `work_dir` | ALPHA |
| Excel Source | Sheet + Discover schema | ALPHA |
| HTTP API Source | GET/JSON path; DEMO fixture | DEMO / ALPHA live |
| Kafka Source | Batch pull; DEMO jsonl fixture | DEMO (live UNPROVEN) |
| SFTP Source | DEMO copies fixtures to staging | DEMO (live UNPROVEN) |
| Postgres / MySQL / SQLite Source | Query → rows; DEMO → SQLite/fixtures | DEMO / ALPHA |
| CSV / JSON / XML Parser | Delimited / path / record → rows | ALPHA |
| Schema Map | Rename columns; Discover + visual map | ALPHA |
| **Field Mapper** | **Input · Variables · Output**; expressions (`upper`, `coalesce`, math); Discover; reject stream opt. | ALPHA |
| Transform / Filter / Sort / Aggregate / Dedupe | Casts, keep-when, keys, group aggs, unique | ALPHA |
| **Lookup Join** | **Main** + **Lookup** handles (or Lookup file); left/inner/right/full; match all/first | ALPHA |
| Python Row | Sandboxed row/batch Python | ALPHA |
| Schema Validate | Required cols + types; rejects handle | ALPHA |
| PGP Decrypt / Encrypt | Path/temp; DEMO keys under `fixtures/keys/` | DEMO / ALPHA |
| Local / Excel Destination | Write under workspace | ALPHA |
| Snowflake Destination | DEMO filesystem sidecar | DEMO (live blocker if sold as warehouse) |
| Databricks Job / SQL | Jobs / Statement API; `${…}` vars; DEMO sidecars | DEMO (LIVE UNPROVEN) |
| SFTP / Postgres / MySQL / SQLite Destination | DEMO mocks or local DB | DEMO / ALPHA |
| Archive Files / Logger | Move inputs; metrics | ALPHA |
| Scheduler | In-process cron per pipeline | DEMO / ALPHA |
| **Job Contexts** | Right-rail DEV/QA/PROD key–value + run_params; Studio editor (no JSON) | ALPHA |
| Studio chrome | Collapsible inspector, type-to-place, status `work_dir`, Save / Export | ALPHA |
| Project files | Mirror JSON under `{work_dir}/pipelines/`; export JSON/zip | ALPHA |
| Desktop shell | Electron: spawn/reuse API + Studio window; Mac `.app` via `dist:mac` / mac-pack | ALPHA |

## Studio UX (this wave)

- Collapsible right sidebar (persisted) → big canvas workspace
- Type on focused canvas → quick-add palette (filter · Enter · Esc)
- **Main / Lookup** labels only on dual-input **Lookup Join** (single-input Schema Map / Field Mapper stay quiet)
- Double-click any node → expand inspector (mapper still opens overlay)
- Save + Export JSON; toast shows mirror path; Copy git commands
- Field Mapper Variables: expression helper chips (string / math / null; date honest DEMO limits)
- Status bar: `workspace on this machine · {work_dir}`
- Projects + Git → see `PROJECTS_AND_GIT.md`
- Desktop: double-click **FormulaHub Studio.app** → API + Studio window (browser is optional menu item)
- **Job Contexts** (right rail): DEV/QA/PROD key–value editor + `run_date` / `job_name`; same metadata as Databricks Variables preview — see `docs/CONTEXTS.md`

## Explicitly not in this wave

- No new connector types
- No GitHub OAuth / one-click remote (Pro later)
- Desktop shell is shipped — see `DESKTOP_SHELL.md` (signed/notarized Mac builds still need Apple secrets)
