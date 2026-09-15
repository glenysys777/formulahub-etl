# Lookup Join + Job Contexts (LOCAL/DEMO Soft-PASS)

Two CSV sources → **Lookup Join** → Schema Map → CSV, with **DEV / QA / PROD** Job Contexts driving `${context.orders_path}`, `${context.lookup_path}`, `${context.out_path}`, and `${context.join_key}`.

**Honesty:** Lookup Join is an in-memory hash join (`BLOCKING_ROWS`). Soft-PASS proves scale + substitution — not a streaming join or LIVE cloud claim.

## Generate fixtures + run

```bash
# Smoke (1k left)
FORMULAETL_DEMO=1 python3 scripts/lookup_join_stress.py --scale 1000 --context DEV --prove-contexts

# Soft-PASS scale (100k left / 5k lookup) — gated
RUN_BENCH=1 FORMULAETL_DEMO=1 python3 scripts/lookup_join_stress.py \
  --scale 100000 --context QA --require-run-bench --prove-contexts \
  --out docs/evidence/lookup_join_stress_softpass_redacted.json
```

Or after fixtures exist:

```bash
FORMULAETL_DEMO=1 FORMULAETL_CONTEXT=QA \
  python3 -m formulaetl.cli run demos/lookup-join-contexts/pipeline.json
```

## Studio

Open this pipeline in FormulaHub Studio → **Job Contexts** rail → switch DEV/QA/PROD → Save → Run. Paths and join key resolve from the active set.

Founder Mac pack / Desktop: see [`docs/demo/LOOKUP_JOIN_STRESS.md`](../../docs/demo/LOOKUP_JOIN_STRESS.md).
