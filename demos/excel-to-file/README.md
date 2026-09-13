# Demo: Excel → Map → Transform → CSV + Excel

Reads `fixtures/sample/orders.xlsx` (sheet **Orders**), renames spreadsheet headers,
casts dates/amounts, validates schema, writes:

- `data/out/excel_orders.csv`
- `data/out/excel_orders.xlsx`

No cloud credentials required (`FORMULAETL_DEMO=1`).

```bash
make demo-excel
# or
FORMULAETL_DEMO=1 python -m formulaetl.cli run demos/excel-to-file/pipeline.json
```
