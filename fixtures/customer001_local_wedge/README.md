# Customer001 LOCAL wedge fixtures

| File | Role |
|------|------|
| `orders.csv` | Plaintext source (N=12 deterministic rows) |
| `orders.csv.pgp` | Encrypted with `fixtures/keys/demo_public.asc` |
| `customers_lookup.csv` | Optional lookup for `lookup_join` |
| `schema.json` | Schema validate column types |
| `expected_counts.json` | Mathematical reconciliation targets |

**Keys:** use repo demo keys under `fixtures/keys/` (no passphrase). Demo only — not production.

**Honesty:** these files prove **LOCAL** filesystem + PGP + parse paths. They do **not** prove cloud SFTP/S3/Snowflake/Databricks.
