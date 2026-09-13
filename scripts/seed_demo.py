#!/usr/bin/env python3
"""Generate demo fixtures: sample CSV, PGP keypair, encrypted file under data/s3."""

from __future__ import annotations

import csv
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
KEYS = FIXTURES / "keys"
SAMPLE = FIXTURES / "sample"
DATA_S3 = ROOT / "data" / "s3" / "demo"
DATA_OUT = ROOT / "data" / "out" / "snowflake"
DATA_ARCHIVE = ROOT / "data" / "archive"
DATA_REJECTS = ROOT / "data" / "rejects"
DATA_DEMO_DB = ROOT / "data" / "demo.db"
DATA_SFTP_MOCK = ROOT / "data" / "out" / "sftp_mock"
DATA_PG_DEMO = ROOT / "data" / "out" / "postgres_demo"

# 17-column customer orders schema
COLUMNS = [
    "order_id",       # int
    "customer_id",    # int
    "customer_name",  # string
    "email",          # email
    "phone",          # string
    "country",        # string
    "city",           # string
    "product_sku",    # string
    "product_name",   # string
    "quantity",       # int
    "unit_price",     # float
    "currency",       # string
    "order_date",     # date (various formats → transform)
    "ship_date",      # date
    "status",         # string
    "channel",        # string
    "notes",          # string
]


def make_rows() -> list[dict[str, str]]:
    """Return mix of good + bad rows for schema validation demo."""
    base = date(2024, 1, 15)
    good: list[dict[str, str]] = []
    for i in range(1, 11):
        good.append({
            "order_id": str(1000 + i),
            "customer_id": str(200 + i),
            "customer_name": f"Customer {i}",
            "email": f"customer{i}@example.com",
            "phone": f"+1-555-010{i:02d}",
            "country": "US" if i % 2 else "CA",
            "city": "Austin" if i % 2 else "Toronto",
            "product_sku": f"SKU-{i:04d}",
            "product_name": f"Widget {i}",
            "quantity": str(i),
            "unit_price": f"{9.99 + i:.2f}",
            "currency": "USD",
            # Mix of date formats for Transform to normalize
            "order_date": (base + timedelta(days=i)).strftime("%m/%d/%Y") if i % 2 else (base + timedelta(days=i)).strftime("%Y-%m-%d"),
            "ship_date": (base + timedelta(days=i + 3)).strftime("%Y-%m-%d"),
            "status": "shipped" if i < 8 else "pending",
            "channel": "web" if i % 3 else "partner",
            "notes": f"order note {i}",
        })

    bad: list[dict[str, str]] = [
        {  # bad email, bad quantity
            "order_id": "9991",
            "customer_id": "301",
            "customer_name": "Bad Email Co",
            "email": "not-an-email",
            "phone": "+1-555-9999",
            "country": "US",
            "city": "Nowhere",
            "product_sku": "SKU-BAD1",
            "product_name": "Broken Widget",
            "quantity": "abc",
            "unit_price": "12.50",
            "currency": "USD",
            "order_date": "2024-02-01",
            "ship_date": "2024-02-05",
            "status": "pending",
            "channel": "web",
            "notes": "invalid email and quantity",
        },
        {  # missing required email, bad unit_price
            "order_id": "9992",
            "customer_id": "302",
            "customer_name": "Missing Fields",
            "email": "",
            "phone": "+1-555-8888",
            "country": "US",
            "city": "Emptyville",
            "product_sku": "SKU-BAD2",
            "product_name": "Ghost Widget",
            "quantity": "2",
            "unit_price": "NaN",
            "currency": "USD",
            "order_date": "02/30/2024",  # invalid date
            "ship_date": "2024-03-01",
            "status": "cancelled",
            "channel": "web",
            "notes": "missing email, bad price/date",
        },
        {  # bad order_id (not int)
            "order_id": "ORD-X",
            "customer_id": "xxx",
            "customer_name": "Type Chaos",
            "email": "chaos@example.com",
            "phone": "n/a",
            "country": "XX",
            "city": "Null Island",
            "product_sku": "",
            "product_name": "",
            "quantity": "-1",
            "unit_price": "0",
            "currency": "ZZZ",
            "order_date": "yesterday",
            "ship_date": "tomorrow",
            "status": "???",
            "channel": "",
            "notes": "many type failures",
        },
    ]
    return good + bad


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def generate_pgp_keys() -> tuple[Path, Path]:
    """Generate RSA keypair with PGPy; write to fixtures/keys/."""
    import pgpy
    from pgpy.constants import (
        PubKeyAlgorithm,
        KeyFlags,
        HashAlgorithm,
        SymmetricKeyAlgorithm,
        CompressionAlgorithm,
    )

    KEYS.mkdir(parents=True, exist_ok=True)
    priv_path = KEYS / "demo_private.asc"
    pub_path = KEYS / "demo_public.asc"

    key = pgpy.PGPKey.new(PubKeyAlgorithm.RSAEncryptOrSign, 2048)
    uid = pgpy.PGPUID.new("FormulaETL Demo", email="demo@formulaetl.local")
    key.add_uid(
        uid,
        usage={KeyFlags.Sign, KeyFlags.EncryptCommunications, KeyFlags.EncryptStorage},
        hashes=[HashAlgorithm.SHA256],
        ciphers=[SymmetricKeyAlgorithm.AES256],
        compression=[CompressionAlgorithm.Uncompressed],
    )

    priv_path.write_text(str(key), encoding="utf-8")
    pub_path.write_text(str(key.pubkey), encoding="utf-8")
    # Empty passphrase marker for docs
    (KEYS / "README.md").write_text(
        "# Demo PGP keys\n\nGenerated by `scripts/seed_demo.py`.\n"
        "Private key has **no passphrase** for demo convenience.\n"
        "Do not use these keys in production.\n",
        encoding="utf-8",
    )
    return priv_path, pub_path


