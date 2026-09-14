# FormulaHub ETL — How to build each major use case

**Product:** FormulaHub ETL (Lynkx) · [formulahub.io/etl](https://formulahub.io/etl)  
**Build pattern every time:** **AI Build** (optional scaffold) → **Field Mapper / Discover schema** → **Run**.

Local: UI `http://127.0.0.1:18766` · API `http://127.0.0.1:18765` · `FORMULAETL_DEMO=1` for mocks.

---

## Shared steps (AI Build + Field Mapper + Run)

1. **AI Build** — paste an English description of the pipeline → graph appears (LLM if keyed; else offline heuristic). Edit nodes freely.  
2. **Discover schema** — on a source (Excel, file, API demo, DB demo), click **Discover schema** so columns + types populate.  
3. **Field Mapper** — open Field Mapper → **Input · Variables · Output**; drag links, add Variables, auto-map, or edit expressions. To merge two sources, use **Lookup Join** first.  
4. **Run** — **Run pipeline**; check sidebar metrics, logs, rejects, and output paths under `data/out/`.

---

## 1) Encrypted file drop → warehouse

**What it is:** Ingest an encrypted object store drop, decrypt, parse, validate, transform, load good rows, archive the source, isolate rejects.

**Components:** `s3_source` → `pgp_decrypt` → `csv_parser` → `schema_validate` → `transform` → `snowflake_destination` → `archive_files` (+ rejects from validate)

**How to build:**
1. **AI Build** prompt: *“Read encrypted files from S3, decrypt using PGP, validate columns, reject invalid records, transform dates, load good records into Snowflake and archive processed files.”*  
2. Or **Load demo** (`demos/s3-pgp-snowflake`).  
3. Click Validate / Transform / Snowflake nodes to inspect params.  
4. **Run** — expect ~10 good / ~3 rejects in demo mode.

**Honesty:** S3 + Snowflake default to local mocks in demo mode.

---

## 2) Excel / spreadsheet → clean file load

**What it is:** Read a business spreadsheet, normalize headers, cast types, validate, write CSV and/or Excel.

**Components:** `excel_source` → `column_map` or Field Mapper → `transform` → `schema_validate` → `local_file_destination` / `excel_destination`

**How to build:**
1. **AI Build:** *“Read orders from Excel, map columns, cast dates and amounts, validate, write CSV and Excel.”*  
2. Or load `demos/excel-to-file`.  
3. On Excel Source → **Discover schema** (Orders sheet).  
4. Open **Field Mapper** / Schema Map → rename columns.  
5. **Run** → `data/out/excel_orders.csv` (+ xlsx if configured).

---

## 3) Core visual map path (Excel → map → filter → sort → aggregate)

**What it is:** Classic visual ETL shaping: map with expressions, filter, sort, aggregate, land a file.

**Components:** `excel_source` → Field Mapper → `filter` → `sort` → `aggregate` → `local_file_destination`

**How to build:**
1. Load the **core path** demo from the UI (Excel → Field Mapper → Filter → Sort → Aggregate → File).  
2. Open **Field Mapper** — show expression maps (e.g. amount scale, `upper(...)`).  
3. Optionally Discover schema from upstream Excel.  
4. **Run** — inspect aggregated CSV.

---

## 4) HTTP / REST API → map → transform → load

**What it is:** Pull JSON from an API whose field names don’t match your schema; normalize; validate; land a file (or swap destination).

**Components:** `http_api_source` → `column_map` / Field Mapper → `transform` → `schema_validate` → `local_file_destination`

**How to build:**
1. **AI Build:** *“GET orders from a REST API, rename orderId and amt, cast dates, validate, write CSV.”*  
2. Or load `demos/api-map-transform`.  
3. Discover / map fields (`orderId` → `order_id`, etc.).  
4. **Run** → `data/out/api_orders.csv`.

**Honesty:** Demo mode loads `fixtures/sample/api_orders.json` for example.com / `demo=true`.

---

## 5) SFTP → Excel/file → load (+ optional SFTP out)

**What it is:** Partner drops a spreadsheet on SFTP; you stage, parse, map, write local file and optionally push back.

**Components:** `sftp_source` → `excel_source` / parser → map → `local_file_destination` (+ optional `sftp_destination`)

**How to build:**
1. **AI Build:** *“Pull Excel from SFTP, map columns, write CSV, optionally upload result via SFTP.”*  
2. Or load `demos/sftp-excel-to-file` / `make demo-sftp`.  
3. Discover schema on Excel after staging.  
4. **Run**.

**Honesty:** Demo copies fixtures into staging and writes `data/out/sftp_mock/` — no real SFTP wire until `FORMULAETL_DEMO=0` + credentials.

---

## 6) Database (Postgres shape) → file

**What it is:** Extract from a DB-shaped source and land a file (or write back via Postgres destination).

**Components:** `postgres_source` → (optional map/transform) → `local_file_destination` / `postgres_destination`

**How to build:**
1. **AI Build:** *“Read rows from Postgres, write CSV.”*  
2. Or load `demos/db-to-file` / `make demo-db`.  
3. Inspect source params (table / query).  
4. **Run**.

**Honesty:** Demo reads SQLite `data/demo.db` (seeded by `make seed`), not live Postgres.

---

## 7) Reject handling & schema validation

**What it is:** Bad rows must not poison the load; good path continues; rejects are inspectable.

**Components:** `schema_validate` (plus any upstream source/parse) → good edges continue; rejects file / metrics

**How to build:**
1. Use the S3→PGP→Snowflake demo (Beat 3 in [DEMO_SCRIPT.md](./DEMO_SCRIPT.md)).  
2. Click **Schema Validate** — show column/type rules.  
3. **Run** — call out good vs reject counts.

---

## 8) Custom per-row logic (Python Row)

**What it is:** Escape hatch when expressions aren’t enough — small sandboxed Python over row/rows.

**Components:** upstream source/map → `python_row` → destination

**How to build:**
1. Load `demos/python-row-flex` (API → map → Python Row → File).  
2. Open Python Row params — show restricted script (no open/network/os).  
3. **Run**.

**Honesty:** Sandboxed Python only — not unrestricted host scripting.

---

## 9) PGP encrypt / decrypt paths

**What it is:** Decrypt inbound partner files or encrypt outbound drops.

**Components:** `pgp_decrypt` / `pgp_encrypt` (+ file/S3/SFTP around them)

**How to build:**
1. Spectacular demo already includes decrypt.  
2. For encrypt-out: AI Build *“Encrypt CSV with PGP and write to file/SFTP.”* wire `pgp_encrypt` before destination.  
3. Demo keys live under `fixtures/keys/` after `make seed`.

---

## 10) Two sources → Lookup Join → Field Mapper

**What it is:** Merge a primary stream with a lookup (customers, dims, reference file), then apply Variables + output column logic.

**Components:** source A + source B → `lookup_join` → Field Mapper → destination

**How to build:**
1. Wire **primary** → Lookup Join **left/in** handle, **lookup** → **right** handle (or set Lookup file).  
2. Set primary/lookup join keys; choose join type (`left` / `inner` / `right` / `full`) and match mode (`all` / `first`).  
3. Open **Field Mapper** — add Variables in the middle pane, map Output columns.  
4. **Run**. Demo: `demos/lookup-join-mapper`.

---

## 11) XML / JSON records → rows

**What it is:** Nested or tagged payloads flattened into tabular rows for mapping and load.

**Components:** `xml_parser` or `json_parser` → Field Mapper / Transform → destination

**How to build:**
1. **AI Build:** *“Parse XML records into rows, map fields, write CSV.”* (or JSON array path).  
2. Set record tag / xpath-lite or `json_path`.  
3. Discover / map → **Run**.

---

## Quick reference — demos folder

| Use case | Demo path |
|----------|-----------|
| Encrypted drop → warehouse | `demos/s3-pgp-snowflake` |
| Excel → file | `demos/excel-to-file` |
| Core Field Mapper path | UI core-path demo / `demos/` core path |
| Lookup Join + Variables | `demos/lookup-join-mapper` |
| API → map → file | `demos/api-map-transform` |
| SFTP → Excel → file | `demos/sftp-excel-to-file` |
| DB → file | `demos/db-to-file` |
| Python Row | `demos/python-row-flex` |

Component catalog & limits: [COMPONENTS.md](./COMPONENTS.md).
