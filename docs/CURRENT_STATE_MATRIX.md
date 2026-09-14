# Current state matrix (code inspection)

Companion to `docs/PRODUCTION_READINESS.md`. Phase A audit SHA: `b162987` / merged `cecb1af`. Phase B merge: `f2d8b57`. Phase C (this PR) hardens CSV/PGP/S3/SFTP bounded I/O.

Status: **DEMO** | **ALPHA** | **ABSENT**. Risk: **blocker** | **high** | **medium** | **low**.

| FEATURE | STATUS | RISK | NEXT ACTION |
|---------|--------|------|-------------|
| In-process DAG; `DatasetHandle` / `ArtifactHandle`; legacy `list[dict]` adapter | ALPHA (types + planner + Phase C file I/O) / DEMO (still one process; dest materializes) | blocker | Phase D: workers; not Spark |
| Auth on API | ABSENT | blocker | Token/SSO before any live credentials |
| Secrets vault / env refs | ABSENT (PGP key/passphrase *refs* only) | blocker | Stop storing passwords in pipeline JSON |
| Durable run history | ABSENT (memory) | blocker | Persist `RunStore` |
| Global sync run lock | DEMO | high | Async jobs; per-pipeline lock |
| In-process cron | DEMO | high | Out-of-process scheduler |
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
| Control vs data plane split | ABSENT | blocker for Customer #1 scale | See `architecture/CONTROL_DATA_PLANE.md` |
| New connectors / Talend importer / billing / K8s / Spark | ABSENT | — | **Do not add** |

Phase C should keep the Customer #1 wedge (SFTP/S3 → PGP → CSV → validate → warehouse) honest — no new connectors.
