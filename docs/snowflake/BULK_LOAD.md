# Snowflake bulk load — honesty + proposed architecture

**Status:** Gap documented. **Not implemented** in this PROVE+SELL pass.  
**Code today:** `packages/runner/formulaetl/components/dest_snowflake.py`  
**Audited tip:** `067b80d`

---

## What ships today

| Mode | Behavior | Proven? |
|------|----------|---------|
| `FORMULAETL_DEMO=1` (default) | Streams `RowBatch`es to CSV + `.load.json` under `data/out/snowflake/` | **DEMO / LOCAL** — not a warehouse |
| Live (`FORMULAETL_DEMO=0` + `account`) | Materializes rows → `INSERT INTO … VALUES` via `cursor.executemany` | **Code path exists; LIVE UNPROVEN in CI** |

There is **no** `PUT` / internal stage / `COPY INTO` path in the tree. Demo streaming does **not** make live loads high-volume safe.

From `dest_snowflake.py` (live branch):

- Requires optional extra `snowflake-connector-python` (`pip install formulaetl[snowflake]`).
- Builds `INSERT INTO {table} ({cols}) VALUES (%s, …)` and `executemany` over the full cleaned row list.
- `consume_dataset` for live falls back to `dataset.materialize()` then `run()` — so the live path **drops streaming** and holds rows in RAM.
- Table/column names are interpolated into SQL (not warehouse-grade DDL hygiene).

**Do not claim high-volume Snowflake** until a design-partner run proves a bulk path with tests + evidence.

---

## Gap (harsh)

1. **Row-by-row INSERT** does not scale; warehouse best practice is file stage + `COPY INTO`.
2. **Live path materializes** the full dataset — fights the LOCAL/DEMO streaming work in Phase Perf.
3. **No** retry/idempotency/merge/schema evolution on live insert.
4. **No LIVE evidence** in `PRODUCTION_EVIDENCE.md` §C (C5/C6 remain UNPROVEN).
5. Demo CSV “load” must never be described as production Snowflake.

---

## Proposed architecture (follow-on — implement later with tests)

```
FormulaETL worker (data plane next to files)
  │
  ├─ stream RowBatches → local/GZIP CSV or Parquet files (spill, bounded RAM)
  │
  ├─ PUT files → Snowflake internal stage  (or external stage on customer S3)
  │     PUT file://… @~/%RUN_ID%/
  │
  └─ COPY INTO db.schema.table
        FROM @~/%RUN_ID%/
        FILE_FORMAT = (TYPE=CSV …)
        ON_ERROR = 'ABORT_STATEMENT' | continue-with-rejects policy
```

### Design notes for the follow-on PR

| Concern | Recommendation |
|---------|----------------|
| Streaming | Keep `consume_dataset` for **both** demo and live; write chunk files, never full `list[dict]` |
| Auth | Connections + secret refs only; key-pair auth preferred over password for partners |
| Idempotency | Stage path includes `run_id`; optional truncate/load vs merge documented per pipeline |
| Rejects | Prefer validate/dedupe **before** COPY; use `VALIDATION_MODE` / error files only with explicit partner policy |
| Evidence | Mark LIVE PROVEN only after `RUN_LIVE_WEDGE` + Snowflake dest with measured row counts |
| Scope | One component enhancement + unit tests with connector mocked + one design-partner LIVE paste |

### Explicit non-goals for first bulk PR

- Snowpipe continuous ingest  
- Dynamic table / Streams & Tasks productization  
- Claiming “faster than Fivetran” without partner numbers  

---

## When to implement

Allowed under PROVE+SELL **only** if:

1. Partner volume makes `executemany` a known blocker, **and**
2. Implementation is small, tested, and evidence-logged, **and**
3. Sales copy still says UNPROVEN until a real account run succeeds.

Otherwise: leave code; sell the **engagement to build + prove COPY**, not a finished warehouse loader.

## Related

- Matrix: [`../CUSTOMER001_EVIDENCE_MATRIX.md`](../CUSTOMER001_EVIDENCE_MATRIX.md)
- Freeze: [`../PROVE_SELL_FREEZE.md`](../PROVE_SELL_FREEZE.md)
- Live harness: [`../design-partner/LIVE_WEDGE.md`](../design-partner/LIVE_WEDGE.md)
- Perf honesty: [`../PERFORMANCE.md`](../PERFORMANCE.md)
