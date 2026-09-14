# Backup (design partner)

## What to back up

| Path / object | Contents |
|---------------|----------|
| `data/formulaetl.db` | Pipelines, versions, runs, node_runs, events, schedules, connections metadata, encrypted secrets |
| `data/.formulaetl_secrets_key` | Local Fernet key (if you are not using `FORMULAETL_SECRETS_KEY`) |
| Pipeline JSON exports (optional) | Human-readable graphs; still prefer DB versions as source of truth |
| `data/out/`, staging dirs | Job outputs — optional; regenerate from sources when possible |

Do **not** commit real secret keys or live credentials to git.

## Suggested procedure

1. Stop the worker (and API if you need a consistent SQLite snapshot).
2. Copy `data/formulaetl.db` (+ WAL/SHM if present) and the secrets key material.
3. Restart processes.
4. Restore by replacing the DB file (same schema version) and key, then start API/worker.

## Limits

- No built-in point-in-time recovery, replication, or multi-region backup.
- Schema migrations are versioned in code (`SCHEMA_VERSION`); restore onto a matching app SHA.
- DEMO databases are disposable — wipe and `make seed` for clean demos.
