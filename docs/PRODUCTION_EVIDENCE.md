# Production evidence log

Claims in sales/README are **not** evidence. Each row is a statement we are willing to make only with a command, git SHA, and date.

**Audit SHA (main / Phase A merge):** `cecb1af` (PR #4)  
**Phase B branch tip:** `92b3d7a` (`cursor/batch-stream-abstraction-d316`)  
**Agent run date:** 2026-09-14  
**Python:** 3.12.3 · **Node:** 22.14.0 · **pytest:** 9.1.1

Fill status: `PROVEN` | `UNPROVEN` | `FAILED` | `EMPTY`

---

## A. Build and tests

| ID | Claim | Status | Command | Result | SHA | Date |
|----|-------|--------|---------|--------|-----|------|
| A1 | Pytest suite on `tests/` | PROVEN | `python3 scripts/seed_demo.py && python3 -m pytest tests -v --tb=short` | **99 passed**, 163 warnings (pgpy deprecations), 10.05s. Includes 12 new Phase B unit tests. `FORMULAETL_DEMO=1` via conftest. Not live AWS/Kafka/Snowflake. | this PR | 2026-09-14 |
| A2 | Web production build | PROVEN **skipped this PR** | UI untouched | Phase A `npm run build` still stands; no `apps/web` changes in Phase B | Phase A | 2026-09-14 |
| A3 | GitHub Actions CI on `main` | PROVEN **absent** | `ls .github/workflows` | Still no workflow files | `cecb1af` | 2026-09-14 |
| A4 | Default env is demo | PROVEN | Read `tests/conftest.py` | Tests force `FORMULAETL_DEMO=1` | `cecb1af` | 2026-09-14 |

---

## B. Demo runs (fixtures, not customer systems)

| ID | Claim | Status | Command | Result | SHA | Date |
|----|-------|--------|---------|--------|-----|------|
| B1 | Flagship S3→PGP→Snowflake **demo** CLI | PROVEN **demo only** | `FORMULAETL_DEMO=1 python3 -m formulaetl.cli run demos/s3-pgp-snowflake/pipeline.json` | `status=success`. Planner: S3 `feed=none`, PGP/CSV `feed=artifact`, validate `materialized_rows` (fan-out), transform/logger `feed=batches`, snowflake `materialized_rows`, archive `artifact`. S3 hashed file in place (1074 bytes, sha256 logged) — **no `artifacts["bytes"]`**. PGP wrote `data/tmp/<run>/pgp_decrypt.out`; CSV parsed 13 rows from that path. Validate 10/3. Demo Snowflake CSV + archive move. Metrics `rows_in=49` still **summed node counts**. | this PR | 2026-09-14 |
| B2 | Kafka→Databricks **demo** CLI | PROVEN **demo only** (Phase A; pytest still covers) | `tests/integration/test_kafka_databricks_pipeline.py` | Integration test green on this PR | this PR | 2026-09-14 |
| B3 | Lookup Join + Field Mapper demo | PROVEN **demo only** | `FORMULAETL_DEMO=1 python3 -m formulaetl.cli run demos/lookup-join-mapper/pipeline.json` | `status=success`. Lookup join `feed=materialized_rows` (blocking); tMap `feed=batches`; dest `materialized_rows`. Same silent-null on `total='abc'`. | this PR | 2026-09-14 |
| B4 | Historical founder screenshots / sidecar JSON | PROVEN as **demo artifacts only** | `docs/artifacts/EVIDENCE.md` | Unchanged | `b162987` | 2026-09-14 |

---

## C. Live systems (customer-shaped)

Unchanged from Phase A — all **UNPROVEN**. Live S3 now *would* `download_file` to a temp path (not `Body.read()` into RAM), but that branch was not executed here.

---

## D. Architecture facts (code, not a passing test)

| ID | Claim | Status | Evidence | SHA | Date |
|----|-------|--------|----------|-----|------|
| D1 | Runner still sequential in-process | PROVEN | `PipelineRunner.run` topological loop; no workers | this PR | 2026-09-14 |
| D2 | File hops use `ArtifactHandle` (S3/SFTP/PGP); runner does not copy `bytes` when a path exists | PROVEN | `sdk/data.py` `ArtifactHandle`; `sdk/adapter.py` `apply_upstream_to_component`; S3/SFTP no longer put `bytes` in artifacts | this PR | 2026-09-14 |
| D3 | Row-wise nodes can be fed `RowBatch`es; blocking/fan-out still materialize `list[dict]` | PROVEN | `engine/planner.py` `decide_feed`; flagship logs; `test_runner_feeds_filter_in_bounded_batches` | this PR | 2026-09-14 |
| D4 | Legacy `run(ctx, list[dict])` still works | PROVEN | Default `LEGACY` capabilities + `run_legacy` / `run_batched` adapters; 99 pytest green | this PR | 2026-09-14 |
| D5 | RunStore is process memory | PROVEN | unchanged | `cecb1af` | 2026-09-14 |
| D6 | No API authentication | PROVEN | unchanged | `cecb1af` | 2026-09-14 |
| D7 | Secrets live in node `config` JSON | PROVEN | unchanged | `cecb1af` | 2026-09-14 |
| D8 | Kafka live path is a bounded batch pull | PROVEN | unchanged | `cecb1af` | 2026-09-14 |
| D9 | Databricks component is Jobs API orchestration | PROVEN | unchanged | `cecb1af` | 2026-09-14 |
| D10 | Snowflake default path writes local CSV | PROVEN | unchanged | `cecb1af` | 2026-09-14 |

---

## E. Phase B — what this PR proved

| ID | Claim | Status | Evidence |
|----|-------|--------|----------|
| E1 | Neutral data types exist: `RowBatch`, `DatasetHandle`, `ArtifactHandle` | PROVEN | `packages/runner/formulaetl/sdk/data.py` + unit tests |
| E2 | Planner uses capabilities for real feed decisions (`none` / `artifact` / `batches` / `materialized_rows`) | PROVEN | `engine/planner.py`; logs on B1; `test_plan_flagship_like_graph` |
| E3 | `list[dict]` adapter: `dataset.materialize()` / `run_legacy` / `run_batched` calling existing `run()` | PROVEN | `sdk/adapter.py`; `test_legacy_component_run_via_adapter` |
| E4 | Migrated path: S3 → PGP → CSV off giant byte arrays (temp/path + checksum) | PROVEN | B1 logs; `test_s3_source_demo` asserts `"bytes" not in artifacts` |
| E5 | Remaining components keep `list[dict]` `run()` | PROVEN | pytest 99; destinations still `requires_materialization` |

### Remaining gaps (not this PR)

- Still **one process**. No async workers (Phase D), no secrets/vault (Phase F).
- `pgpy` still loads the full ciphertext/plaintext while decrypting; we only stopped *passing* those bytes to the next node.
- Destinations (Snowflake demo, local file) still materialize the full row list. No spill-to-disk for `DatasetHandle`.
- Excel / JSON / XML / HTTP still whole-object or whole-list. Phase C file-component work.
- Fan-out (schema validate rejects vs good) forces materialization so both edges can replay.
- Output row datasets from CSV `run()` are still materialized into `ComponentResult.rows` for the adapter.
- Live S3/SFTP/warehouse E2E still **UNPROVEN**.
- Not Spark, not K8s, not streaming Kafka.

---

## Notes

- Pytest **count** for Phase B: **99 passed** (Phase A was 87; +12 abstraction/planner/adapter tests).
- C-rows remain UNPROVEN.
