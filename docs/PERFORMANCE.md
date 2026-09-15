# Performance — stream, don’t choke

FormulaHub’s claim: **handle huge enterprise files and millions of rows** with a hard memory ceiling — stream through hops instead of loading the whole working set into RAM. Studio should stay snappy while the data plane does that work.

This document is **LOCAL/DEMO** only. It is not live AWS / Snowflake / SFTP throughput.

## What was breaking

Our old runner kept **the whole file as Python objects in RAM**. At 1M rows the LOCAL/DEMO wedge sat at **~1.4 GiB RSS** and we skipped 10M as likely OOM.

Studio “slow” was a **separate** problem: React Flow + run polling + SchemaMapper SVG, not the data plane.

## What we do now (data plane)

1. **Bounded `RowBatch`es** (default `FORMULAETL_BATCH_SIZE=32768`).
2. **Lazy producer chain** — row-wise hops (`schema_validate`, `column_map`, `dedupe keep=first`) transform one batch at a time. No full `list[dict]` concat between hops.
3. **Streaming sinks** — demo Snowflake / local file write per batch (`consume_dataset`). They do not echo the load set back into RAM.
4. **Rejects fan-out** — side stream spills to JSONL so the main spine stays streaming.
5. **Large PGP** — `gpg` path-to-path decrypt when available (no Python ciphertext blob). `pgpy` remains the fallback for tiny fixtures.
6. **CSV** — large files stay a re-readable producer (line-scan for counts). Small files still materialize for Studio/tests.

This is still **one Python process, sequential DAG**. Not Spark. Not a warehouse COPY path.

## Knobs

| Env | Default | Meaning |
|-----|---------|---------|
| `FORMULAETL_BATCH_SIZE` | `32768` | Rows per `RowBatch` |
| `FORMULAETL_SPILL_THRESHOLD` | `25000` | Above this, `ComponentResult.rows` stays empty; use `dataset` |
| `FORMULAETL_STREAM_SPILL` | `1` | Keep spill helpers on (`0` disables JSONL reject spill) |
| `FORMULAETL_DEMO` | `1` | Fixture / mock S3 / snowflake-demo CSV |

```bash
make bench          # 10K + 100K + 1M → data/out/bench/local_wedge_results.json
make bench-10m      # optional 10M (BENCH_INCLUDE_10M=1)
```

Peak RSS is measured in a **child process** so fixture encrypt / prior scales do not inflate `ru_maxrss`.

## What is still DEMO / not claimed

- Mock S3 under `data/s3`, demo Snowflake **CSV** under `data/out`. **Not** live cloud.
- `keep=last` dedupe, sort, aggregate, lookup join still materialize. Lookup Join Soft-PASS (100k / optional 1M) is documented in `docs/evidence/lookup_join_stress_softpass_redacted.json` — RSS grows with both sides in RAM (`make bench-lookup-join`).
- Live Snowflake still `executemany` (not COPY).
- PGP via `gpg` is real crypto on demo keys — not a partner key-management story.
- 10M peak RSS is dominated by the **dedupe key set**, not a second full row copy. It completes; it is not a 400 MB job.

Numbers and SHA: `docs/PRODUCTION_EVIDENCE.md` §J.

## Studio (apps/web)

Cheap wins, not a rewrite: memoized `EtlNode`, skip unchanged `runVisual` refs, poll 500 ms, cap edge-flow CSS, `onlyRenderVisibleElements`, SchemaMapper scroll on rAF. Qualitatively: palette + canvas should stay usable at 50+ nodes; no multi-second freeze on Open/Run start from poll storms.
