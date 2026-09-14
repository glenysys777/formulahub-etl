# Spectacular demo: S3 → PGP → CSV → Validate → Transform → Snowflake (demo) → Archive

See the pipeline definition in `pipeline.json`.

```bash
# from repo root
make seed
make demo
```

Expected: 10 good rows under `data/out/snowflake/`, 3 rejects under `data/rejects/`, encrypted source moved to `data/archive/`.

## LOCAL Postgres variant (LOCAL_PROVEN — not LIVE_EXTERNAL)

Retargeted to local files + Homebrew/`formulahub_wedge.customers_wedge`:

```bash
# Mac: double-click FormulaHub-ETL-Mac/START-POSTGRES.command first
export FORMULAETL_DEMO=0
export LOCAL_POSTGRES_DSN="host=localhost port=5432 dbname=formulahub_wedge"
python3 -m formulaetl.cli run demos/s3-pgp-snowflake/pipeline.local-postgres.json
```

See `docs/CUSTOMER001_LOCAL_WEDGE.md`. Snowflake/S3 cloud paths remain **UNPROVEN**.
