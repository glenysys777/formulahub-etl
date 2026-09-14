# Control plane vs data plane (north star)

**Status:** Phase D+E landed a **Community** control-plane split (HTTP enqueues; worker executes). Phase F adds **Connections + SecretProvider** so workers can resolve `connection_id` / env / local encrypted refs without putting passwords in pipeline JSON. Data plane is still the sequential `PipelineRunner` (not Spark/K8s).

Customer #1 production trust still needs live connector proofs + a private worker next to customer data.

```
┌─────────────────────────────────────────────────────────┐
│ Control plane (API / UI / metadata)                     │
│  • Pipeline + immutable versions (SQLite)               │
│  • Connections metadata (no plaintext secrets on GET)   │
│  • Schedule records, run ledger, run_events, node_runs  │
│  • Optional FORMULAETL_API_KEY gate                     │
│  • “Start run” → 202 queued / cancel (cancel TBD)       │
│  Must not hold customer datasets in RAM                 │
└──────────────────────────┬──────────────────────────────┘
                           │ job_queue (run_id, version pin)
                           ▼
┌─────────────────────────────────────────────────────────┐
│ Data plane (worker process or embedded thread)          │
│  • Claims QUEUED jobs; runs PipelineRunner              │
│  • Resolves connection_id + SecretProvider (env/local)  │
│    (not yet: customer Vault / IAM Roles Anywhere)       │
│  • Bounded memory: chunked files where Phase B/C allow  │
└─────────────────────────────────────────────────────────┘
```

## Today (honest)

- `POST /run` returns **202** + `queued`; worker persists `queued`→`running`→`success`/`failed`.
- History survives API/worker restart (SQLite under `data/formulaetl.db`).
- Runs pin `pipeline_version_id` so edits do not rewrite yesterday’s graph.
- Connections + secret refs: see `docs/CONNECTIONS.md`.
- Default Community UX still embeds the worker in the API process.
- CLI `formulaetl run` remains synchronous (no queue); resolves env secret refs.

## Later (not this PR)

- Do **not** add Spark, Kubernetes operators, or new connectors in order to “look like” a data plane.
- Next trust steps: always-separate private worker + live partner proofs + stronger vault backends.
- Multi-tenant hosted workers and HA schedulers are **ENTERPRISE**.

See capability matrix in `docs/PRODUCTION_READINESS.md`.
