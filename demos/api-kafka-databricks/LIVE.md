# Kafka Source + Databricks Job Trigger

## Demo (CI / local, no broker or workspace)

```bash
FORMULAETL_DEMO=1 make demo-kafka
# or: python -m formulaetl.cli run demos/api-kafka-databricks/pipeline.json
```

- **Kafka Source** reads `fixtures/sample/kafka_orders.jsonl` when `FORMULAETL_DEMO=1`, `brokers=demo`, or `demo=true`. Emits rows + logs (`KafkaSource [demo]: … N messages`).
- **Databricks Job** writes a Jobs API–shaped sidecar under `data/out/databricks_demo/` with nested `state.life_cycle_state` / `state.result_state` matching `jobs/runs/get`, plus `run_id`, `job_id`, `notebook_params`, `rows_passed`.

## Live (optional)

```bash
pip install 'formulaetl[kafka]'   # or: pip install confluent-kafka
export FORMULAETL_DEMO=0
# Kafka: set real brokers/topic/group_id (security=plain|ssl|sasl_plain)
# Databricks: workspace_host + token + job_id → POST /api/2.1/jobs/run-now
```

Flipping from demo → live is config/credentials only; sidecar + live poll both use the same Jobs state shape.