def encrypt_file(csv_path: Path, pub_path: Path, out_path: Path) -> None:
    import pgpy
    from pgpy.constants import CompressionAlgorithm

    pub, _ = pgpy.PGPKey.from_blob(pub_path.read_text())
    msg = pgpy.PGPMessage.new(csv_path.read_text(encoding="utf-8"))
    encrypted = pub.encrypt(msg, compression=CompressionAlgorithm.Uncompressed)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(bytes(encrypted))


def main() -> int:
    print("Seeding FormulaETL demo fixtures…")
    for d in (DATA_S3, DATA_OUT, DATA_ARCHIVE, DATA_REJECTS, SAMPLE, KEYS, DATA_SFTP_MOCK, DATA_PG_DEMO):
        d.mkdir(parents=True, exist_ok=True)

    rows = make_rows()
    csv_path = SAMPLE / "orders_17cols.csv"
    write_csv(csv_path, rows)
    print(f"  wrote {csv_path} ({len(rows)} rows, {len(COLUMNS)} columns)")

    priv, pub = generate_pgp_keys()
    print(f"  wrote PGP keys → {priv.name}, {pub.name}")

    enc_path = DATA_S3 / "orders_encrypted.csv.pgp"
    encrypt_file(csv_path, pub, enc_path)
    print(f"  wrote encrypted object → {enc_path}")

    # Plaintext sample already at fixtures/sample/orders_17cols.csv
    print(f"  sample CSV ready at {csv_path}")

    # Local SQLite DB — demo stand-in for Postgres/JDBC
    if DATA_DEMO_DB.exists():
        DATA_DEMO_DB.unlink()
    conn = sqlite3.connect(str(DATA_DEMO_DB))
    try:
        cols_sql = ", ".join(f'"{c}" TEXT' for c in COLUMNS)
        col_list = ", ".join(f'"{c}"' for c in COLUMNS)
        placeholders = ", ".join("?" for _ in COLUMNS)
        conn.execute(f"CREATE TABLE orders ({cols_sql})")
        conn.executemany(
            f"INSERT INTO orders ({col_list}) VALUES ({placeholders})",
            [tuple(r[c] for c in COLUMNS) for r in rows],
        )
        conn.execute(
            'CREATE TABLE customers (customer_id TEXT, segment TEXT, region TEXT)'
        )
        cust = {}
        for r in rows:
            cid = r["customer_id"]
            if not str(cid).isdigit():
                continue
            if cid not in cust:
                cust[cid] = (
                    cid,
                    "enterprise" if int(cid) % 2 == 0 else "smb",
                    "NA" if r["country"] in ("US", "CA") else "OTHER",
                )
        conn.executemany(
            "INSERT INTO customers (customer_id, segment, region) VALUES (?, ?, ?)",
            list(cust.values()),
        )
        conn.commit()
    finally:
        conn.close()
    print(f"  wrote {DATA_DEMO_DB} (orders + customers)")

    # Lookup CSV for join demos
    cust_csv = SAMPLE / "customers.csv"
    with cust_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["customer_id", "segment", "region"])
        w.writeheader()
        for cid, segment, region in cust.values():
            w.writerow({"customer_id": cid, "segment": segment, "region": region})
    print(f"  wrote {cust_csv}")

    # Clean runtime output dirs but keep structure
    for p in DATA_OUT.glob("*"):
        if p.is_file():
            p.unlink()
    for p in DATA_ARCHIVE.glob("*"):
        if p.is_file():
            p.unlink()
    for p in DATA_REJECTS.glob("*"):
        if p.is_file():
            p.unlink()

    # Ensure .gitkeep files
    for d in (DATA_S3.parent, DATA_OUT, DATA_ARCHIVE, DATA_REJECTS, DATA_SFTP_MOCK, DATA_PG_DEMO):
        (d / ".gitkeep").touch()

    print("Done. Demo object: data/s3/demo/orders_encrypted.csv.pgp")
    return 0


if __name__ == "__main__":
    sys.exit(main())
