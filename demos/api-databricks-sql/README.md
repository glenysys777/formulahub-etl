# API → Databricks SQL (demo)

**Status:** DEMO only under `FORMULAETL_DEMO=1`. LIVE Databricks SQL Warehouse calls are **UNPROVEN** until workspace host + token + warehouse id are configured.

## What it shows

1. **HTTP API Source** (fixture orders)
2. **Databricks SQL** node runs a statement with dynamic variables:
   - `${run_date}` from `metadata.run_params` / run clock
   - `${context.env}` / `${context.catalog}` from active Job Context (`DEV` / `QA` / `PROD`)
   - `${upstream.channel}` from the first upstream row

Demo mode writes a Statement Execution–shaped sidecar under `data/out/databricks_sql_demo/` including `sql_template` and `sql_resolved`.

## Run

```bash
FORMULAETL_DEMO=1 python -m formulaetl.cli run demos/api-databricks-sql/pipeline.json
# or switch context without editing SQL:
FORMULAETL_DEMO=1 FORMULAETL_CONTEXT=QA python -m formulaetl.cli run demos/api-databricks-sql/pipeline.json
```

## Founder note — passing variables into Databricks SQL

Keep SQL templates in the node; put environment differences in **Job Contexts** (`metadata.contexts`). At run time FormulaHub resolves `${…}` before submit (or into the DEMO sidecar). Preview in Studio shows resolved values for the active context without calling Databricks.

See [docs/CONTEXTS.md](../../docs/CONTEXTS.md).
