# Demo: HTTP/REST API → Column Map → Transform → Validate → File

**Client-facing use case:** ingest JSON orders from a REST endpoint whose field names
do not match your warehouse schema, normalize columns, cast dates/types, validate,
and land a clean CSV (or swap the last node for Snowflake demo destination).

## Flow

1. **HTTP API Source** (`http_api_source`) — GET JSON; in demo mode (`FORMULAETL_DEMO=1`
   + `example.com` URL or `demo=true`) loads `fixtures/sample/api_orders.json` (~12 orders
   with mixed names like `orderId`, `amt`).
2. **Column Map** (`column_map`) — `old:new` lines (`orderId→order_id`, `amt→amount`, …).
3. **Transform** — date cast on `order_date`, numeric casts.
4. **Schema Validate** — required columns + types; good rows continue.
5. **Local File Destination** — `data/out/api_orders.csv`.

## Run

```bash
# from repo root
export FORMULAETL_DEMO=1 FORMULAETL_WORK_DIR=$PWD
python -m formulaetl.cli run demos/api-map-transform/pipeline.json

# or via API after `make api`
curl -X POST http://127.0.0.1:18765/api/pipelines/demo-api-map-transform/run
```

No cloud credentials required — the HTTP step uses the local fixture in demo mode.
