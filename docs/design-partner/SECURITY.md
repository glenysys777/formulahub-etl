# Security (design partner)

**Level today:** Community / design-partner **ALPHA** for optional API key + local secrets — **not** ENTERPRISE.

## Auth

| Mode | When | Behavior |
|------|------|----------|
| Open Community | `FORMULAETL_API_KEY` unset | All `/api/*` open. Fine for local DEMO only. |
| API key | `FORMULAETL_API_KEY` set | Require `X-API-Key` or `Authorization: Bearer`. `/health` stays open. |

No SSO, no RBAC, no per-tenant isolation. One key = full control-plane access.

## Secrets

- Prefer **refs** in pipeline JSON: `env:NAME`, `${NAME}`, `secret:<id>`, and node **`connection_id`**.
- Local store: Fernet-encrypted rows in SQLite (`secrets` table). Key from `FORMULAETL_SECRETS_KEY` or `data/.formulaetl_secrets_key` (DEMO uses a well-known material — **do not use DEMO crypto for real credentials**).
- `GET` responses **mask** secret fields (`***` or refs). Validate and connection APIs never return plaintext secret values.
- AI builder strips secret literals before save.

## Threat notes (honest)

- CORS is `allow_origins=["*"]` — lock down at the reverse proxy for anything beyond a private lab.
- Embedded worker shares the API process memory — prefer a private worker for partner data.
- Pipeline versions created with inline passwords may still contain them until migrated (`docs/CONNECTIONS.md`).
- `python_row` uses restricted `exec` — not a sandbox for untrusted code.
- SQLite DB file on disk is the trust boundary — protect filesystem permissions and backups.

## Validate vs test

- `POST /api/pipelines/{id}/validate` — structural + ref **existence**; does not decrypt values into responses.
- `POST /api/connections/{id}/test` — connectivity check (DEMO hosts succeed under `FORMULAETL_DEMO=1`).
