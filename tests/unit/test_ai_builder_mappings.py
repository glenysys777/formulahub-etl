"""AI builder: schema-discover auto-fills column_map / tmap mappings offline."""

from __future__ import annotations

import os
from pathlib import Path

from formulaetl_api.ai_builder import (
    build_column_map_mappings,
    build_pipeline_from_text,
    build_tmap_mappings,
    parse_prompt_renames,
    to_snake_case,
)

ROOT = Path(__file__).resolve().parents[2]


def test_to_snake_case():
    assert to_snake_case("Order ID") == "order_id"
    assert to_snake_case("Customer Name") == "customer_name"
    assert to_snake_case("orderId") == "order_id"
    assert to_snake_case("productSku") == "product_sku"


def test_parse_prompt_renames_honors_explicit():
    r = parse_prompt_renames('rename "Customer Name" to client_name')
    assert r["Customer Name"] == "client_name"
    # Do not treat "map columns … to snake_case" as a rename
    assert parse_prompt_renames("map columns from camelCase to snake_case") == {}


def test_build_column_map_mappings_aliases():
    lines = build_column_map_mappings(["Order ID", "Qty", "amt"])
    assert "Order ID:order_id" in lines
    assert "Qty:quantity" in lines
    assert "amt:amount" in lines


def test_build_tmap_col_style():
    lines = build_tmap_mappings(["Order ID", "Amount"], want_calc=True)
    assert 'order_id=col("Order ID")' in lines
    assert any(x.startswith("amount=") and "float(col(" in x and "*1.1" in x for x in lines)


def test_offline_excel_ai_build_populates_mappings(monkeypatch):
    monkeypatch.setenv("FORMULAETL_WORK_DIR", str(ROOT))
    monkeypatch.setenv("FORMULAETL_DEMO", "1")
    # Ensure no LLM keys force heuristic path
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    pipe = build_pipeline_from_text(
        "Read Excel xlsx orders, map columns, transform dates, write CSV"
    )
    cmap = next(n for n in pipe.nodes if n.type == "column_map")
    assert cmap.config["mappings"]
    assert any("Order ID:order_id" == m for m in cmap.config["mappings"])
    assert pipe.metadata.get("schema_enriched") is True


def test_offline_tmap_ai_build_uses_col(monkeypatch):
    monkeypatch.setenv("FORMULAETL_WORK_DIR", str(ROOT))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    pipe = build_pipeline_from_text(
        "Excel spreadsheet tmap expression map with uppercase customer name"
    )
    tmap = next(n for n in pipe.nodes if n.type == "tmap")
    assert tmap.config["mappings"]
    assert any('col("Order ID")' in m for m in tmap.config["mappings"])
    assert any("upper(col(" in m for m in tmap.config["mappings"])
