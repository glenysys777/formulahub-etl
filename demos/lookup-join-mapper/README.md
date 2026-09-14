# Two sources → Lookup Join → Field Mapper → CSV

Demonstrates:

1. **Two sources** wired into **Lookup Join** — primary (`orders`) → left/`in` handle, lookup (`customers`) → `right` handle
2. Join types / match mode in node config (`how`, `match`)
3. **Field Mapper** with a **Variables** middle layer (`full_name`, `total`) before output mappings

```bash
make seed
FORMULAETL_DEMO=1 FORMULAETL_WORK_DIR=. python3 -m formulaetl.cli run demos/lookup-join-mapper/pipeline.json
```

Output: `data/out/lookup_join_mapper.csv`

## LOCAL Postgres variant (LOCAL_PROVEN — not LIVE_EXTERNAL)

Retargeted to local files + Homebrew/`formulahub_wedge.customers_wedge`:

```bash
# Mac: double-click FormulaHub-ETL-Mac/START-POSTGRES.command first
export FORMULAETL_DEMO=0
export LOCAL_POSTGRES_DSN="host=localhost port=5432 dbname=formulahub_wedge"
python3 -m formulaetl.cli run demos/lookup-join-mapper/pipeline.local-postgres.json
```

See `docs/CUSTOMER001_LOCAL_WEDGE.md`. Snowflake/S3 cloud paths remain **UNPROVEN**.
