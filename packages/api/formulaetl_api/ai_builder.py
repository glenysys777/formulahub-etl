"""AI Pipeline Builder — heuristic + LLM-ready interface."""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import Any

from formulaetl.models.pipeline import EdgeDefinition, NodeDefinition, PipelineDefinition

DEMO_COLUMNS = {
    "order_id": "int",
    "customer_id": "int",
    "customer_name": "string",
    "email": "email",
    "phone": "string",
    "country": "string",
    "city": "string",
    "product_sku": "string",
    "product_name": "string",
    "quantity": "int",
    "unit_price": "float",
    "currency": "string",
    "order_date": "string",
    "ship_date": "date",
    "status": "string",
    "channel": "string",
    "notes": "string",
}

DEMO_REQUIRED = [
    "order_id",
    "customer_id",
    "customer_name",
    "email",
    "product_sku",
    "quantity",
    "unit_price",
    "order_date",
    "ship_date",
    "status",
]


def _has(text: str, *keywords: str) -> bool:
    t = text.lower()
    return any(k.lower() in t for k in keywords)


def heuristic_build(description: str, name: str | None = None) -> PipelineDefinition:
    """Map English keywords to a runnable FormulaETL DAG."""
    text = description.strip()
    want_api = _has(text, "api", "rest", "http", "endpoint")
    want_kafka = _has(text, "kafka", "topic", "stream", "event stream", "consumer group")
    want_databricks = _has(
        text, "databricks", "notebook job", "spark job", "spark job trigger", "databricks job"
    )
    want_excel = _has(text, "excel", "xlsx", "spreadsheet", "xls")
    want_sqlite = _has(text, "sqlite", "sql db", "demo.db") and not _has(
        text, "postgres", "postgresql", "sftp"
    )
    want_postgres = _has(text, "postgres", "postgresql", "psql", "jdbc")
    want_mysql = _has(text, "mysql", "mariadb")
    want_sftp = _has(text, "sftp", "secure file transfer", "ssh file")
    want_tmap = _has(text, "tmap", "t map", "expression map", "column expression")
    want_lookup = _has(text, "lookup", "join", "enrich") and not want_tmap
    want_json = _has(text, "json parser", "json array", "parse json") or (
        _has(text, "json") and not want_api
    )
    want_dedupe = _has(text, "dedupe", "deduplicate", "unique", "distinct rows")
    want_sort = _has(text, "sort", "tsort", "tsortrow", "order by")
    # "java"/"flex" alone are common Talend words; require row/script/code context unless python/tjava*
    want_python = _has(text, "python", "tjavarow", "tjavaflex", "script per row") or (
        _has(text, "java", "flex") and _has(text, "row", "script", "code", "tjava")
    )
    want_aggregate = _has(text, "aggregate", "group by", "groupby", "sum:", "taggregaterow")
    want_encrypt = _has(text, "pgp_encrypt", "gpg encrypt", "encrypt with", "pgp encrypt") or (" encrypt" in f" {text.lower()}" and "decrypt" not in text.lower() and "encrypted" not in text.lower())
    want_xml = _has(text, "xml", "xml parser", "parse xml")
    want_s3 = (
        (not want_api)
        and (not want_kafka)
        and (not want_excel)
        and (not want_sqlite)
        and (not want_postgres)
        and (not want_mysql)
        and (not want_sftp)
        and (
            _has(text, "s3", "bucket", "object storage")
            or not _has(text, "local file", "filesystem", "csv file")
        )
    )
    want_pgp = (_has(text, "pgp", "gpg", "decrypt", "encrypted") or _has(text, "decrypt")) and not want_encrypt
    want_validate = (
        _has(text, "validate", "schema", "reject", "invalid", "columns")
        or want_api
        or want_kafka
        or want_excel
        or want_postgres
        or want_sftp
    )
    want_transform = (
        _has(text, "transform", "date", "cast", "rename")
        or want_api
        or want_kafka
        or want_excel
        or want_postgres
    )
    want_column_map = (
        want_api
        or want_kafka
        or want_excel
        or want_sftp
        or _has(text, "column map", "rename columns", "map columns")
    )
    want_excel_dest = _has(text, "write excel", "to excel", "xlsx out", "excel destination")
    want_sqlite_dest = want_sqlite and _has(
        text, "write", "load", "insert", "destination", "into"
    )
    want_postgres_dest = want_postgres and _has(
        text, "into postgres", "postgres destination", "load into", "insert into"
    ) and not _has(text, "csv", "file destination", "local file", "write csv")
    want_sftp_dest = want_sftp and _has(
        text, "upload", "put", "sftp destination", "send to sftp", "to sftp"
    )
    if want_api or want_excel or want_sqlite or want_postgres or want_mysql or want_sftp or want_kafka:
        want_snowflake = _has(text, "snowflake", "warehouse") and not want_databricks
    elif want_tmap or want_python or want_aggregate or want_sort or want_xml:
        want_snowflake = _has(text, "snowflake", "warehouse") and not want_databricks
        want_s3 = want_s3 and _has(text, "s3", "bucket")
    else:
        want_snowflake = (
            _has(text, "snowflake", "warehouse")
            or (
                not want_databricks
                and not _has(
                    text, "local destination", "write csv", "file destination", "excel"
                )
            )
        )
    want_archive = _has(text, "archive", "processed file")
    want_rejects = _has(text, "reject", "invalid")

    nodes: list[NodeDefinition] = []
    edges: list[EdgeDefinition] = []
    x = 40.0

    def node(nid: str, typ: str, label: str, config: dict[str, Any], y: float = 180) -> None:
        nonlocal x
        nodes.append(
            NodeDefinition(
                id=nid,
                type=typ,
                label=label,
                config=config,
                position={"x": x, "y": y},
            )
        )
        x += 220

    def edge(src: str, tgt: str, handle: str | None = None) -> None:
        edges.append(
            EdgeDefinition(
                id=f"e-{src}-{tgt}",
                source=src,
                target=tgt,
                sourceHandle=handle,
            )
        )

    # --- build linear spine ---
    chain: list[str] = []

    if want_api:
        node(
            "api",
            "http_api_source",
            "HTTP API Source",
            {
                "url": "https://api.example.com/v1/orders",
                "method": "GET",
                "json_path": "data.items",
                "demo": True,
            },
        )
        chain.append("api")
    elif want_kafka:
        node(
            "kafka",
            "kafka_source",
            "Kafka Source",
            {
                "brokers": "demo",
                "topic": "orders",
                "group_id": "formulaetl",
                "auto_offset_reset": "earliest",
                "max_messages": 100,
                "timeout_sec": 10,
                "security": "plain",
                "format": "json",
                "demo": True,
            },
        )
        chain.append("kafka")
    elif want_sftp and want_excel:
        node(
            "sftp",
            "sftp_source",
            "SFTP Source",
            {
                "host": "demo",
                "remote_path": "/incoming/orders.xlsx",
                "local_staging_path": "data/out/sftp_staging/orders.xlsx",
            },
        )
        chain.append("sftp")
        node(
            "excel",
            "excel_source",
            "Excel Source",
            {
                "path": "data/out/sftp_staging/orders.xlsx",
                "sheet_name": "Orders",
                "has_header": True,
            },
        )
        chain.append("excel")
    elif want_sftp:
        node(
            "sftp",
            "sftp_source",
            "SFTP Source",
            {
                "host": "demo",
                "remote_path": "/incoming/orders_17cols.csv",
                "local_staging_path": "data/out/sftp_staging/",
            },
        )
        chain.append("sftp")
    elif want_mysql:
        node(
            "mysql",
            "mysql_source",
            "MySQL Source",
            {
                "host": "demo",
                "port": 3306,
                "query": "SELECT * FROM orders",
                "demo_sqlite_path": "data/demo.db",
            },
        )
        chain.append("mysql")
    elif want_postgres:
        node(
            "pg",
            "postgres_source",
            "Postgres Source",
            {
                "host": "demo",
                "query": "SELECT * FROM orders",
                "demo_sqlite_path": "data/demo.db",
            },
        )
        chain.append("pg")
    elif want_excel:
        node(
            "excel",
            "excel_source",
            "Excel Source",
            {
                "path": "fixtures/sample/orders.xlsx",
                "sheet_name": "Orders",
                "has_header": True,
            },
        )
        chain.append("excel")
    elif want_sqlite:
        node(
            "sqlite",
            "sqlite_source",
            "SQLite Source",
            {"path": "data/demo.db", "query": "SELECT * FROM orders"},
        )
        chain.append("sqlite")
    elif want_s3:
        node("s3", "s3_source", "S3 Source", {"bucket": "demo", "key": "demo/orders_encrypted.csv.pgp"})
        chain.append("s3")
    else:
        node(
            "file",
            "local_file_source",
            "Local File",
            {"path": "fixtures/sample/orders_17cols.csv", "format": "csv"},
        )
        chain.append("file")

    if want_pgp:
        node(
            "pgp",
            "pgp_decrypt",
            "PGP Decrypt",
            {"private_key_path": "fixtures/keys/demo_private.asc", "passphrase": ""},
        )
        chain.append("pgp")

    # Parse whenever we decrypt or explicitly ask for CSV parsing from binary sources
    if (
        want_pgp
        or chain[-1] == "s3"
        or (chain[-1] == "sftp" and not want_excel)
        or (_has(text, "csv") and not want_excel and not want_postgres and not want_mysql)
    ) and not want_json and not want_excel and not want_postgres and not want_mysql:
        node("parse", "csv_parser", "CSV Parse", {"delimiter": ","})
        chain.append("parse")

    if want_json:
        node(
            "json",
            "json_parser",
            "JSON Parser",
            {"path": "fixtures/sample/api_orders.json", "json_path": "data.items"},
        )
        chain.append("json")

    if want_xml:
        node(
            "xml",
            "xml_parser",
            "XML Parser",
            {"path": "fixtures/sample/orders.xml", "record_tag": "order"},
        )
        chain.append("xml")

    if want_tmap:
        node(
            "field_mapper",
            "tmap",
            "Field Mapper",
            {
                "mappings": [
                    "order_id=order_id",
                    "customer_name=upper(customer_name)",
                    "amount=amount*1.1",
                    "status=status",
                ],
                "drop_unmapped": False,
            },
        )
        chain.append("field_mapper")
    elif want_column_map:
        if want_excel:
            mappings = [
                "Order ID:order_id",
                "Customer ID:customer_id",
                "Customer Name:customer_name",
                "Product SKU:product_sku",
                "Qty:quantity",
                "Amount:amount",
                "Order Date:order_date",
            ]
        else:
            mappings = [
                "orderId:order_id",
                "customerId:customer_id",
                "customerName:customer_name",
                "productSku:product_sku",
                "qty:quantity",
                "amt:amount",
            ]
            if want_kafka:
                mappings = [
                    "order_id:order_id",
                    "customer_id:customer_id",
                    "customer_name:customer_name",
                    "product_sku:product_sku",
                    "quantity:quantity",
                    "amount:amount",
                ]
        node(
            "map",
            "column_map",
            "Column Map",
            {"mappings": mappings, "drop_unmapped": False},
        )
        chain.append("map")

    if want_lookup:
        node(
            "join",
            "lookup_join",
            "Lookup Join",
            {
                "left_keys": ["customer_id"],
                "right_keys": ["customer_id"],
                "lookup_path": "fixtures/sample/customers.csv",
                "how": "left",
            },
        )
        chain.append("join")

    if want_dedupe:
        node("dedupe", "dedupe", "Dedupe", {"keys": ["order_id"], "keep": "first"})
        chain.append("dedupe")

    if want_python:
        node(
            "py",
            "python_row",
            "Python Row",
            {
                "mode": "row",
                "input_var": "row",
                "code": "row['loaded_by'] = 'formulaetl'\nrow['amount'] = float(row.get('amount') or row.get('unit_price') or 0)",
            },
        )
        chain.append("py")

    if want_sort:
        node("sort", "sort", "Sort Rows", {"keys": ["amount:desc"]})
        chain.append("sort")

    if want_aggregate:
        node(
            "agg",
            "aggregate",
            "Aggregate",
            {"group_by": ["status"], "aggs": ["sum:amount", "count:*"]},
        )
        chain.append("agg")

    if want_validate:
        if want_api or want_excel or want_kafka:
            api_cols = {
                "order_id": "int",
                "customer_id": "int",
                "customer_name": "string",
                "email": "email",
                "product_sku": "string",
                "quantity": "int",
                "amount": "float",
                "order_date": "string",
                "status": "string",
            }
            api_req = list(api_cols.keys())
            node(
                "validate",
                "schema_validate",
                "Schema Validate",
                {"columns": api_cols, "required_columns": api_req},
            )
        else:
            node(
                "validate",
                "schema_validate",
                "Schema Validate",
                {"columns": DEMO_COLUMNS, "required_columns": DEMO_REQUIRED},
            )
        chain.append("validate")

    if want_transform:
        if want_api or want_excel or want_kafka:
            cast_cfg = {
                "order_date": {
                    "type": "date",
                    "input_format": "%m/%d/%Y",
                    "output_format": "%Y-%m-%d",
                },
                "quantity": "int",
                "amount": "float",
                "order_id": "int",
                "customer_id": "int",
            }
        else:
            cast_cfg = {
                "order_date": {
                    "type": "date",
                    "input_format": "%m/%d/%Y",
                    "output_format": "%Y-%m-%d",
                },
                "ship_date": {
                    "type": "date",
                    "input_format": "%Y-%m-%d",
                    "output_format": "%Y-%m-%d",
                },
                "quantity": "int",
                "unit_price": "float",
            }
        node(
            "transform",
            "transform",
            "Transform Dates",
            {
                "cast": cast_cfg,
                "add_constants": {"loaded_by": "formulaetl"},
            },
            y=80,
        )
        chain.append("transform")

    if want_encrypt:
        node(
            "pgp_enc",
            "pgp_encrypt",
            "PGP Encrypt",
            {
                "public_key_path": "fixtures/keys/demo_public.asc",
                "output_path": "data/out/encrypted_out.pgp",
                "armor": True,
            },
        )
        chain.append("pgp_enc")

    if want_snowflake:
        node(
            "snowflake",
            "snowflake_destination",
            "Snowflake (demo)",
            {
                "database": "DEMO_DB",
                "schema": "PUBLIC",
                "table": "ORDERS",
                "demo_output_dir": "data/out/snowflake",
            },
            y=80,
        )
        chain.append("snowflake")
    elif want_databricks:
        node(
            "databricks",
            "databricks_job",
            "Databricks Job",
            {
                "workspace_host": "demo",
                "job_id": "1001",
                "notebook_params": ["source=formulaetl"],
                "wait_for_completion": True,
                "poll_interval_sec": 1,
                "demo": True,
                "demo_output_dir": "data/out/databricks_demo",
            },
            y=80,
        )
        chain.append("databricks")
    elif want_mysql and _has(text, "write", "load", "insert", "destination", "into"):
        node(
            "mysql_dest",
            "mysql_destination",
            "MySQL Destination",
            {
                "host": "demo",
                "port": 3306,
                "table": "orders",
                "if_exists": "replace",
                "demo_output_dir": "data/out/mysql_demo",
            },
        )
        chain.append("mysql_dest")
    elif want_postgres_dest:
        node(
            "pg_dest",
            "postgres_destination",
            "Postgres Destination",
            {
                "host": "demo",
                "table": "orders",
                "if_exists": "replace",
                "demo_output_dir": "data/out/postgres_demo",
            },
        )
        chain.append("pg_dest")
    elif want_sftp_dest:
        node(
            "dest",
            "local_file_destination",
            "File Destination",
            {"path": "data/out/output.csv", "format": "csv"},
        )
        chain.append("dest")
        node(
            "sftp_dest",
            "sftp_destination",
            "SFTP Destination",
            {
                "host": "demo",
                "remote_path": "/outgoing/output.csv",
                "local_path": "data/out/output.csv",
            },
        )
        chain.append("sftp_dest")
    elif want_sqlite_dest:
        node(
            "sqlite_dest",
            "sqlite_destination",
            "SQLite Destination",
            {"path": "data/demo.db", "table": "orders", "if_exists": "replace"},
        )
        chain.append("sqlite_dest")
    elif want_excel_dest and want_excel:
        node(
            "dest",
            "excel_destination",
            "Excel Destination",
            {"path": "data/out/output.xlsx", "sheet_name": "Orders", "has_header": True},
        )
        chain.append("dest")
    else:
        node(
            "dest",
            "local_file_destination",
            "File Destination",
            {"path": "data/out/output.csv", "format": "csv"},
        )
        chain.append("dest")

    # Wire main chain; use rejects handle out of validate → transform
    for i in range(len(chain) - 1):
        src, tgt = chain[i], chain[i + 1]
        handle = "out" if src == "validate" and tgt == "transform" else None
        # Also when validate goes directly to destination
        if src == "validate" and tgt in (
            "snowflake",
            "dest",
            "sqlite_dest",
            "pg_dest",
            "sftp_dest",
            "mysql_dest",
            "pgp_enc",
            "databricks",
        ):
            handle = "out"
        edge(src, tgt, handle)

    if want_rejects and "validate" in chain:
        node(
            "rejects",
            "local_file_destination",
            "Rejects File",
            {"path": "data/rejects/orders_rejects.csv", "format": "csv"},
            y=320,
        )
        edge("validate", "rejects", "rejects")

    if want_archive:
        last = chain[-1]
        node(
            "archive",
            "archive_files",
            "Archive Source",
            {"destination": "data/archive/", "mode": "move"},
            y=300,
        )
        edge(last, "archive")

    if name:
        pipeline_name = name
    elif want_kafka and want_databricks:
        pipeline_name = "Kafka → Databricks Job"
    elif want_s3 and want_databricks:
        pipeline_name = "S3 → Databricks Job"
    elif want_kafka:
        pipeline_name = "Kafka → Transform"
    elif want_databricks:
        pipeline_name = "Trigger Databricks Job"
    elif want_sftp and want_excel:
        pipeline_name = "SFTP → Excel → Map"
    elif want_sftp:
        pipeline_name = "SFTP → Transform"
    elif want_mysql:
        pipeline_name = "MySQL → File"
    elif want_postgres:
        pipeline_name = "Postgres → File"
    elif want_tmap or want_aggregate or want_sort:
        pipeline_name = "Field Mapper → Sort → Aggregate"
    elif want_python:
        pipeline_name = "Python Row Flex"
    elif want_excel:
        pipeline_name = "Excel → Map → Transform"
    elif want_api:
        pipeline_name = "API → Map → Transform"
    elif want_sqlite:
        pipeline_name = "SQLite → Transform"
    elif want_s3 and want_snowflake:
        pipeline_name = "S3 → PGP → Snowflake"
    else:
        pipeline_name = "AI Generated Pipeline"

    return PipelineDefinition(
        id=f"ai-{uuid.uuid4().hex[:10]}",
        name=pipeline_name,
        description=description[:500],
        nodes=nodes,
        edges=edges,
        metadata={"builder": "heuristic", "source_prompt": description[:1000]},
    )




