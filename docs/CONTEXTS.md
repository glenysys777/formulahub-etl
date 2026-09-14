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

## Job Contexts on a pipeline

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

- Switch active context in Studio (Databricks SQL / Job inspector) or at run time:

```bash
FORMULAETL_CONTEXT=QA FORMULAETL_DEMO=1 python -m formulaetl.cli run demos/api-databricks-sql/pipeline.json
```

## Databricks SQL (clean path)

1. Drop **Databricks SQL** (`databricks_sql`).
2. Write SQL with `${run_date}`, `${context.env}`, `${upstream.…}` as needed.
3. Preview **Resolved** values for the active context (no live warehouse call).
4. Run with `FORMULAETL_DEMO=1` → sidecar under `data/out/databricks_sql_demo/` includes `sql_resolved`.
5. For LIVE: set `workspace_host`, `token`, `warehouse_id`, `FORMULAETL_DEMO=0`. **LIVE remains UNPROVEN** until credentials are validated outside CI.

**Databricks Job** (`databricks_job`) notebook/python param *values* use the same `${…}` resolver.

## Honesty

- DEMO sidecars are clearly labeled; they are not a workspace proof.
- Contexts do not replace Connections for tokens.
- No competitor product names in Studio copy.
