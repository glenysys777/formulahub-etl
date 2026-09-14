# Current state matrix (code inspection)

Companion to `docs/PRODUCTION_READINESS.md`. Same audit SHA: `b162987c3667525fcffa75135bbab54e391855f5` (2026-09-14).

Status: **DEMO** | **ALPHA** | **ABSENT**. Risk: **blocker** | **high** | **medium** | **low**.

| FEATURE | STATUS | RISK | NEXT ACTION |
|---------|--------|------|-------------|
| In-process DAG, `list[dict]` + full `bytes` | DEMO | blocker | Phase B: bounded data plane (not Spark in this freeze) |
| Auth on API | ABSENT | blocker | Token/SSO before any live credentials |
| Secrets vault / env refs | ABSENT | blocker | Stop storing passwords in pipeline JSON |
| Durable run history | ABSENT (memory) | blocker | Persist `RunStore` |
| Global sync run lock | DEMO | high | Async jobs; per-pipeline lock |
| In-process cron | DEMO | high | Out-of-process scheduler |
| CI on GitHub | ABSENT | high | pytest + npm build workflow |
| Local CSV/Excel/file | ALPHA | medium | Size limits / chunking |
| Field Mapper + Lookup Join | ALPHA | medium | Keep; add size guards |
| PGP (pgpy) | ALPHA lib / DEMO keys | high (key handling) | No private keys in git for customers |
| S3 live | ALPHA code / DEMO CI | high | Partner proof only |
| SFTP live | ALPHA code / DEMO CI | high | Partner proof only |
| Postgres/MySQL live | ALPHA code / DEMO CI | high | Partner proof only |
| Snowflake live | DEMO (CSV sidecar) | blocker if sold as warehouse | Do not sell until COPY evidence |
| Kafka “streaming” | DEMO batch fixture | blocker if sold as stream | Relabel as batch pull |
| Databricks Spark runtime | ABSENT (job trigger only) | blocker if sold as Spark | Keep honesty docs |
| AI builder | DEMO heuristic | medium | Do not auto-run unreviewed graphs on prod data |
| Hosted full ETL (API+runner) | ABSENT (Vercel UI only) | high | Document; don’t imply Vercel runs jobs |
| Control vs data plane split | ABSENT | blocker for Customer #1 scale | See `architecture/CONTROL_DATA_PLANE.md` |
| New connectors / Talend importer / billing / K8s / Spark | ABSENT | — | **Do not add** |

Phase B should start at the **blocker** rows, not new palette icons.