# --- Schema-aware mapping enrichment (offline, no LLM required) ---

_DISCOVERABLE_SOURCES = {
    "excel_source",
    "local_file_source",
    "http_api_source",
    "kafka_source",
    "sqlite_source",
    "postgres_source",
    "mysql_source",
    "s3_source",
    "csv_parser",
}

# Short / idiomatic headers → preferred target names (after snake_case)
_TARGET_ALIASES = {
    "qty": "quantity",
    "amt": "amount",
    "sku": "product_sku",
}


def _work_dir() -> Path:
    env = os.environ.get("FORMULAETL_WORK_DIR")
    if env:
        return Path(env)
    # packages/api/formulaetl_api/ai_builder.py → repo root
    return Path(__file__).resolve().parents[3]


def to_snake_case(name: str) -> str:
    """Match SchemaMapper UI: CamelCase / spaces / punctuation → snake_case."""
    s = str(name).strip()
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    s = re.sub(r"[^A-Za-z0-9]+", "_", s)
    s = re.sub(r"^_+|_+$", "", s)
    return s.lower()


def preferred_target_name(source: str) -> str:
    snake = to_snake_case(source)
    return _TARGET_ALIASES.get(snake, snake)


def parse_prompt_renames(text: str) -> dict[str, str]:
    """Extract explicit renames from the English prompt (source → target)."""
    renames: dict[str, str] = {}
    patterns = [
        # rename/map "Order ID" to order_id  (quoted source)
        re.compile(
            r"(?:rename|map)\s+[\"']([^\"']+)[\"']\s+to\s+[\"']?([A-Za-z_][A-Za-z0-9_]*)[\"']?",
            re.IGNORECASE,
        ),
        # rename/map Order ID to order_id  (multi-word Title/spaced, not "columns from…")
        re.compile(
            r"(?:rename|map)\s+([A-Za-z][A-Za-z0-9]*(?:[ \-][A-Za-z0-9]+)+)\s+to\s+([a-z_][a-z0-9_]*)\b",
            re.IGNORECASE,
        ),
        # "Customer Name" → client_name
        re.compile(
            r"[\"']([^\"']+)[\"']\s*(?:→|->|=>)\s*[\"']?([A-Za-z_][A-Za-z0-9_]*)[\"']?",
        ),
        # bare: Order ID → order_id (Title Case phrase → snake ident)
        re.compile(
            r"\b([A-Z][A-Za-z0-9]*(?:[ \-][A-Za-z0-9]+)+)\s*(?:→|->|to)\s+([a-z_][a-z0-9_]*)\b",
        ),
    ]
    skip_src = {"columns", "column", "fields", "field", "them", "it"}
    for pat in patterns:
        for m in pat.finditer(text):
            src, tgt = m.group(1).strip(), m.group(2).strip()
            if not src or not tgt:
                continue
            # Avoid "map columns from camelCase to snake_case"
            if src.casefold().split()[0] in skip_src:
                continue
            if " from " in src.casefold():
                continue
            renames[src] = tgt
            renames[src.casefold()] = tgt
    return renames


