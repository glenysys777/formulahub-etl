# Production evidence log

Claims in sales/README are **not** evidence. Each row is a statement we are willing to make only with a command, git SHA, and date.

**Audit SHA (main / Phase A merge):** `cecb1af` (PR #4)  
**Phase B merge tip:** `f2d8b57`  
**Phase C branch tip:** *(this PR — fill after commit)*  
**Agent run date:** 2026-09-14  
**Python:** 3.12.3 · **Node:** 22.14.0 · **pytest:** 9.1.1

Fill status: `PROVEN` | `UNPROVEN` | `FAILED` | `EMPTY`

---

## A. Build and tests

| ID | Claim | Status | Command | Result | SHA | Date |
|----|-------|--------|---------|--------|-----|------|
| A1 | Pytest suite on `tests/` | PROVEN | `python3 scripts/seed_demo.py && python3 -m pytest tests -q` | **127 passed**, 1 skipped (`RUN_CSV_1M`), 183 warnings (pgpy), 9.37s. Includes Phase C CSV/PGP/S3/SFTP hardening tests. `FORMULAETL_DEMO=1` via conftest. Not live AWS/SFTP. | this PR | 2026-09-14 |
| A2 | Web production build | PROVEN **skipped this PR** | UI untouched | Phase A `npm run build` still stands; no `apps/web` changes in Phase C | Phase A | 2026-09-14 |
| A3 | GitHub Actions CI on `main` | PROVEN **absent** | `ls .github/workflows` | Still no workflow files | `cecb1af` | 2026-09-14 |
| A4 | Default env is demo | PROVEN | Read `tests/conftest.py` | Tests force `FORMULAETL_DEMO=1` | `cecb1af` | 2026-09-14 |
| A5 | CSV 10K streaming benchmark | PROVEN | `iter_csv_batches` on 10_000-row file, `batch_size=500` | **10_000 rows**, 107 789 bytes, peak_batch=500, **0.0137s**, ~728 668 rows/s. Peak batch bounded (no full-file list during iteration). | this PR | 2026-09-14 |

---

## B. Demo runs (fixtures, not customer systems)

| ID | Claim | Status | Command | Result | SHA | Date |
|----|-------|--------|---------|--------|-----|------|
| B1 | Flagship S3→PGP→Snowflake **demo** CLI | PROVEN **demo only** | `FORMULAETL_DEMO=1 python3 -m formulaetl.cli run demos/s3-pgp-snowflake/pipeline.json` | `status=success` (~115ms). S3 artifact path (no bytes); PGP decrypt → temp path; CSV stream/parse 13 rows; validate 10/3; Snowflake demo CSV + archive. | this PR | 2026-09-14 |
| B2 | Kafka→Databricks **demo** | PROVEN **demo only** | pytest integration | Green on this PR | this PR | 2026-09-14 |
| B3 | Lookup Join + Field Mapper demo | PROVEN **demo only** | pytest / CLI | Unchanged green | this PR | 2026-09-14 |
| B4 | Historical founder screenshots / sidecar JSON | PROVEN as **demo artifacts only** | `docs/artifacts/EVIDENCE.md` | Unchanged | `b162987` | 2026-09-14 |

---

## C. Live systems (customer-shaped)

Unchanged — all **UNPROVEN**. Live branches now have retries/timeouts/host-key (SFTP) and botocore retries + paginated list (S3); none executed against real endpoints in this PR.

---

## D. Architecture facts (code, not a passing test)

| ID | Claim | Status | Evidence | SHA | Date |
|----|-------|--------|----------|-----|------|
| D1 | Runner still sequential in-process | PROVEN | `PipelineRunner.run` topological loop; no workers | this PR | 2026-09-14 |
| D2 | File hops use `ArtifactHandle` (S3/SFTP/PGP); runner does not copy `bytes` when a path exists | PROVEN | unchanged + Phase C large-PGP omits content/bytes when >64KiB plaintext | this PR | 2026-09-14 |
| D3 | Row-wise nodes can be fed `RowBatch`es; blocking/fan-out still materialize `list[dict]` | PROVEN | planner + adapter | this PR | 2026-09-14 |
| D4 | CSV reads via chunked `iter_csv_batches` / `DatasetHandle.from_csv_path` | PROVEN | `sdk/data.py`; A5; `test_csv_streaming.py` | this PR | 2026-09-14 |
| D5 | RunStore is process memory | PROVEN | unchanged | `cecb1af` | 2026-09-14 |
| D6 | No API authentication | PROVEN | unchanged | `cecb1af` | 2026-09-14 |
| D7 | Secrets may still live in node `config` JSON; refs supported for PGP | PROVEN | `private_key_ref` / `passphrase_ref` / `public_key_ref` resolve env; demo pipelines still use paths | this PR | 2026-09-14 |
| D8 | SFTP live defaults to `RejectPolicy` host keys | PROVEN | `sftp_source.py`; `test_sftp_host_key_default_is_reject` | this PR | 2026-09-14 |
| D9 | S3 prefix listing is paginated (`list_objects_v2` continuation) | PROVEN | `iter_s3_keys`; unit mock pagination | this PR | 2026-09-14 |

---

## E. Phase B — what landed (historical)

| ID | Claim | Status | Evidence |
|----|-------|--------|----------|
| E1–E5 | RowBatch / DatasetHandle / ArtifactHandle + planner feeds | PROVEN | Phase B PR #5 / `f2d8b57` |

---

## F. Phase C — bounded I/O (this PR)

| ID | Claim | Status | Evidence |
|----|-------|--------|----------|
| F1 | CSV: delimiter/encoding/quotes/headers; malformed fail\|skip\|reject; extra/missing columns; nulls; row numbers; Unicode | PROVEN | `csv_parser.py` + `iter_csv_batches`; `tests/unit/test_csv_streaming.py` |
| F2 | CSV 10K chunked parse with bounded peak batch | PROVEN | A5 + `test_csv_10k_*` |
| F3 | CSV 1M optional soak | PROVEN **skipped by default** | `@pytest.mark.slow` + `RUN_CSV_1M=1`; not run in default CI time budget |
| F4 | PGP: path/temp hop; wrong key / corrupt errors; no passphrase in logs; key refs | PROVEN | `test_pgp_hardening.py` |
| F5 | PGP large plaintext omits artifact `content`/`bytes` | PROVEN | `test_pgp_large_file_stays_path_only` |
| F6 | SFTP: timeouts, retries, host-key reject default, password+key paths, streaming `get` | PROVEN (unit/mock) | `test_s3_sftp_hardening.py`; live E2E UNPROVEN |
| F7 | S3: botocore retries/timeouts, streaming `download_file`, paginated prefix list | PROVEN (unit/mock + demo) | same; live E2E UNPROVEN |
| F8 | Temp artifact cleanup after run | PROVEN | runner `_cleanup_temps` (Phase B; still used) |

### Remaining gaps (not this PR)

- Still **one process**. No async workers, no secrets vault, no auth.
- `pgpy` still loads ciphertext/plaintext blobs while decrypting (library limit); we only stop *passing* large payloads to the next node.
- Destinations still materialize full row lists. CSV parser still materializes `ComponentResult.rows` for the legacy adapter after streaming read.
- Live S3/SFTP/warehouse E2E still **UNPROVEN**.
- Not Spark, not K8s, not streaming Kafka.

---

## Notes

- Pytest **count** for Phase C: **127 passed**, 1 skipped (Phase B was 99; Phase A was 87).
- C-rows remain UNPROVEN.
- Readiness: CSV/local file I/O moves toward **ALPHA** (chunked + policy); S3/SFTP live code remains **ALPHA code / DEMO CI**.
