# Kafka → Field Mapper → Databricks Job (demo)

End-to-end company pattern without a real Kafka cluster or Databricks workspace.

```bash
FORMULAETL_DEMO=1 make seed
python3 -m formulaetl.cli run demos/api-kafka-databricks/pipeline.json
```

| Node | What demo does |
|------|----------------|
| **Kafka Source** | Reads `fixtures/sample/kafka_orders.jsonl` |
| **Field Mapper** | Renames / keeps order fields |
| **Databricks Job** | Writes a SUCCESS sidecar under `data/out/databricks_demo/` |

Live Kafka needs `pip install formulaetl[kafka]` (or `confluent-kafka`) and `FORMULAETL_DEMO=0`. Live Databricks needs workspace host + token.
