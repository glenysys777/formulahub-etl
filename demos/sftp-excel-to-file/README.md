# Demo: SFTP → Excel → File (+ SFTP mock upload)

**Honest demo:** with `FORMULAETL_DEMO=1` (or `host=demo`), `sftp_source` copies
`fixtures/sample/orders.xlsx` into staging — **no real SFTP wire**.
`sftp_destination` writes under `data/out/sftp_mock/` instead of uploading.

Real SFTP requires host/credentials (password or key) and `FORMULAETL_DEMO=0`.

```bash
make demo-sftp
# or
FORMULAETL_DEMO=1 python -m formulaetl.cli run demos/sftp-excel-to-file/pipeline.json
```
