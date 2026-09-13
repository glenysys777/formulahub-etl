"""Unit tests for core FormulaETL components."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from formulaetl.sdk.context import RunContext
from formulaetl.components.source_file import LocalFileSource
from formulaetl.components.source_s3 import S3Source
from formulaetl.components.http_api_source import HttpApiSource
from formulaetl.components.column_map import ColumnMap
from formulaetl.components.pgp_decrypt import PGPDecrypt
from formulaetl.components.csv_parser import CSVParser
from formulaetl.components.schema_validate import SchemaValidate
from formulaetl.components.transform import Transform
from formulaetl.components.filter_rows import Filter
from formulaetl.components.dest_file import LocalFileDestination
from formulaetl.components.dest_snowflake import SnowflakeDestination
from formulaetl.components.archive import ArchiveFiles
from formulaetl.components.logger import LoggerMetrics


def ctx(work: Path) -> RunContext:
    return RunContext(
        run_id="test",
        pipeline_id="test",
        demo_mode=True,
        work_dir=work,
        data_dir=work / "data",
        log=lambda m: None,
    )


def test_local_file_source_csv(work_dir: Path):
    c = LocalFileSource({"path": "fixtures/sample/orders_17cols.csv", "format": "csv"})
    result = c.run(ctx(work_dir))
    assert result.metrics.rows_out == 13  # 10 good + 3 bad
    assert "order_id" in result.rows[0]
    assert len(result.rows[0]) == 17


def test_s3_source_demo(work_dir: Path):
    c = S3Source({"bucket": "demo", "key": "demo/orders_encrypted.csv.pgp"})
    result = c.run(ctx(work_dir))
    assert result.metrics.rows_out == 1
    assert result.side_effects["mode"] == "demo"
    assert len(result.artifacts["bytes"]) > 100


def test_pgp_decrypt(work_dir: Path):
    enc = (work_dir / "data/s3/demo/orders_encrypted.csv.pgp").read_bytes()
    c = PGPDecrypt({
        "private_key_path": "fixtures/keys/demo_private.asc",
        "bytes": enc,
    })
    result = c.run(ctx(work_dir))
    assert result.metrics.rows_out == 1
    assert "order_id" in result.artifacts["content"]
    assert result.artifacts["content"].startswith("order_id")


def test_csv_parser(work_dir: Path):
    text = (work_dir / "fixtures/sample/orders_17cols.csv").read_text()
    c = CSVParser({"content": text})
    result = c.run(ctx(work_dir))
    assert result.metrics.rows_out == 13
    assert result.rows[0]["customer_name"] == "Customer 1"


def test_schema_validate_rejects(work_dir: Path):
    text = (work_dir / "fixtures/sample/orders_17cols.csv").read_text()
    rows = CSVParser({"content": text}).run(ctx(work_dir)).rows
    c = SchemaValidate({
        "columns": {
            "order_id": "int",
            "email": "email",
            "quantity": "int",
            "unit_price": "float",
            "ship_date": "date",
            "customer_name": "string",
        },
        "required_columns": ["order_id", "email", "customer_name", "quantity", "unit_price"],
    })
    result = c.run(ctx(work_dir), rows)
    assert result.metrics.rows_in == 13
    assert result.metrics.rows_out == 10
    assert result.metrics.rows_rejected == 3
    assert all("_reject_reason" in r for r in result.rejects)


def test_transform_dates(work_dir: Path):
    rows = [
        {"order_date": "01/20/2024", "quantity": "3", "unit_price": "10.5", "name": "a"},
        {"order_date": "2024-02-01", "quantity": "1", "unit_price": "2", "name": "b"},
    ]
    c = Transform({
        "cast": {
            "order_date": {"type": "date", "input_format": "%m/%d/%Y", "output_format": "%Y-%m-%d"},
            "quantity": "int",
            "unit_price": "float",
        },
        "rename": {"name": "customer_name"},
        "add_constants": {"loaded_by": "formulaetl"},
    })
    result = c.run(ctx(work_dir), rows)
    assert result.rows[0]["order_date"] == "2024-01-20"
    assert result.rows[0]["quantity"] == 3
    assert result.rows[0]["customer_name"] == "a"
    assert result.rows[0]["loaded_by"] == "formulaetl"
    assert result.rows[1]["order_date"] == "2024-02-01"


def test_filter(work_dir: Path):
    rows = [
        {"status": "shipped", "amount": 10},
        {"status": "pending", "amount": 5},
        {"status": "shipped", "amount": 0},
    ]
    c = Filter({"expression": "status == 'shipped' and amount > 0"})
    result = c.run(ctx(work_dir), rows)
    assert len(result.rows) == 1
    assert result.metrics.rows_rejected == 2


def test_local_file_destination(work_dir: Path):
    rows = [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}]
    out = "data/out/test_dest.csv"
    c = LocalFileDestination({"path": out, "format": "csv"})
    result = c.run(ctx(work_dir), rows)
    path = work_dir / out
    assert path.exists()
    with path.open() as f:
        reader = list(csv.DictReader(f))
    assert len(reader) == 2
    assert result.metrics.rows_out == 2


def test_snowflake_destination_demo(work_dir: Path):
    rows = [{"order_id": 1, "email": "a@b.com"}, {"order_id": 2, "email": "c@d.com"}]
    c = SnowflakeDestination({
        "database": "DEMO_DB",
        "schema": "PUBLIC",
        "table": "ORDERS",
        "demo_output_dir": "data/out/snowflake",
    })
    result = c.run(ctx(work_dir), rows)
    assert result.side_effects["mode"] == "demo"
    assert result.side_effects["rows_loaded"] == 2
    assert Path(result.side_effects["written_path"]).exists()
    assert Path(result.side_effects["load_log"]).exists()


def test_archive_files_move(work_dir: Path):
    src = work_dir / "data" / "s3" / "demo" / "to_archive.txt"
    src.write_text("hello", encoding="utf-8")
    c = ArchiveFiles({"source": str(src), "destination": "data/archive/", "mode": "move"})
    result = c.run(ctx(work_dir))
    assert not src.exists()
    assert Path(result.side_effects["archived_to"]).exists()
    assert result.side_effects["mode"] == "move"


def test_logger_metrics(work_dir: Path):
    rows = [{"x": 1}, {"x": 2}]
    c = LoggerMetrics({"label": "test", "log_sample": 1})
    result = c.run(ctx(work_dir), rows)
    assert result.metrics.rows_in == 2
    assert result.metrics.rows_out == 2
    assert result.metrics.duration_ms >= 0


def test_http_api_source_demo(work_dir: Path):
    c = HttpApiSource({
        "url": "https://api.example.com/v1/orders",
        "method": "GET",
        "json_path": "data.items",
        "demo": True,
    })
    result = c.run(ctx(work_dir))
    assert result.side_effects["mode"] == "demo"
    assert result.metrics.rows_out == 12
    assert "orderId" in result.rows[0]
    assert "amt" in result.rows[0]
    assert result.rows[0]["orderId"] == 2001


def test_http_api_source_demo_via_example_url(work_dir: Path):
    """FORMULAETL_DEMO + example.com triggers fixture without demo=true."""
    c = HttpApiSource({
        "url": "https://orders.example.com/api/orders",
        "json_path": "data.items",
    })
    result = c.run(ctx(work_dir))
    assert result.metrics.rows_out == 12


def test_column_map(work_dir: Path):
    rows = [
        {"orderId": 1, "amt": 9.5, "keep": "x"},
        {"orderId": 2, "amt": 1.0, "keep": "y"},
    ]
    c = ColumnMap({
        "mappings": ["orderId:order_id", "amt:amount"],
        "drop_unmapped": False,
    })
    result = c.run(ctx(work_dir), rows)
    assert result.rows[0]["order_id"] == 1
    assert result.rows[0]["amount"] == 9.5
    assert "orderId" not in result.rows[0]
    assert result.rows[0]["keep"] == "x"

    c2 = ColumnMap({
        "mappings": ["orderId:order_id", "amt:amount"],
        "drop_unmapped": True,
    })
    result2 = c2.run(ctx(work_dir), rows)
    assert set(result2.rows[0].keys()) == {"order_id", "amount"}


def test_excel_source(work_dir: Path):
    from formulaetl.components.excel_source import ExcelSource

    c = ExcelSource({
        "path": "fixtures/sample/orders.xlsx",
        "sheet_name": "Orders",
        "has_header": True,
    })
    result = c.run(ctx(work_dir))
    assert result.metrics.rows_out == 8
    assert "Order ID" in result.rows[0]
    assert result.rows[0]["Order ID"] == 3001


def test_excel_source_range_and_index(work_dir: Path):
    from formulaetl.components.excel_source import ExcelSource

    c = ExcelSource({
        "path": "fixtures/sample/orders.xlsx",
        "sheet_name": 0,
        "has_header": True,
        "range": "A1:C3",
    })
    result = c.run(ctx(work_dir))
    assert result.metrics.rows_out == 2
    assert set(result.rows[0].keys()) == {"Order ID", "Customer ID", "Customer Name"}


def test_excel_destination(work_dir: Path):
    from formulaetl.components.excel_destination import ExcelDestination
    from formulaetl.components.excel_source import ExcelSource

    rows = [{"order_id": 1, "name": "a"}, {"order_id": 2, "name": "b"}]
    out = "data/out/test_excel.xlsx"
    c = ExcelDestination({"path": out, "sheet_name": "Out", "has_header": True})
    result = c.run(ctx(work_dir), rows)
    assert result.metrics.rows_out == 2
    assert (work_dir / out).exists()

    back = ExcelSource({"path": out, "sheet_name": "Out", "has_header": True}).run(ctx(work_dir))
    assert back.metrics.rows_out == 2
    assert back.rows[0]["order_id"] == 1


def test_json_parser_file(work_dir: Path):
    from formulaetl.components.json_parser import JSONParser

    c = JSONParser({
        "path": "fixtures/sample/api_orders.json",
        "json_path": "data.items",
    })
    result = c.run(ctx(work_dir))
    assert result.metrics.rows_out == 12
    assert result.rows[0]["orderId"] == 2001


def test_json_parser_inline(work_dir: Path):
    from formulaetl.components.json_parser import JSONParser

    c = JSONParser({"content": '[{"a": 1}, {"a": 2}]'})
    result = c.run(ctx(work_dir))
    assert result.metrics.rows_out == 2


def test_dedupe(work_dir: Path):
    from formulaetl.components.dedupe import Dedupe

    rows = [
        {"order_id": 1, "v": "a"},
        {"order_id": 2, "v": "b"},
        {"order_id": 1, "v": "c"},
    ]
    c = Dedupe({"keys": ["order_id"], "keep": "first"})
    result = c.run(ctx(work_dir), rows)
    assert len(result.rows) == 2
    assert result.rows[0]["v"] == "a"
    assert result.metrics.rows_rejected == 1

    c2 = Dedupe({"keys": "order_id", "keep": "last"})
    result2 = c2.run(ctx(work_dir), rows)
    assert result2.rows[0]["v"] == "c"


def test_sqlite_source_destination(work_dir: Path):
    from formulaetl.components.sqlite_destination import SQLiteDestination
    from formulaetl.components.sqlite_source import SQLiteSource

    rows = [
        {"order_id": 1, "customer_name": "Acme", "amount": 10.5},
        {"order_id": 2, "customer_name": "Beta", "amount": 3.0},
    ]
    dest = SQLiteDestination({
        "path": "data/demo.db",
        "table": "orders",
        "if_exists": "replace",
    })
    dres = dest.run(ctx(work_dir), rows)
    assert dres.side_effects["rows_loaded"] == 2
    assert (work_dir / "data/demo.db").exists()

    src = SQLiteSource({
        "path": "data/demo.db",
        "query": "SELECT * FROM orders ORDER BY order_id",
    })
    sres = src.run(ctx(work_dir))
    assert sres.metrics.rows_out == 2
    assert sres.rows[0]["customer_name"] == "Acme"


def test_sftp_source_demo(work_dir: Path):
    from formulaetl.components.sftp_source import SFTPSource

    c = SFTPSource({
        "host": "demo",
        "remote_path": "/incoming/orders.xlsx",
        "local_staging_path": "data/out/sftp_staging/orders.xlsx",
    })
    result = c.run(ctx(work_dir))
    assert result.side_effects["mode"] == "demo"
    assert result.metrics.rows_out == 1
    dest = work_dir / "data/out/sftp_staging/orders.xlsx"
    assert dest.exists()
    assert dest.stat().st_size > 100


def test_sftp_destination_demo(work_dir: Path):
    from formulaetl.components.sftp_destination import SFTPDestination

    src = work_dir / "fixtures/sample/orders_17cols.csv"
    c = SFTPDestination({
        "host": "demo",
        "remote_path": "/outgoing/orders.csv",
        "local_path": str(src.relative_to(work_dir)),
    })
    result = c.run(ctx(work_dir), [])
    assert result.side_effects["mode"] == "demo"
    out = Path(result.side_effects["written_path"])
    assert out.exists()
    assert "sftp_mock" in str(out)


def test_postgres_source_demo(work_dir: Path):
    from formulaetl.components.postgres_source import PostgresSource

    c = PostgresSource({
        "host": "demo",
        "query": "SELECT * FROM orders LIMIT 5",
        "demo_sqlite_path": "data/demo.db",
    })
    result = c.run(ctx(work_dir))
    assert result.side_effects["mode"].startswith("demo")
    assert result.metrics.rows_out >= 3
    assert "order_id" in result.rows[0]


def test_postgres_destination_demo(work_dir: Path):
    from formulaetl.components.postgres_destination import PostgresDestination

    rows = [
        {"order_id": 1, "customer_name": "Acme"},
        {"order_id": 2, "customer_name": "Beta"},
    ]
    c = PostgresDestination({
        "host": "demo",
        "table": "orders_loaded",
        "if_exists": "replace",
        "demo_output_dir": "data/out/postgres_demo",
    })
    result = c.run(ctx(work_dir), rows)
    assert result.side_effects["mode"] == "demo"
    assert result.side_effects["rows_loaded"] == 2
    assert Path(result.side_effects["written_path"]).exists()
    assert Path(result.side_effects["csv_path"]).exists()


def test_lookup_join(work_dir: Path):
    from formulaetl.components.lookup_join import LookupJoin

    left = [
        {"order_id": 1, "customer_id": "201"},
        {"order_id": 2, "customer_id": "999"},
    ]
    # Ensure customers.csv exists (seeded into fixtures)
    cust = work_dir / "fixtures/sample/customers.csv"
    if not cust.exists():
        cust.write_text(
            "customer_id,segment,region\n201,smb,NA\n202,enterprise,NA\n",
            encoding="utf-8",
        )
    c = LookupJoin({
        "left_keys": ["customer_id"],
        "right_keys": ["customer_id"],
        "lookup_path": "fixtures/sample/customers.csv",
        "how": "left",
    })
    result = c.run(ctx(work_dir), left)
    assert result.metrics.rows_out == 2
    assert result.rows[0].get("segment") == "smb"
    assert "segment" not in result.rows[1] or result.rows[1].get("segment") in (None, "smb")


def test_sort_rows(work_dir: Path):
    from formulaetl.components.sort_rows import SortRows

    rows = [
        {"status": "b", "amount": 10},
        {"status": "a", "amount": 30},
        {"status": "a", "amount": 5},
    ]
    c = SortRows({"keys": ["status:asc", "amount:desc"]})
    result = c.run(ctx(work_dir), rows)
    assert [r["amount"] for r in result.rows] == [30, 5, 10]
    assert result.rows[0]["status"] == "a"


def test_aggregate(work_dir: Path):
    from formulaetl.components.aggregate import Aggregate

    rows = [
        {"status": "shipped", "amount": 10},
        {"status": "shipped", "amount": 20},
        {"status": "pending", "amount": 5},
    ]
    c = Aggregate({"group_by": ["status"], "aggs": ["sum:amount", "count:*", "avg:amount"]})
    result = c.run(ctx(work_dir), rows)
    by = {r["status"]: r for r in result.rows}
    assert by["shipped"]["sum_amount"] == 30
    assert by["shipped"]["count"] == 2
    assert by["shipped"]["avg_amount"] == 15
    assert by["pending"]["sum_amount"] == 5


def test_tmap_expressions(work_dir: Path):
    from formulaetl.components.tmap import TMap

    rows = [
        {"name": "Ada", "amount": 10, "status": "SHIPPED", "a": None, "b": 2},
        {"name": "Bob", "amount": 0, "status": "pending", "a": 1, "b": 9},
    ]
    c = TMap({
        "mappings": [
            "name_up=upper(name)",
            "total=amount*1.1",
            "x=coalesce(a,b)",
            "status=lower(status)",
        ],
        "filter_expr": "status == 'SHIPPED' or status == 'shipped'",
        "drop_unmapped": True,
        "reject_unmatched": True,
    })
    # filter runs on input row — status is still SHIPPED for first
    result = c.run(ctx(work_dir), rows)
    assert len(result.rows) == 1
    assert result.rows[0]["name_up"] == "ADA"
    assert abs(result.rows[0]["total"] - 11.0) < 1e-9
    assert result.rows[0]["x"] == 2
    assert result.metrics.rows_rejected == 1


def test_python_row_and_sandbox(work_dir: Path):
    from formulaetl.components.python_row import PythonRow

    rows = [{"amount": 10, "qty": 2}, {"amount": 5, "qty": 1}]
    c = PythonRow({
        "mode": "row",
        "code": "row['total'] = float(row['amount']) * int(row['qty'])",
    })
    result = c.run(ctx(work_dir), rows)
    assert result.rows[0]["total"] == 20
    assert result.rows[1]["total"] == 5

    bad = PythonRow({"mode": "row", "code": "open('/etc/passwd')"})
    with pytest.raises(ValueError, match="disallowed"):
        bad.run(ctx(work_dir), rows)

    batch = PythonRow({
        "mode": "batch",
        "input_var": "rows",
        "code": "rows = [r for r in rows if float(r.get('amount') or 0) >= 10]",
    })
    bres = batch.run(ctx(work_dir), rows)
    assert len(bres.rows) == 1


def test_pgp_encrypt_decrypt_roundtrip(work_dir: Path):
    from formulaetl.components.pgp_encrypt import PGPEncrypt
    from formulaetl.components.pgp_decrypt import PGPDecrypt

    enc = PGPEncrypt({
        "public_key_path": "fixtures/keys/demo_public.asc",
        "content": "hello,formulaetl\n",
        "armor": True,
    }).run(ctx(work_dir))
    assert enc.artifacts["bytes"]
    dec = PGPDecrypt({
        "private_key_path": "fixtures/keys/demo_private.asc",
        "bytes": enc.artifacts["bytes"],
    }).run(ctx(work_dir))
    assert "hello,formulaetl" in dec.artifacts["content"]


def test_xml_parser(work_dir: Path):
    from formulaetl.components.xml_parser import XMLParser

    # Copy fixture into work_dir
    src = Path(__file__).resolve().parents[2] / "fixtures/sample/orders.xml"
    dest = work_dir / "fixtures/sample/orders.xml"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    c = XMLParser({"path": "fixtures/sample/orders.xml", "record_tag": "order"})
    result = c.run(ctx(work_dir))
    assert result.metrics.rows_out == 3
    assert result.rows[0]["customer_name"] == "XML Customer 1"
    assert result.rows[0].get("@id") == "4001"


def test_mysql_source_destination_demo(work_dir: Path):
    from formulaetl.components.mysql_destination import MySQLDestination
    from formulaetl.components.mysql_source import MySQLSource

    rows = [{"order_id": 1, "customer_name": "Acme"}, {"order_id": 2, "customer_name": "Beta"}]
    dest = MySQLDestination({
        "host": "demo",
        "table": "mysql_orders",
        "if_exists": "replace",
        "demo_output_dir": "data/out/mysql_demo",
    })
    dres = dest.run(ctx(work_dir), rows)
    assert dres.side_effects["mode"] == "demo"
    assert Path(dres.side_effects["written_path"]).exists()

    src = MySQLSource({
        "host": "demo",
        "query": "SELECT * FROM orders LIMIT 5",
        "demo_sqlite_path": "data/demo.db",
    })
    sres = src.run(ctx(work_dir))
    assert sres.side_effects["mode"].startswith("demo")
    assert sres.metrics.rows_out >= 1
