# Master / Child pipelines (v1)

**Product:** FormulaHub ETL / FormulaHub Studio  
**Status:** Community v1  
**UI terms only:** Master pipeline, Child pipeline, **Run Pipeline** — never competitor product names.

## Goal

A **Master pipeline** orchestrates reusable **Child pipelines** via the **Run Pipeline** component (`run_pipeline`). Children inherit Job Contexts (optionally), publish metrics/params back to the master, and appear as durable child runs when the control plane records them.

```
┌─ Master pipeline ─────────────────────────────────────┐
│  … → [Run Pipeline → child A] → [Run Pipeline → B] → … │
│         publish_as=ingest          publish_as=load     │
│         ${child.ingest.*} ──────────► later run_params │
└────────────────────────────────────────────────────────┘
```

## Component: `run_pipeline` (display: **Run Pipeline**)

| Config key | Type | Default | Meaning |
|------------|------|---------|---------|
| `pipeline_id` | string | *(required)* | Child pipeline id, or a relative `.json` path under `work_dir` for CLI/demo |
| `context_mode` | `inherit` \| `child_active` \| `override` | `inherit` | How Job Contexts are chosen for the child |
| `context_name` | string | `""` | Used when `context_mode=override` (e.g. `QA`) |
| `run_params` | object | `{}` | Extra `${run.*}` / plain params for this child invocation |
| `publish_as` | string | node id | Key under master `children[<publish_as>]` |
| `on_failure` | `fail_master` \| `continue` | `fail_master` | Fail the master node vs log and continue |
| `pass_rows` | boolean | `false` | When true, passthrough input rows as this node’s output after the child succeeds |

Palette: **Orchestration**. Inspector: pipeline picker from `GET /api/pipelines`, context-mode help, **Open child pipeline** button.

## Context inheritance (parent → child)

Secrets / Connection tokens are **never** inherited across the master→child boundary. Children resolve secrets via their own Connections / `env:` / `secret:` refs.

| `context_mode` | Active context name | Context values |
|----------------|---------------------|----------------|
| `inherit` | Master’s active context name (`FORMULAETL_CONTEXT` still wins on the master) | Child’s set for that name (if any), then **overlaid** by master’s active context values |
| `child_active` | Child pipeline’s own `metadata.contexts.active` | Child set only |
| `override` | `context_name` from node config | Child’s set for that name (if any), then overlay from master’s set of the same name when present |

**Also merged into the child run (never secrets):**

1. Master `metadata.run_params` as a base  
2. Node `run_params` (wins over master)  
3. Earlier sibling publishes available as `${child.<publish_as>.<key>}` on the **master** for later nodes (and passed into subsequent children’s param maps)

## Child publishes

After a successful (or continued-after-failure) child run, the master records under `RunContext.variables["children"][publish_as]`:

- Aggregate child **metrics** (`rows_in`, `rows_out`, `rows_rejected`, `duration_ms`, `status`, `run_id`, `pipeline_id`, …)
- Optional flat map from child `metadata.publish` (static publish keys declared on the child pipeline)
- Selected child context / run_param keys useful for chaining (non-secret)

Later master nodes may use:

```text
${child.<publish_as>.rows_out}
${child.<publish_as>.status}
${child.<publish_as>.<published_key>}
```

## Cycle detection & depth

- Nested invocation tracks a **pipeline id stack** on the run context.
- Re-entering an id already on the stack → hard error (`Pipeline cycle detected`).
- Max nesting depth: env `FORMULAETL_PIPELINE_MAX_DEPTH` (default **5**). Depth counts master as 1; each Run Pipeline increments.

## Durable run store

SQLite `runs` columns (schema v3):

| Column | Meaning |
|--------|---------|
| `parent_run_id` | Master (or parent) run id; `NULL` for top-level |
| `master_node_id` | Node id of the Run Pipeline step that spawned this child |

Child runs are recorded when a run recorder / API worker path is available; CLI nested runs still execute in-process without requiring a queue round-trip.

## Studio

- Palette entry under **Orchestration**
- Inspector: pipeline picker, context mode, publish_as, on_failure, pass_rows
- Job Contexts help mentions inherit for Master → Child
- **Open child pipeline** loads the selected child in Studio

## Demo

`demos/master-file-to-databricks/` — master with two Run Pipeline children, Job Contexts (DEV/QA/PROD), `FORMULAETL_DEMO=1` / `FORMULAETL_CONTEXT=QA`.

Honesty: DEMO sidecars ≠ LIVE Databricks.

## Out of scope (v1)

- Spark-in-product, Stripe, new random connectors  
- Parallel fan-out of children  
- Remote distributed child workers (nested runs are in-process sequential)  
- Competitor trademark UI labels

## Related

- [CONTEXTS.md](../CONTEXTS.md) — Job Contexts + `${…}`  
- [CONTROL_DATA_PLANE.md](./CONTROL_DATA_PLANE.md) — control vs data plane  
- [COMPONENTS.md](../sales/COMPONENTS.md) — catalog
