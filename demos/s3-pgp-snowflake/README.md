# Spectacular demo: S3 → PGP → CSV → Validate → Transform → Snowflake (demo) → Archive

See the pipeline definition in `pipeline.json`.

```bash
# from repo root
make seed
make demo
```

Expected: 10 good rows under `data/out/snowflake/`, 3 rejects under `data/rejects/`, encrypted source moved to `data/archive/`.
