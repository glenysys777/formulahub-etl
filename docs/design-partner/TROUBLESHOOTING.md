# Troubleshooting (design partner)

## API offline / UI footer

- Designer defaults to `http://127.0.0.1:18765`. Start `make api` or set `VITE_API_URL` at **build** time for hosted UI.
- Vercel UI alone cannot run pipelines.

## 401 unauthorized

- `FORMULAETL_API_KEY` is set on the server but the client omitted `X-API-Key` / Bearer.

## Run stays `queued`

- Embedded worker disabled and no standalone worker: run `make worker` or `POST /api/worker/tick` (lab only).
- Check `/health` → `queue_depth`, `embedded_worker`.

## Validate ✗ but Run used to work

- Canvas body vs stored pipeline differ — validate with current nodes/edges in the POST body (UI does this).
- `connection_id` deleted, or `env:` / `secret:` ref missing.
- Empty `column_map` / `tmap` mappings.

## Connection test fails live

- Under `FORMULAETL_DEMO=1`, demo hosts (`host: demo`, example.com fixtures) succeed by design.
- Live failures: credentials, network, SFTP host-key reject policy, missing boto3/psycopg extras.
- **CI does not prove live AWS/SFTP/Snowflake/Kafka/Databricks/Postgres.** Treat live E2E as a manual design-partner checklist.

## Metrics look “high”

- `rows_in` / `rows_out` are **summed across nodes**, not distinct pipeline row counts. Use per-node `node_runs` for clarity.

## Secrets show `***`

- Expected on GET. Use refs + connection store; never log resolved values.

## Reset demo fixtures

```bash
make seed
```