def _resolve_target(source: str, prompt_renames: dict[str, str]) -> str:
    if source in prompt_renames:
        return prompt_renames[source]
    if source.casefold() in prompt_renames:
        return prompt_renames[source.casefold()]
    snake = to_snake_case(source)
    if snake in prompt_renames:
        return prompt_renames[snake]
    return preferred_target_name(source)


def build_column_map_mappings(
    column_names: list[str], prompt_renames: dict[str, str] | None = None
) -> list[str]:
    prompt_renames = prompt_renames or {}
    out: list[str] = []
    for name in column_names:
        tgt = _resolve_target(name, prompt_renames)
        out.append(f"{name}:{tgt}")
    return out


def build_tmap_mappings(
    column_names: list[str],
    prompt_renames: dict[str, str] | None = None,
    *,
    want_upper: bool = False,
    want_calc: bool = False,
) -> list[str]:
    """Build out=col(\"Source\") style mappings; optionally spice with upper/calc."""
    prompt_renames = prompt_renames or {}
    out: list[str] = []
    amount_src: str | None = None
    name_src: str | None = None
    for name in column_names:
        tgt = _resolve_target(name, prompt_renames)
        low = name.casefold()
        if amount_src is None and ("amount" in low or low == "amt"):
            amount_src = name
        # Prefer *name* columns for upper() demos (not customer_id)
        if "name" in low and (name_src is None or "name" not in name_src.casefold()):
            name_src = name
        # Prefer col("Source") so SchemaMapper / Excel headers round-trip cleanly
        expr = f'col("{name}")'
        out.append(f"{tgt}={expr}")

    # Overlay expression demos when prompt asks for them
    rewritten: list[str] = []
    for line in out:
        tgt, expr = line.split("=", 1)
        src_guess = None
        for name in column_names:
            if _resolve_target(name, prompt_renames) == tgt:
                src_guess = name
                break
        if want_upper and src_guess and name_src and src_guess == name_src:
            rewritten.append(f'{tgt}=upper(col("{src_guess}"))')
        elif want_calc and src_guess and amount_src and src_guess == amount_src:
            rewritten.append(f'{tgt}=float(col("{src_guess}"))*1.1')
        else:
            rewritten.append(line)
    return rewritten


