# S3 → Databricks Job (demo)

Minimal orchestration path: pick up an object from the S3 demo mock, then trigger a Databricks job run (sidecar JSON).

```bash
FORMULAETL_DEMO=1 make seed
python3 -m formulaetl.cli run demos/s3-databricks/pipeline.json
```
