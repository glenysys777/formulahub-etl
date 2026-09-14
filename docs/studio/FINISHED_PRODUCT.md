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
| Studio chrome | Collapsible inspector, type-to-place, status `work_dir` | ALPHA (this PR) |

## Studio UX (this wave)

- Collapsible right sidebar (persisted) → big canvas workspace
- Type on focused canvas → quick-add palette (filter · Enter · Esc)
- Main vs Lookup labeled on Field Mapper / Lookup Join + inspector help
- Field Mapper Variables: expression helper chips (string / math / null; date honest DEMO limits)
- Status bar: `workspace on this machine · {work_dir}`

## Explicitly not in this wave

- No new connector types
- Desktop `.app` shell → see `DESKTOP_SHELL.md` (next wave)