def build_python_row_code(column_names: list[str], prompt: str) -> str:
    """Small safe sandbox example using discovered column names."""
    names_cf = {n.casefold(): n for n in column_names}
    # Prefer a name-like and amount-like column
    name_col = None
    for key in ("customer_name", "customername", "customer name", "name"):
        if key in names_cf:
            name_col = names_cf[key]
            break
    if name_col is None:
        for n in column_names:
            if "name" in n.casefold():
                name_col = n
                break
    amount_col = None
    for key in ("amount", "amt", "unit_price", "unitprice"):
        if key in names_cf:
            amount_col = names_cf[key]
            break
    if amount_col is None:
        for n in column_names:
            if any(k in n.casefold() for k in ("amount", "price", "amt")):
                amount_col = n
                break

    lines = [
        "row['loaded_by'] = 'formulaetl'",
    ]
    want_upper = _has(prompt, "upper", "uppercase", "toupper")
    want_calc = _has(prompt, "calculate", "calc", "multiply", "* 1.1", "markup")
    if name_col and (want_upper or _has(prompt, "python", "java", "flex", "script")):
        lines.append(
            f"row[{name_col!r}] = str(row.get({name_col!r}) or '').upper()"
        )
    if amount_col and (want_calc or True):
        # Always include a gentle numeric coerce using discovered amount-like col
        lines.append(
            f"row['amount'] = float(row.get({amount_col!r}) or row.get('amount') or 0)"
        )
    elif not amount_col:
        lines.append(
            "row['amount'] = float(row.get('amount') or row.get('unit_price') or 0)"
        )
    return "\n".join(lines)


