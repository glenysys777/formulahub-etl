# Current state matrix (code inspection)

Companion to `docs/PRODUCTION_READINESS.md`. Phase A audit SHA: `b162987` / merged `cecb1af`. Phase B merge: `f2d8b57`. Phase C merge: `dce51a6`. Phase D+E: this PR (async queue + SQLite durable history + pipeline versions).

Status: **DEMO** | **ALPHA** | **ABSENT**. Risk: **blocker** | **high** | **medium** | **low**.

| FEATURE | STATUS | RISK | NEXT ACTION |
|---------|--------|------|-------------|
| In-process DAG; `DatasetHandle` / `ArtifactHandle`; legacy `list[dict]` adapter | ALPHA (types + planner + Phase C file I/O) / DEMO (dest materializes) | high | Keep sequential runner honesty; not Spark |
| Async run accept (202 queued) + worker claim | ALPHA | medium | Prefer split worker in partner deploys (`make worker`) |
| Auth on API | ABSENT | blocker | Token/SSO before any live credentials |
| Secrets vault / env refs | ABSENT (PGP key/passphrase *refs* only) | blocker | Stop storing passwords in pipeline JSON |
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
| AI builder | DEMO heuristic | medium | Do not auto-run unreviewed graphs on prod data |
| Hosted full ETL (API+runner) | ABSENT (Vercel UI only) | high | Document; don’t imply Vercel runs jobs |
| Control vs data plane split | ALPHA (queue + optional worker process) | high | Auth + private worker next; see `architecture/CONTROL_DATA_PLANE.md` |
| New connectors / Talend importer / billing / K8s / Spark | ABSENT | — | **Do not add** |

Phase D+E stops feature expansion: trust via async control plane + durable history only.
