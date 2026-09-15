# Master → Child: File → Databricks (DEMO)

**FormulaHub ETL** Master pipeline that runs two **Child** pipelines via **Run Pipeline**.

## What it shows

1. **Child A (ingest)** — CSV → Schema Map → staging file  
2. **Child B (load)** — Databricks SQL DEMO with inherited Job Context (`${context.env}` / `${context.catalog}`)  
3. Master chains `${child.ingest.rows_out}` into Child B `run_params`

## Run (DEMO)

```bash
FORMULAETL_DEMO=1 FORMULAETL_CONTEXT=QA \
  python -m formulaetl.cli run demos/master-file-to-databricks/pipeline.json
```

- Default `FORMULAETL_DEMO=1` writes sidecars under `data/out/master_child/` — **not** a live warehouse proof.
- `FORMULAETL_CONTEXT=QA` switches the Master active context; Child steps with `context_mode=inherit` pick up **QA**.

## Honesty

| Mode | Meaning |
|------|---------|
| DEMO | Local fixtures + Databricks SQL sidecar with resolved SQL |
| LIVE | Requires workspace credentials; **UNPROVEN** in CI |

UI terms: Master pipeline, Child pipeline, Run Pipeline only — no competitor product names.

Design: [`docs/architecture/MASTER_CHILD_PIPELINES.md`](../../docs/architecture/MASTER_CHILD_PIPELINES.md)