def _discover_columns_for_pipeline(
    pipeline: PipelineDefinition, work_dir: Path | None = None
) -> tuple[list[str], dict[str, Any] | None, str | None]:
    """Return (column_names, schema_dict, source_node_id) from first discoverable source."""
    from formulaetl.schema.discover import discover

    wd = work_dir or _work_dir()
    for node in pipeline.nodes:
        if node.type not in _DISCOVERABLE_SOURCES:
            continue
        try:
            schema = discover(
                node.type,
                dict(node.config or {}),
                work_dir=wd,
                demo_mode=os.environ.get("FORMULAETL_DEMO", "1") == "1",
            )
        except Exception:
            continue
        cols = schema.get("columns") or []
        names = [str(c.get("name")) for c in cols if c.get("name")]
        if names:
            return names, schema, node.id
    return [], None, None


def enrich_pipeline_with_discovered_mappings(
    pipeline: PipelineDefinition,
    description: str,
    *,
    work_dir: Path | None = None,
) -> PipelineDefinition:
    """After graph build: discover source schema and populate map/tmap/python_row."""
    text = description or ""
    prompt_implies_map = _has(
        text,
        "map",
        "transform",
        "excel",
        "xlsx",
        "api",
        "column",
        "rename",
        "tmap",
        "schema",
    )
    # Always try discover for pipelines that already have map/tmap/python nodes
    has_map_nodes = any(n.type in ("column_map", "tmap", "python_row") for n in pipeline.nodes)
    if not prompt_implies_map and not has_map_nodes:
        return pipeline

    names, schema, source_id = _discover_columns_for_pipeline(pipeline, work_dir=work_dir)
    if not names:
        return pipeline

    prompt_renames = parse_prompt_renames(text)
    want_upper = _has(text, "upper", "uppercase", "toupper")
    want_calc = _has(text, "calculate", "calc", "multiply", "markup", "1.1")
    want_custom = want_upper or want_calc or _has(
        text, "python", "java", "flex", "script", "tjavarow", "tjavaflex", "code"
    )

    col_map_lines = build_column_map_mappings(names, prompt_renames)
    tmap_lines = build_tmap_mappings(
        names,
        prompt_renames,
        want_upper=want_upper,
        want_calc=want_calc,
    )

    # Attach discovered_schema onto source for SchemaMapper UI
    new_nodes: list[NodeDefinition] = []
    for node in pipeline.nodes:
        cfg = dict(node.config or {})
        if source_id and node.id == source_id and schema is not None:
            cfg["discovered_schema"] = {
                "columns": schema.get("columns") or [],
                **({"sample_rows": schema["sample_rows"]} if schema.get("sample_rows") else {}),
            }
        if node.type == "column_map":
            cfg["mappings"] = col_map_lines
            cfg.setdefault("drop_unmapped", False)
        elif node.type == "tmap":
            cfg["mappings"] = tmap_lines
            cfg.setdefault("drop_unmapped", False)
        elif node.type == "python_row":
            cfg["code"] = build_python_row_code(names, text)
            cfg.setdefault("mode", "row")
            cfg.setdefault("input_var", "row")
        new_nodes.append(node.model_copy(update={"config": cfg}))

    # If custom logic implied but no python_row node, insert one before destination
    if want_custom and not any(n.type == "python_row" for n in new_nodes):
        # Find a sensible insert point: before last destination-ish node
        dest_types = {
            "local_file_destination",
            "excel_destination",
            "sqlite_destination",
            "sftp_destination",
            "postgres_destination",
            "mysql_destination",
            "snowflake_destination",
            "databricks_job",
            "archive_files",
        }
        insert_at = len(new_nodes)
        for i, n in enumerate(new_nodes):
            if n.type in dest_types:
                insert_at = i
                break
        # Position near previous node
        prev = new_nodes[insert_at - 1] if insert_at > 0 else None
        px = float((prev.position or {}).get("x", 400)) + 220 if prev else 400.0
        py = float((prev.position or {}).get("y", 180)) if prev else 180.0
        py_node = NodeDefinition(
            id="py",
            type="python_row",
            label="Python Row",
            config={
                "mode": "row",
                "input_var": "row",
                "code": build_python_row_code(names, text),
            },
            position={"x": px, "y": py},
        )
        # Rewire: previous → py → former target of previous
        new_edges = list(pipeline.edges)
        if prev:
            # edges from prev to something → become prev→py and py→something
            rewired: list[EdgeDefinition] = []
            for e in new_edges:
                if e.source == prev.id and e.target != "py":
                    rewired.append(
                        EdgeDefinition(
                            id=f"e-{prev.id}-py",
                            source=prev.id,
                            target="py",
                            sourceHandle=e.sourceHandle,
                        )
                    )
                    rewired.append(
                        EdgeDefinition(
                            id=f"e-py-{e.target}",
                            source="py",
                            target=e.target,
                            sourceHandle=None,
                        )
                    )
                else:
                    rewired.append(e)
            new_edges = rewired
        new_nodes.insert(insert_at, py_node)
        meta = dict(pipeline.metadata or {})
        meta["schema_enriched"] = True
        meta["discovered_columns"] = names
        return pipeline.model_copy(
            update={"nodes": new_nodes, "edges": new_edges, "metadata": meta}
        )

    meta = dict(pipeline.metadata or {})
    meta["schema_enriched"] = True
    meta["discovered_columns"] = names
    return pipeline.model_copy(update={"nodes": new_nodes, "metadata": meta})


