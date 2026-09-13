# FormulaHub ETL — 90-Second Live Demo Script

**Goal:** Show visual ETL that feels familiar, runs real Python, and handles rejects — then wow with AI Build.  
**Brand:** FormulaHub ETL (Lynkx) · [formulahub.io/etl](https://formulahub.io/etl)  
**Prereqs:** API on `http://127.0.0.1:18765`, UI on `http://127.0.0.1:18766`, demo seeded (`make seed`).  
**Honest framing:** Snowflake/S3 default to local mocks in demo mode so anyone can run without cloud accounts. Real connectors exist behind the same interfaces when credentials + `FORMULAETL_DEMO=0` are set.

**Total target:** ~90 seconds talking. Practice once; don’t rush the reject beat.

---

## Setup (before the call — silent)

1. Open UI full-screen; clear unrelated tabs.  
2. Confirm API healthy.  
3. Have the AI Build prompt ready on clipboard (see Beat 5).  
4. Optional: second window with `docs/sales/ONE_PAGER.md` if they ask for leave-behinds.

---

## Beat 1 — Frame (0:00–0:10)

**Say:**  
“FormulaHub ETL is open-source visual ETL — canvas on top, Python underneath, Apache 2.0. Built for file drops, APIs, SFTP, and databases before the warehouse. I’ll show one pipeline end-to-end, then generate another from English.”

**Do:** Land on blank or home canvas. Don’t digress into architecture.

---

## Beat 2 — Load demo (0:10–0:20)

**Click path:** **Load demo** (or open pipeline `demo-s3-pgp-snowflake`).

**Say:**  
“This is the spectacular path: **S3 → PGP Decrypt → CSV Parse → Schema Validate → Transform → Snowflake demo → Archive.** Encrypted file drop to warehouse load, with rejects — the job data engineers still do every day.”

**Do:** Pause half a second so they see the full graph left-to-right.

---

## Beat 3 — Run + metrics (0:20–0:45)

**Click path:** **Run pipeline** → watch sidebar logs / metrics.

**Say:**  
“Running live. Runner walks the DAG in order. You’re seeing rows processed, duration, and logs — not a slide.”

**When complete, say:**  
“**Ten** good rows loaded to Snowflake demo output. **Three** rejects — bad schema or types — isolated instead of poisoning the load. That’s the difference between a sync tool and real ETL.”

**Do:** Point at reject count / rejects artifact path if visible. Do **not** invent throughput benchmarks.

---

## Beat 4 — Click node params (0:45–1:05)

**Click path:** Click **Schema Validate** → show column/type config → click **Transform** (dates/maps) → optionally **Snowflake** destination config.

**Say:**  
“Every node is configured in place — columns validated here, date transforms here, destination here. Pipelines are JSON under the hood, so they’re reviewable in Git. Familiar visual ETL, modern stack.”

**Do:** One or two clicks only. Resist scrolling every field.

---

## Beat 5 — AI Build (1:05–1:25)

**Click path:** Open **AI Build** / prompt panel → paste prompt → **AI Build** → graph appears.

**Clipboard prompt (use verbatim):**

> Read encrypted files from S3, decrypt using PGP, validate these 17 columns, reject invalid records, transform dates, load good records into Snowflake and archive processed files.

**Say:**  
“Same intent in English. AI Build returns a pipeline graph — nodes and edges. If an LLM key is set we use it; otherwise a solid offline heuristic still maps this demo. Either way, you land on an editable canvas, not a black box.”

**Do:** Let the graph render. If it matches the demo shape, say “Same shape you just ran — editable from here.”

---

## Beat 6 — Close + CTA (1:25–1:30+)

**Say:**  
“Community edition is free and open source. Cloud hosting and Enterprise SSO/RBAC/lineage are on the roadmap — we’re honest that this is MVP/demo-ready, not a mature enterprise suite yet. Want a 15-minute deep-dive on your SFTP/S3 drop pattern, or a local clone walkthrough?”

**CTA:** Share [CALENDAR_LINK] or book next step before leaving the screen share. Point to formulahub.io/etl.

---

## If something breaks (10-second recovery)

| Issue | Recovery line |
|-------|----------------|
| Run fails / API down | “Demo mode needs the local API — I’ll restart and re-run; the pipeline definition is still the product.” |
| AI Build slow / empty | “Heuristic path works offline — I’ll paste the known-good prompt again or load the saved demo.” |
| They ask “is Snowflake real?” | “Same component interface; today we’re on filesystem mock so you can run without an account. Flip demo mode off and add credentials for a real warehouse.” |

---

## Optional extension (+60s) — only if they ask

- Show rejects file / archive folder on disk.  
- Open **Field Mapper** on the core-path demo (Excel → map → filter → sort → aggregate).  
- Mention component catalog and SDK — see `docs/sales/COMPONENTS.md`.  
- Mention verified suite: pytest green, Playwright Run + AI Build OK.  
- Contrast: Airbyte = EL; dbt = in-warehouse T; FormulaHub ETL = pre-warehouse visual ETL that feeds both.
