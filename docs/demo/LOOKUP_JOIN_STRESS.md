# Lookup Join stress + Job Contexts — founder Soft-PASS

**Classification:** `LOCAL/DEMO Soft-PASS` only. Not LIVE_EXTERNAL.  
**What it proves:** ~100k-row Lookup Join completes with measured RSS; `${…}` Job Context paths/keys substitute in the runner (and the same metadata is editable in Studio).  
**What it does not claim:** streaming join, Spark, partner cloud throughput.

## Mac pack / Desktop Studio

1. Unzip **FormulaHub-ETL-Mac** (or clone the repo).
2. Double-click **START-POSTGRES.command** only if you also want the LOCAL Postgres wedge — **not required** for this Soft-PASS.
3. From Terminal in the pack / repo root:

```bash
python3 -m pip install -e packages/runner -e packages/api
python3 -m pip install pytest
export FORMULAETL_DEMO=1

# Generate CSVs + run smoke (DEV) and prove QA/PROD path switch:
python3 scripts/lookup_join_stress.py --scale 1000 --context DEV --prove-contexts

# Soft-PASS scale (optional; a few minutes on a laptop):
RUN_BENCH=1 python3 scripts/lookup_join_stress.py \
  --scale 100000 --lookup-scale 5000 --context QA --require-run-bench \
  --out docs/evidence/lookup_join_stress_softpass_redacted.json
```

4. **Studio (web or Desktop shell):** Open `demos/lookup-join-contexts/pipeline.json` → right-rail **Job Contexts** → switch **DEV / QA / PROD** → confirm `orders_path` / `lookup_path` / `out_path` / `join_key` → **Run**. Active context can also be forced with `FORMULAETL_CONTEXT=QA`.

## Soft-PASS metrics (committed evidence)

See [`docs/evidence/lookup_join_stress_softpass_redacted.json`](../evidence/lookup_join_stress_softpass_redacted.json) and the Soft-PASS row in [`CUSTOMER001_EVIDENCE_MATRIX.md`](../CUSTOMER001_EVIDENCE_MATRIX.md).

| Metric | Meaning |
|--------|---------|
| `scale_left` / `scale_lookup` | Generated CSV sizes |
| `rows_join_out` | Lookup Join output rows |
| `elapsed_s` | Wall time (child process) |
| `peak_rss_mb` | Child `ru_maxrss` (fixture gen excluded) |

## Honesty notes

- CSV sources may stream; **Lookup Join materializes** left + lookup.
- Prefer partner volumes in the thousands–low hundreds of thousands on a laptop; millions → RAM risk (matrix still says Partial for unbounded join).
- No competitor brand names; no new connectors.
