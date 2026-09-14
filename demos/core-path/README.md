# Excel → Field Mapper → Aggregate → CSV

Spreadsheet in → **Field Mapper** (expression mappings + visual mapper) → Filter → **Sort** → **Aggregate** → CSV.

Shows FormulaHub ETL's core path for spreadsheet jobs. Click the Excel source → **Discover schema**, or open Field Mapper → **Open Field Mapper** → **Discover** for drag-and-drop column mapping. Complex expressions remain editable as text.

## LOCAL Postgres variant (LOCAL_PROVEN — not LIVE_EXTERNAL)

Retargeted to local files + Homebrew/`formulahub_wedge.customers_wedge`:

```bash
# Mac: double-click FormulaHub-ETL-Mac/START-POSTGRES.command first
export FORMULAETL_DEMO=0
export LOCAL_POSTGRES_DSN="host=localhost port=5432 dbname=formulahub_wedge"
python3 -m formulaetl.cli run demos/core-path/pipeline.local-postgres.json
```

See `docs/CUSTOMER001_LOCAL_WEDGE.md`. Snowflake/S3 cloud paths remain **UNPROVEN**.
