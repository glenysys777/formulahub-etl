"""Schema discovery unit tests — excel, api fixture, csv."""

from __future__ import annotations

from pathlib import Path

import pytest

from formulaetl.schema.discover import discover

ROOT = Path(__file__).resolve().parents[2]


def test_discover_excel_orders_columns():
    result = discover(
        "excel_source",
        {
            "path": "fixtures/sample/orders.xlsx",
            "sheet_name": "Orders",
            "has_header": True,
        },
        work_dir=ROOT,
        demo_mode=True,
    )
    names = [c["name"] for c in result["columns"]]
    assert "Order ID" in names
    assert "Customer Name" in names
    assert "Amount" in names
    assert "Status" in names
    assert len(names) == 11
    assert result.get("sample_rows")
    # Amount should be numeric
    amount_col = next(c for c in result["columns"] if c["name"] == "Amount")
    assert amount_col["type"] in ("float", "int", "string")


def test_discover_http_api_fixture():
    result = discover(
        "http_api_source",
        {
            "url": "https://api.example.com/orders",
            "json_path": "data.items",
            "demo": True,
        },
        work_dir=ROOT,
        demo_mode=True,
    )
    names = [c["name"] for c in result["columns"]]
    assert "orderId" in names
    assert "customerName" in names
    assert "amt" in names
    assert result["sample_rows"]
    assert result["sample_rows"][0]["orderId"] == 2001


def test_discover_csv_customers():
    result = discover(
        "csv",
        {"path": "fixtures/sample/customers.csv", "format": "csv"},
        work_dir=ROOT,
        demo_mode=True,
    )
    names = [c["name"] for c in result["columns"]]
    assert "customer_id" in names
    assert "segment" in names
    assert "region" in names


def test_discover_local_file_csv_alias():
    result = discover(
        "local_file_source",
        {"path": "fixtures/sample/orders_17cols.csv"},
        work_dir=ROOT,
    )
    names = [c["name"] for c in result["columns"]]
    assert "order_id" in names
    assert len(names) == 17


def test_discover_unsupported_type():
    with pytest.raises(ValueError, match="not supported"):
        discover("archive_files", {}, work_dir=ROOT)
