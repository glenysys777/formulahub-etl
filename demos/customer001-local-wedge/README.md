# Customer001 LOCAL wedge

**Classification:** `LOCAL_ONLY` / `LOCAL_PROVEN` (when real local Postgres) — **never** `LIVE_EXTERNAL`.

```
local encrypted drop → PGP → CSV → schema_validate → Field Mapper (tmap)
  → lookup → dedupe → rejects file → Postgres → archive → reconcile
```

## Quick start (DEMO postgres mirror)

```bash
python3 scripts/seed_demo.py
python3 scripts/customer001_local_wedge.py --mode demo
# or:
FORMULAETL_DEMO=1 python3 -m formulaetl.cli run demos/customer001-local-wedge/pipeline.json
```

## Real local Postgres (Mac / Linux)

See [`docs/CUSTOMER001_LOCAL_WEDGE.md`](../../docs/CUSTOMER001_LOCAL_WEDGE.md).

```bash
export FORMULAETL_DEMO=0
export LOCAL_POSTGRES_DSN="host=127.0.0.1 port=5432 dbname=formulaetl user=formula password=formula"
python3 scripts/customer001_local_wedge.py --mode postgres
```

Expected reconciliation: **N=12 = R=2 + D=2 + L=8**.
