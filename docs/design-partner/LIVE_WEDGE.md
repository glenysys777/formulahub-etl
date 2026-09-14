# Live wedge E2E (design partner)

**Classification:** `LIVE_CLOUD`  
**Default status:** **UNPROVEN** — CI never runs this against real clouds.

The harness exercises one honest customer-shaped path:

```
S3 | SFTP  →  PGP decrypt  →  CSV parse  →  schema_validate  →  column_map
           →  Postgres | Snowflake  →  archive_files
```

## How to run

```bash
# 1) Credential readiness only (safe — no network load):
python3 scripts/live_wedge_e2e.py --check

# 2) Live attempt (requires real systems you control):
export RUN_LIVE_WEDGE=1
export FORMULAETL_DEMO=0
python3 scripts/live_wedge_e2e.py

# Or via pytest (same gates):
RUN_LIVE_WEDGE=1 FORMULAETL_DEMO=0 python3 -m pytest tests/live -m live -v
```

If `RUN_LIVE_WEDGE` is unset, or credentials are missing, the harness **skips** and reports `evidence: UNPROVEN`. That is correct — do **not** paste a skip into `PRODUCTION_EVIDENCE` as PROVEN.

After a **successful** live run, paste the JSON stdout (redact secrets) into `docs/PRODUCTION_EVIDENCE.md` section **C / LIVE_CLOUD** with the git SHA and date.

## Required environment variables

### Gate

| Variable | Required | Meaning |
|----------|----------|---------|
| `RUN_LIVE_WEDGE` | yes (`1`) | Opt-in. Without this, harness skips. |
| `FORMULAETL_DEMO` | yes (`0`) | Live libraries / real hosts (harness also forces `0`). |

### Source (choose one)

Set `LIVE_SOURCE=s3` or `LIVE_SOURCE=sftp`, or omit to auto-detect.

**S3**

| Variable | Required |
|----------|----------|
| `LIVE_S3_BUCKET` | yes |
| `LIVE_S3_KEY` | yes (encrypted object key, e.g. `inbox/orders.csv.pgp`) |
| `LIVE_S3_REGION` | no (falls back to `AWS_DEFAULT_REGION` / `us-east-1`) |
| `LIVE_S3_ENDPOINT` | no (S3-compatible endpoint) |
| `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` | recommended (or `AWS_PROFILE` / instance role) |

**SFTP**

| Variable | Required |
|----------|----------|
| `LIVE_SFTP_HOST` | yes |
| `LIVE_SFTP_USER` | yes |
| `LIVE_SFTP_REMOTE_PATH` | yes |
| `LIVE_SFTP_PASSWORD` or `LIVE_SFTP_KEY_PATH` or `FORMULAETL_SFTP_PASSWORD` | yes (one of) |
| `LIVE_SFTP_PORT` | no (default 22) |
| `LIVE_SFTP_STAGING` | no |

### PGP

| Variable | Required |
|----------|----------|
| `LIVE_PGP_PRIVATE_KEY_PATH` | yes (path to private key file) |
| `LIVE_PGP_PASSPHRASE` | if the key is protected |

### Destination (choose one)

Set `LIVE_DEST=snowflake` or `LIVE_DEST=postgres`, or omit to auto-detect.

**Snowflake**

| Variable | Required |
|----------|----------|
| `LIVE_SNOWFLAKE_ACCOUNT` | yes |
| `LIVE_SNOWFLAKE_USER` | yes |
| `LIVE_SNOWFLAKE_PASSWORD` or `SF_PASS` | yes |
| `LIVE_SNOWFLAKE_WAREHOUSE` | yes |
| `LIVE_SNOWFLAKE_DATABASE` | yes |
| `LIVE_SNOWFLAKE_SCHEMA` | no (default `PUBLIC`) |
| `LIVE_SNOWFLAKE_TABLE` | no (default `FORMULAETL_LIVE_WEDGE`) |

**Postgres**

| Variable | Required |
|----------|----------|
| `LIVE_POSTGRES_DSN` | yes **or** host form below |
| `LIVE_POSTGRES_HOST` + `LIVE_POSTGRES_USER` + `LIVE_POSTGRES_PASSWORD` (or `FORMULAETL_POSTGRES_PASSWORD`) + `LIVE_POSTGRES_DATABASE` | yes if no DSN |
| `LIVE_POSTGRES_PORT` | no (5432) |
| `LIVE_POSTGRES_TABLE` | no |

### Optional mapping / validate / archive

| Variable | Meaning |
|----------|---------|
| `LIVE_COLUMN_MAPPINGS` | Comma-separated `old:new` renames (default `order_id:order_id`) |
| `LIVE_VALIDATE_COLUMNS` | JSON object of column→type for `schema_validate` |
| `LIVE_CSV_DELIMITER` | Default `,` |
| `LIVE_ARCHIVE_DIR` | Default `data/archive/live_wedge/` |
| `LIVE_ARCHIVE_MODE` | `copy` (default) or `move` |

## What CI does

GitHub Actions runs `pytest -m "not live"` with `FORMULAETL_DEMO=1` only.  
**No** AWS/SFTP/Snowflake/Postgres live calls. A green CI badge ≠ live wedge PROVEN.

## Related

- Demo (fixture) path: `demos/s3-pgp-snowflake/` under `FORMULAETL_DEMO=1`
- Connections: [`CONNECTIONS.md`](./CONNECTIONS.md) / [`docs/CONNECTIONS.md`](../CONNECTIONS.md)
- Checklist: [`PRODUCTION_CHECKLIST.md`](./PRODUCTION_CHECKLIST.md)
