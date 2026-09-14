# Current state matrix (code inspection)

Companion to `docs/PRODUCTION_READINESS.md`. Phase A audit SHA: `b162987` / merged `cecb1af`. Phase B merge: `f2d8b57`. Phase C merge: `dce51a6`. Phase D+E: `1b82aa5`. Phase F: this PR (connections + secret refs + optional API key).

Status: **DEMO** | **ALPHA** | **ABSENT**. Risk: **blocker** | **high** | **medium** | **low**.

| FEATURE | STATUS | RISK | NEXT ACTION |
|---------|--------|------|-------------|
| In-process DAG; `DatasetHandle` / `ArtifactHandle`; legacy `list[dict]` adapter | ALPHA (types + planner + Phase C file I/O) / DEMO (dest materializes) | high | Keep sequential runner honesty; not Spark |
| Async run accept (202 queued) + worker claim | ALPHA | medium | Prefer split worker in partner deploys (`make worker`) |
| Auth on API | ALPHA (optional `FORMULAETL_API_KEY`) / open when unset | medium (was blocker) | Keep key on for any live credentials; SSO later |
| Secrets / Connections | ALPHA (env + local Fernet store + `connection_id`) | medium (was blocker) | Prefer refs; migrate inline secrets; not enterprise vault |
| Durable run history (SQLite) | ALPHA | medium | Postgres backend later; same schema shapes |
| Immutable pipeline versions pinned on run | ALPHA | medium | UI version picker (optional) |
| Global sync run lock | ABSENT (removed) | — | Concurrent claimed runs OK |
| In-process cron (enqueue-only) | DEMO / ALPHA bookkeeping | high | Out-of-process scheduler later |
| CI on GitHub | ABSENT | high | pytest + npm build workflow |
| Local CSV (chunked + malformed policy) | ALPHA | medium | Spill for multi-million; keep adapter honesty |
| Field Mapper + Lookup Join | ALPHA | medium | Keep; add size guards |
| PGP (pgpy) path/temp + refs | ALPHA lib / DEMO keys | high (key handling) | No private keys in git for customers; prefer refs |
| S3 live (retries, paginated list, stream download) | ALPHA code / DEMO CI | high | Partner proof only |
| SFTP live (timeouts, retries, host-key reject) | ALPHA code / DEMO CI | high | Partner proof only |
| Postgres/MySQL live | ALPHA code / DEMO CI | high | Partner proof only |
| Snowflake live | DEMO (CSV sidecar) | blocker if sold as warehouse | Do not sell until COPY evidence |
| Kafka “streaming” | DEMO batch fixture | blocker if sold as stream | Relabel as batch pull |
| Databricks Spark runtime | ABSENT (job trigger only) | blocker if sold as Spark | Keep honesty docs |
| AI builder | DEMO heuristic | medium | Do not auto-run unreviewed graphs on prod data; secrets stripped |
| Hosted full ETL (API+runner) | ABSENT (Vercel UI only) | high | Document; don’t imply Vercel runs jobs |
| Control vs data plane split | ALPHA (queue + optional worker + secret resolve) | high | Private worker + API key for partners |
| New connectors / Talend importer / billing / K8s / Spark | ABSENT | — | **Do not add** |

Phase F stops feature expansion: trust via connections + secret refs + optional API key only. See `docs/CONNECTIONS.md`.
