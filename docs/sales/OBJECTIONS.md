# FormulaHub ETL — Top Objections & Crisp Answers

Use these in calls and follow-ups. Stay honest: **MVP / demo-ready**, no fake logos or benchmarks.  
**Product:** FormulaHub ETL (Lynkx) · [formulahub.io/etl](https://formulahub.io/etl)

---

### 1) “We already use Airbyte.”

**Answer:** Great — keep it for EL syncs at scale. FormulaHub ETL is for the jobs Airbyte doesn’t own: mid-pipeline **transform, schema validate, PGP, reject streams, archive**, and a **visual DAG** ops can reason about. Many teams will run Airbyte *and* a visual ETL for file/crypto/validate paths. Complementary, not a rip-and-replace.

---

### 2) “Why not Apache NiFi?”

**Answer:** NiFi is powerful and battle-tested. It’s also heavyweight: ops surface, JVM footprint, and a learning curve that isn’t “simple visual ETL for the common case.” FormulaHub ETL optimizes for file → decrypt → parse → validate → transform → warehouse — with a **modern Python runner** and a canvas data engineers pick up quickly. If you need NiFi’s full processor zoo and clustering model, stay on NiFi; if you want lighter visual ETL on an open Python stack, try FormulaHub ETL.

---

### 3) “Why not Apache Hop?”

**Answer:** Hop is an excellent visual ETL option for many teams. FormulaHub ETL’s bet is **Python-native jobs**, **JSON/YAML pipelines** friendly to Git, a **React** canvas, **Field Mapper**, and an **AI Pipeline Builder** (English → graph). Different stack preference and a sharper focus on modern data-stack destinations. Evaluate both; pick the runtime and UX your team will actually maintain.

---

### 4) “We use dbt — isn’t that enough?”

**Answer:** dbt owns **in-warehouse** transforms. FormulaHub ETL owns **before and into** the warehouse: encrypted drops, validation, rejects, routing, and load prep. Typical pattern: FormulaHub ETL loads clean rows → dbt models downstream. Not a dbt replacement; a pre-warehouse complement.

---

### 5) “We’ll stick with our legacy desktop / commercial visual ETL suite.”

**Answer:** If you already have deep investment in a full commercial suite, that can be the right buy. FormulaHub ETL is for teams that want the **visual ETL mental model** without desktop lock-in or heavy license weight — **Apache 2.0 core**, browser UI, Python under the hood, Git-friendly JSON/YAML. We’re open-core: Community free now; Enterprise SSO/RBAC/lineage **planned** (roadmap, not vapor-sold as shipped). Compare TCO and ownership honestly for your org size.

---

### 6) “Just use Python / Airflow / scripts.”

**Answer:** Scripts work until the second team inherits them. FormulaHub ETL **is** Python — a component SDK and DAG runner — with a visual layer so pipelines are **reviewable, demable, and less tribal**. Exportable JSON/YAML beats a folder of one-off scripts. Airflow/Kestra exporters are on the roadmap for production orchestration; today the built-in runner is enough for demos and early PoCs.

---

### 7) “Is this production-ready? Connectors look thin.”

**Answer:** **Honestly: MVP.** A working component catalog (files, Excel, API, SFTP, Postgres/MySQL shapes, PGP, validate, Field Mapper, Python Row, Snowflake path, and more), a spectacular demo path, tests green locally. Snowflake/S3 (and SFTP/DB) default to **demo mocks** so strangers can run without accounts; real connectors share the same interfaces when credentials and demo mode are off. More connectors (broader JDBC, Kafka, BigQuery, Databricks), Spark/Polars backends, and orchestration exporters are **roadmap**. We won’t pretend we’re a 200-connector catalog today. See [COMPONENTS.md](./COMPONENTS.md).

---

### 8) “AI Pipeline Builder sounds like hype / risk.”

**Answer:** It’s a **builder**, not autopilot production. English → editable graph; you review and run. With an API key it can call an LLM; **without** one, an offline heuristic still builds the demo-quality graph from keywords (S3, PGP, validate, Snowflake, archive). No customer data leaves your box unless you configure a key. Treat AI Build as a speed boost for scaffolding — same as we show in the 90-second demo.

---

## Quick rebuttal card (print / notes app)

| Objection | One-liner |
|-----------|-----------|
| Airbyte | Keep for EL; we do transform / PGP / validate / rejects |
| NiFi | Heavier ops; we aim for simple visual ETL + Python |
| Hop | Strong peer; we bet on Python + React + AI builder |
| dbt | They do T in-warehouse; we do pre-warehouse ETL |
| Legacy desktop / commercial suite | Valid path; we’re open-core browser alternative, MVP-honest |
| Just Python | We *are* Python + visual + Git-friendly JSON |
| Prod-ready? | MVP; demos/tests solid; connectors growing |
| AI hype | Optional LLM; offline heuristic; always editable |
