# Connections + Secret refs (Phase F)

**Status:** Community / design-partner path. Local encrypted store + env refs — **not** an enterprise vault.

## Why

Customer #1 blockers: passwords in pipeline JSON and unauthenticated GET of those values.

Phase F adds **reusable Connections** and a **SecretProvider** so pipeline JSON holds **references** (`connection_id`, `env:NAME`, `secret:<id>`) instead of raw credentials where practical.

## Create a connection locally

```bash
# API running: make api  (FORMULAETL_DEMO=1 by default)

curl -s http://127.0.0.1:8000/api/connections \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "Partner SFTP",
    "kind": "sftp",
    "config": {"host": "demo", "port": 22, "username": "etl"},
    "secrets": {"password": "env:FORMULAETL_SFTP_PASSWORD"}
  }' | jq .

# Or store a value in the encrypted local store (demo key when DEMO=1):
curl -s http://127.0.0.1:8000/api/connections \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "Partner Postgres",
    "kind": "postgres",
    "config": {"host": "demo", "database": "orders", "user": "etl"},
    "secrets": {"password": "local-only-password"}
  }' | jq .
```

Kinds: `sftp`, `s3`, `snowflake`, `postgres`, `http`, `databricks`.

- `GET /api/connections` / `GET /api/connections/{id}` — **secrets masked** (refs like `env:…` / `secret:…` are returned; plaintext never is).
- `POST /api/connections/{id}/test` — demo hosts succeed under `FORMULAETL_DEMO=1`; live checks use real libraries when credentials point at real systems.
- `PUT` with `"password": "***"` keeps the previous secret.

## Job Contexts + `${…}` in SQL / params

Named DEV/QA/PROD (or custom) variable sets live on `pipeline.metadata.contexts`. Databricks SQL and Job nodes resolve `${context.*}`, `${run.*}`, `${env.*}`, `${upstream.*}` before submit. See **[CONTEXTS.md](./CONTEXTS.md)**.

## Point a node at `connection_id`

**Before (inline demo — still valid when `FORMULAETL_DEMO=1`):**

```json
{
  "id": "src",
  "type": "sftp_source",
  "config": {
    "host": "demo",
    "username": "demo",
    "password": "",
    "remote_path": "/inbox/orders.xlsx",
    "local_staging_path": "data/out/sftp_staging/"
  }
}
```

**After (connection ref):**

1. Create a connection (above) → note `id`.
2. Replace credential fields with `connection_id`; keep node-specific paths/tables:

```json
{
  "id": "src",
  "type": "sftp_source",
  "config": {
    "connection_id": "<connection-uuid>",
    "remote_path": "/inbox/orders.xlsx",
    "local_staging_path": "data/out/sftp_staging/"
  }
}
```

Runtime merges connection public fields + resolved secrets into the node config **in memory only**. Version snapshots keep the `connection_id` reference, not the password.

Same pattern for: `s3_source`, `snowflake_destination`, `postgres_source` / `postgres_destination`, `http_api_source`, `sftp_destination`, `databricks_job` / `databricks_sql`.

## SecretProvider (Community)

| Backend | How |
|---------|-----|
| Env vars | `env:VAR`, `${VAR}`, or bare `FORMULAETL_*` |
| Encrypted local store | Plaintext submitted on create → Fernet ciphertext in SQLite `secrets` table → ref `secret:<id>` |

Key material:

1. `FORMULAETL_SECRETS_KEY` (preferred for non-demo)
2. Else `data/.formulaetl_secrets_key` (auto-created when not demo)
3. Else DEMO well-known material when `FORMULAETL_DEMO=1` (**insecure — demos only**)

## Optional API key

```bash
export FORMULAETL_API_KEY=dev-partner-key
# Clients: X-API-Key: dev-partner-key   or   Authorization: Bearer …
```

When unset, Community stays open. `/health` always open.

## Migration path for existing demos

- Bundled `demos/*/pipeline.json` keep inline `host: "demo"` — **no change required**.
- Hybrid: a node may use `connection_id` **or** inline fields; inline still works under DEMO=1.
- Convert one node at a time using the steps above; save a new pipeline version.

## Honesty

- Not SSO/RBAC, not HashiCorp Vault / AWS Secrets Manager, not multi-tenant.
- AI builder never receives decrypted secrets; GET responses mask them.
- Live connector proofs remain **UNPROVEN** in CI — this phase only removes the “secrets in JSON + open GET” blocker for a design-partner laptop/private worker.
