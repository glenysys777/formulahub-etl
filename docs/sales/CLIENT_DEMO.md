# FormulaHub ETL — 60-second client demo

Use when walking a prospect through the live studio (UI http://127.0.0.1:18766).  
**Brand:** FormulaHub ETL (Lynkx) · [formulahub.io/etl](https://formulahub.io/etl)

Product UI says **Field Mapper**. Speak in features: discover schema, drag columns, expression maps.

## Script

1. **Load demo (5s)** — Click Load demo. Default **core path** opens with **Field Mapper** already showing many mapping arrows (Excel → Field Mapper → Filter → Sort → Aggregate → File).

2. **Field Mapper (15s)** — Point at **Input · Variables · Output**, curved links, sticky headers. Say: Variables are named intermediate expressions; outputs can reference them.

3. **Run (15s)** — Close mapper if open, click Run. Show flowing edges + success metrics.

4. **AI Build (15s)** — English prompt (Excel/API + map) → AI Build → graph appears; **AI fills map mappings after schema discover** so Field Mapper opens populated.

5. **Node parameters (10s)** — Click Excel / Filter / Aggregate — labeled forms, not raw JSON. Advanced JSON collapsed.

## One-liner

> Describe the pipeline in English, map fields visually, run it locally — no Spark, no lock-in.

## Core win path (90s)

1. Load **core path** demo — Excel → Field Mapper → Filter → Sort → Aggregate → File.  
2. Open Field Mapper (button **Open Field Mapper**, or double-click the node) — show `out=expr` mappings (`amount*1.1`, `upper(...)`, `col("Order ID")`). Say: Field Mapper MVP — expressions + drag map, not a full multi-output IDE.  
3. Run — show aggregated CSV.  
4. Optional: **Python Row flex** demo — sandboxed Python for custom per-row logic.  
5. Point at `docs/sales/COMPONENTS.md` for honest component catalog + limits.