def llm_build(description: str, name: str | None = None) -> PipelineDefinition | None:
    """Optional LLM path when API keys are present. Returns None to fall back."""
    openai_key = os.environ.get("OPENAI_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if not openai_key and not anthropic_key:
        return None

    try:
        system = (
            "You are FormulaETL's pipeline architect. Reply with ONLY valid JSON matching "
            "PipelineDefinition: {id,name,description,nodes:[{id,type,label,config,position}],"
            "edges:[{id,source,target,sourceHandle?}]}. "
            "Allowed types: s3_source, local_file_source, http_api_source, kafka_source, excel_source, "
            "sqlite_source, sftp_source, postgres_source, mysql_source, pgp_decrypt, pgp_encrypt, "
            "csv_parser, json_parser, xml_parser, schema_validate, column_map, tmap, transform, "
            "filter, sort, aggregate, python_row, dedupe, lookup_join, local_file_destination, "
            "excel_destination, sqlite_destination, sftp_destination, postgres_destination, "
            "mysql_destination, snowflake_destination, databricks_job, archive_files, logger_metrics."
        )
        user = f"Build a pipeline for: {description}"

        if openai_key:
            import json
            import urllib.request

            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions",
                data=json.dumps(
                    {
                        "model": os.environ.get("FORMULAETL_LLM_MODEL", "gpt-4o-mini"),
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "temperature": 0.1,
                    }
                ).encode(),
                headers={
                    "Authorization": f"Bearer {openai_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode())
            content = payload["choices"][0]["message"]["content"]
            content = re.sub(r"^```(?:json)?\s*", "", content.strip())
            content = re.sub(r"\s*```$", "", content)
            data = json.loads(content)
            if name:
                data["name"] = name
            data.setdefault("id", f"ai-{uuid.uuid4().hex[:10]}")
            data.setdefault("metadata", {})["builder"] = "openai"
            return PipelineDefinition.model_validate(data)

        if anthropic_key:
            import json
            import urllib.request

            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=json.dumps(
                    {
                        "model": os.environ.get(
                            "FORMULAETL_LLM_MODEL", "claude-3-5-haiku-latest"
                        ),
                        "max_tokens": 4096,
                        "system": system,
                        "messages": [{"role": "user", "content": user}],
                    }
                ).encode(),
                headers={
                    "x-api-key": anthropic_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode())
            content = payload["content"][0]["text"]
            content = re.sub(r"^```(?:json)?\s*", "", content.strip())
            content = re.sub(r"\s*```$", "", content)
            data = json.loads(content)
            if name:
                data["name"] = name
            data.setdefault("id", f"ai-{uuid.uuid4().hex[:10]}")
            data.setdefault("metadata", {})["builder"] = "anthropic"
            return PipelineDefinition.model_validate(data)
    except Exception:
        return None
    return None


def build_pipeline_from_text(description: str, name: str | None = None) -> PipelineDefinition:
    """Public entry: try LLM when keyed, otherwise solid offline heuristic.

    Always runs schema-discover enrichment so column_map / tmap / python_row
    configs are populated from real source columns (offline, no API keys).
    """
    llm = llm_build(description, name=name)
    if llm is not None and llm.nodes:
        pipeline = llm
    else:
        pipeline = heuristic_build(description, name=name)
    return enrich_pipeline_with_discovered_mappings(pipeline, description)
