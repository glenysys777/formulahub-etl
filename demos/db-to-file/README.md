# Demo: DB (Postgres component) → File

`postgres_source` / `postgres_destination` are the client-facing connectors.

**Honest demo:** with `FORMULAETL_DEMO=1`, the source reads **SQLite** `data/demo.db`
(seeded by `make seed`) or returns fixture rows if the DB is missing — **not a live
Postgres connection**. The destination writes SQLite + CSV under
`data/out/postgres_demo/`.

Real Postgres needs a DSN (or host/db/user/password) and `FORMULAETL_DEMO=0`.

```bash
make demo-db
# or
FORMULAETL_DEMO=1 python -m formulaetl.cli run demos/db-to-file/pipeline.json
```
