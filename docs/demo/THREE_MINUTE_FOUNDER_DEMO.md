# Three-minute founder demo — SFTP/S3 → … → Snowflake + AI

**Audience:** Founder / design-partner intro  
**Length:** ~3 minutes talking  
**Mode:** `FORMULAETL_DEMO=1` unless you explicitly have LIVE credentials  
**Honesty first:** Everything below is a **DEMO / LOCAL** proof unless you say “LIVE” and mean `FORMULAETL_DEMO=0` against real systems.

Prereqs: `make install && make seed`; API `:18765`; UI `:18766`.

---

## Minute 0:00–0:20 — Frame (no oversell)

**Say:**  
“FormulaHub ETL is open-core visual ETL — canvas on top, Python DAG underneath. I’m going to run the flagship path on **demo fixtures**: encrypted object → decrypt → parse → validate with rejects → map → **Snowflake demo sidecar** → archive. That is **not** your cloud yet. Same graph shape flips to live when credentials and `FORMULAETL_DEMO=0` are set — and we only call that proven after a real run.”

**Do:** Full-screen Studio. Do not open pricing slides.

---

## Minute 0:20–1:20 — Run the wedge

**Load:** demo `s3-pgp-snowflake` (or **Load demo**).

**Say:**  
“Source here is **mock S3** under `data/s3` in demo mode — same node type as live boto3. PGP is real crypto on demo keys. Schema validate isolates bad rows. Destination writes a CSV that **looks like** a Snowflake load under `data/out/snowflake` — labeled demo in the load JSON. Archive moves the processed file.”

**Click:** **Run pipeline**. Point at rows / rejects / duration.

**Say:**  
“Good rows and rejects separately — that’s the ETL beat. CI and this demo never talk to AWS or Snowflake. Green local run ≠ LIVE proven.”

Optional one-liner if they ask SFTP:  
“SFTP is the same story — demo copies fixtures; live uses paramiko when we have their host and `DEMO=0`.”

---

## Minute 1:20–2:10 — AI prompt → same shape

**Open AI Build.** Paste:

> Read encrypted files from SFTP or S3, decrypt with PGP, parse CSV, validate columns and reject bad rows, map fields, load into Snowflake, and archive processed files.

**Say:**  
“English → editable graph. Offline heuristic works without an LLM key; with a key we get richer maps. We **review** before any live data — AI does not get to skip validate or secrets hygiene.”

**Do:** Land on canvas. If graph matches the demo, say “Same wedge you just ran.”

---

## Minute 2:10–2:45 — Databricks / control plane (if asked)

**Say only if prompted:**  
“Databricks Job and SQL nodes **orchestrate** their workspace — Jobs API / Statement API. Spark compute stays in Databricks. Demo writes Jobs-shaped sidecars. LIVE Databricks is separate proof with a workspace token — also UNPROVEN in CI.”

Do **not** demo Spark notebooks inside FormulaETL — we don’t embed Spark.

---

## Minute 2:45–3:00 — Close + next step

**Say:**  
“What you saw is sellable as a **design-partner implementation**: we wire your SFTP or S3, keys, and warehouse, run `DEMO=0`, and paste live evidence. Snowflake high volume needs staging + `COPY INTO` — not the current insert path — and we won’t claim it until tested. Community product stays Apache 2.0; we sell the proof engagement.”

**Leave-behinds (internal/partner):**  
`docs/CUSTOMER001_EVIDENCE_MATRIX.md` · `docs/design-partner/LIVE_WEDGE.md` · `docs/PROVE_SELL_FREEZE.md`

---

## Forbidden lines in this demo

- “This loaded into Snowflake production.”  
- “CI proves AWS / Snowflake / Databricks.”  
- “We’re a Spark engine / streaming Kafka platform.”  
- Quoting website list prices for Cloud/Enterprise as shipped.

## Related scripts

- Shorter GTM: `docs/sales/DEMO_SCRIPT.md` (90s)  
- Live partner runbook: `docs/design-partner/LIVE_WEDGE.md`
