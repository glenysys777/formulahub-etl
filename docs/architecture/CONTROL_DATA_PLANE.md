# Control plane vs data plane (north star)

**Status:** Phase D+E landed a **Community** control-plane split: HTTP enqueues runs; a worker (embedded or `make worker`) executes. Data plane is still the same sequential `PipelineRunner` (not Spark/K8s).

Customer #1 production trust still requires auth, secret refs, and a private worker next to customer data.

```
┌─────────────────────────────────────────────────────────┐
│ Control plane (API / UI / metadata)                     │
│  • Pipeline + immutable versions (SQLite)               │
│  • Schedule records, run ledger, run_events, node_runs  │
│  • “Start run” → 202 queued / cancel (cancel TBD)       │
│  Must not hold customer datasets in RAM                 │
└──────────────────────────┬──────────────────────────────┘
                           │ job_queue (run_id, version pin)
                           ▼
┌─────────────────────────────────────────────────────────┐
│ Data plane (worker process or embedded thread)          │
│  • Claims QUEUED jobs; runs PipelineRunner              │
│  • Pulls credentials from the customer’s vault/IAM      │
│    (not yet — secrets still in JSON)                    │
│  • Bounded memory: chunked files where Phase B/C allow  │
└─────────────────────────────────────────────────────────┘
```

## Today (honest)

- `POST /run` returns **202** + `queued`; worker persists `queued`→`running`→`success`/`failed`.
- History survives API/worker restart (SQLite under `data/formulaetl.db`).
- Runs pin `pipeline_version_id` so edits do not rewrite yesterday’s graph.
- Default Community UX still embeds the worker in the API process.
- CLI `formulaetl run` remains synchronous (no queue).

## Later (not this PR)

- Do **not** add Spark, Kubernetes operators, or new connectors in order to “look like” a data plane.
- Next trust steps: **authenticated control API** + always-separate private worker + secret refs.
- Multi-tenant hosted workers and HA schedulers are **ENTERPRISE**.

See capability matrix in `docs/PRODUCTION_READINESS.md`.
