# Production checklist (Customer #1 / design partner)

Use this before putting **real** credentials or customer data on a private deploy. Checkboxes are operator tasks — not CI claims.

## Must do

- [ ] `FORMULAETL_API_KEY` set; UI/scripts send the key
- [ ] `FORMULAETL_DEMO=0` only when intentionally hitting live systems
- [ ] Prefer split worker (`FORMULAETL_EMBEDDED_WORKER=0` + `make worker`) on a host that can reach data sources
- [ ] Secrets via `connection_id` / `env:` / `secret:` — no passwords in committed pipeline JSON
- [ ] Non-DEMO Fernet key (`FORMULAETL_SECRETS_KEY` or generated `data/.formulaetl_secrets_key` with tight file mode)
- [ ] `POST .../validate` clean (0 errors) on the pipeline version you will run
- [ ] `POST .../connections/{id}/test` against the **real** endpoint (manual)
- [ ] Backup plan for `formulaetl.db` + secrets key (`BACKUP.md`)
- [ ] Reverse proxy / firewall; do not expose open Community API to the internet

## Prove yourself (manual — not GitHub Actions)

- [ ] `python3 scripts/live_wedge_e2e.py --check` shows credentials ready (see [`LIVE_WEDGE.md`](./LIVE_WEDGE.md))
- [ ] `RUN_LIVE_WEDGE=1 FORMULAETL_DEMO=0 python3 scripts/live_wedge_e2e.py` succeeds; paste redacted JSON into `PRODUCTION_EVIDENCE.md` section C as **PROVEN** with SHA + date
- [ ] One live source read (S3 or SFTP) with partner credentials
- [ ] One live destination (Postgres or Snowflake INSERT) with evidence you accept
- [ ] Inspect `GET /api/runs/{id}` → `summary`, `node_runs`, `events` for that live run (if run via API)

## Do not claim yet

- [ ] “PRODUCTION Snowflake / Kafka streaming / Databricks Spark” — still DEMO/ALPHA in-repo
- [ ] SSO / Vault / multi-tenant HA / K8s operator / billing
- [ ] CI green = live cloud green (CI is pytest + optional web build under `DEMO=1` only)

## Readiness words

See `docs/PRODUCTION_READINESS.md`. Overall product for live connectors remains **DEMO** until you attach partner evidence. Control-plane bookkeeping + validate + optional API key + connections = **ALPHA** / design-partner path.
