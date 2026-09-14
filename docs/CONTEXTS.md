# Job Contexts + dynamic variables

**Status:** Community / design-partner. Contexts are named key/value sets on a pipeline (or project metadata). They are **not** a secrets vault — put credentials in Connections / SecretProvider (see [CONNECTIONS.md](./CONNECTIONS.md)).

## Why

Enterprise Databricks flows need the same SQL or job params to run across **DEV / QA / PROD** with different catalogs, env labels, and dates — without rewriting the node. FormulaHub resolves `${…}` templates at run time (and in Studio preview).

## Variable syntax

| Ref | Source |
|-----|--------|
| `${context.key}` | Active Job Context set |
| `${run.key}` | Run identity + `metadata.run_params` (`run_id`, `pipeline_id`, `run_date`, …) |
| `${env.NAME}` | Process environment (explicit namespace) |
| `${upstream.field}` | Field from the first upstream row |
| `${key}` | Merged map: `run_params` + active context (+ extras). **Not** bare env |

Secret fields (`token`, `password`, …) are skipped by the interpolator; resolve them via `env:…` / `secret:…` / Connections first.

## Studio: Job Contexts panel

In **FormulaHub Studio** (`apps/web`), open a pipeline and use the right-rail **Job Contexts** accordion (pipeline-level — not buried only inside a Databricks node):

1. **Active context** dropdown — switch DEV / QA / PROD (or any sets you add).
2. **Key–value table** for the active set — add / edit / delete rows (`env`, `catalog`, `schema`, …).
3. **Add / Duplicate / Rename / Delete** context sets.
4. **Run params** — edit common `run_date` and `job_name` (same `metadata.run_params` used at run time).
5. Changes update pipeline metadata in React state and persist via **Save** / auto-save (same path as schedule and other metadata).

If a pipeline has no contexts yet, Studio seeds **DEV / QA / PROD** with empty starter keys (`env`, `catalog`, `schema`) so founders can fill values without editing JSON.

**Databricks SQL / Job** node inspector still has **Variables**: active-context switch + resolved `${…}` preview. Both panels read/write the same `metadata.contexts` / `metadata.run_params`.

Help copy in Studio: *Environment parameters for this pipeline. Use `${context.key}` in Databricks SQL / Job params. Tokens stay in Connections / secrets.*

## Job Contexts on a pipeline (JSON shape)

```json
{
  "metadata": {
    "run_params": {
      "run_date": "2026-09-14"
    },
    "contexts": {
      "active": "DEV",
      "sets": {
        "DEV": { "env": "dev", "catalog": "sandbox" },
        "QA": { "env": "qa", "catalog": "qa_main" },
        "PROD": { "env": "prod", "catalog": "main" }
      }
    }
  }
}
```

- Switch active context in Studio (Job Contexts rail or Databricks SQL / Job inspector) or at run time:

```bash
FORMULAETL_CONTEXT=QA FORMULAETL_DEMO=1 python -m formulaetl.cli run demos/api-databricks-sql/pipeline.json
```

## Databricks SQL (clean path)

1. Drop **Databricks SQL** (`databricks_sql`).
2. Write SQL with `${run_date}`, `${context.env}`, `${upstream.…}` as needed.
3. Preview **Resolved** values for the active context (no live warehouse call).
4. Run with `FORMULAETL_DEMO=1` → sidecar under `data/out/databricks_sql_demo/` includes `sql_resolved`.
5. For LIVE: set `workspace_host`, `token`, `warehouse_id`, `FORMULAETL_DEMO=0`. Free Edition Soft-PASS: SQL [`docs/evidence/databricks_sql_smoke_redacted.json`](./evidence/databricks_sql_smoke_redacted.json); Jobs [`docs/evidence/databricks_job_smoke_redacted.json`](./evidence/databricks_job_smoke_redacted.json) (PAT never in repo).

**Databricks Job** (`databricks_job`) notebook/python param *values* use the same `${…}` resolver.

## Honesty

- DEMO sidecars are clearly labeled; they are not a workspace proof.
- Contexts do not replace Connections for tokens.
- No competitor product names in Studio copy.
