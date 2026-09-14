# Connections (design partner)

Full how-to lives in **[`docs/CONNECTIONS.md`](../CONNECTIONS.md)** (Phase F).

Quick reminders:

1. Create a connection (`sftp` / `s3` / `snowflake` / `postgres` / `http`) with secrets as env refs or local-store values.
2. Point nodes at `connection_id` instead of embedding passwords.
3. `POST /api/connections/{id}/test` under DEMO proves the wiring; live tests need real credentials and `FORMULAETL_DEMO=0`.
4. `POST /api/pipelines/{id}/validate` checks that `connection_id` **resolves** and that secret refs **exist** — it does not replace a live connection test.
5. Full live path (S3|SFTP → PGP → CSV → validate → map → Postgres|Snowflake → archive): see **[`LIVE_WEDGE.md`](./LIVE_WEDGE.md)** (`RUN_LIVE_WEDGE=1`, classification `LIVE_CLOUD`, default **UNPROVEN**).
