# Control plane vs data plane (north star)

**Status:** design intent only. **No implementation in this PR.**

Customer #1 production trust requires splitting what is today a **single Python process** (FastAPI + in-memory runs + sequential runner + cron thread).

```
┌─────────────────────────────────────────────────────────┐
│ Control plane (API / UI / metadata)                     │
│  • Pipeline JSON (no secrets)                           │
│  • Authn/z, schedule records, run records               │
│  • “Start run” / “cancel” / logs tail                   │
│  Must not hold customer datasets in RAM                 │
└──────────────────────────┬──────────────────────────────┘
                           │ run contract (id, graph, secret refs)
                           ▼
┌─────────────────────────────────────────────────────────┐
│ Data plane (private worker)                             │
│  • Runs next to the customer’s VPC / files / warehouses │
│  • Pulls credentials from the customer’s vault/IAM      │
│  • Reads/writes data without shipping it through SaaS   │
│  • Bounded memory: chunked files, not list[dict] of all │
│    rows; binary objects streamed to disk, not bytes[]   │
└─────────────────────────────────────────────────────────┘
```

## Today (honest)

Control plane **is** the data plane: `POST /run` executes `PipelineRunner` under a process lock and stores logs in `RunStore` memory. Default `FORMULAETL_DEMO=1` reads `./data/s3` and writes `./data/out/*`.

## Later (not this PR)

- Do **not** add Spark, Kubernetes operators, or new connectors in order to “look like” a data plane.
- First production shape: **authenticated control API + one private worker** that already runs the existing DAG with chunking and secret refs.
- Multi-tenant hosted workers and HA schedulers are **ENTERPRISE**, after a design partner survives the single-worker path.

See capability matrix in `docs/PRODUCTION_READINESS.md`.
