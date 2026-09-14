# Founder evidence — Kafka / Databricks / Scheduler / Palette

## Screenshots (real app UI)
| File | What it proves |
|------|----------------|
| `screenshots/01-palette-canvas-pipeline.webp` | Apple-light canvas + colorful original palette icons + pipeline |
| `screenshots/02-field-mapper-premium.webp` | Premium Field Mapper (no competitor names) |
| `screenshots/03-schedule-panel.webp` | Cron schedule UI (enable / cron / timezone) |
| `screenshots/04-full-ui-overview.webp` | Full composition |
| `screenshots/07-run-logs-ui.webp` | **Real app** after Run: Last run success metrics + Logs with KafkaSource / DatabricksJob |

Also mirrored under `/opt/cursor/artifacts/screenshots/`.

## Runnable evidence
| File | What it proves |
|------|----------------|
| `screenshots/05-run-evidence.json` | Live API run: Kafka 8 → map 8 → Databricks 8; logs include KafkaSource/DatabricksJob |
| `screenshots/06-databricks-jobs-api-sidecar.json` | Jobs API–shaped sidecar (`state.life_cycle_state` / `result_state`) |

## Pytest
`84 passed` including `tests/unit/test_evidence_kafka_databricks_scheduler.py` (rows+logs+sidecar+scheduler→`/api/runs` history). API + S3 paths covered in the same suite.

Live Kafka/Databricks: see `demos/api-kafka-databricks/LIVE.md`.
