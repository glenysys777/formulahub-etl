"""Unit tests for the live wedge harness (no cloud calls)."""

from __future__ import annotations

import os
from pathlib import Path

from scripts.live_wedge_e2e import build_wedge_pipeline, check_credentials, run_wedge


def test_check_credentials_unproven_without_env(monkeypatch):
    for k in list(os.environ):
        if k.startswith("LIVE_") or k in (
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "SF_PASS",
            "FORMULAETL_SFTP_PASSWORD",
            "FORMULAETL_POSTGRES_PASSWORD",
        ):
            monkeypatch.delenv(k, raising=False)
    report = check_credentials()
    assert report.ok is False
    assert report.missing


def test_run_wedge_skips_without_flag(monkeypatch):
    monkeypatch.delenv("RUN_LIVE_WEDGE", raising=False)
    result = run_wedge()
    assert result["status"] == "skipped"
    assert result["evidence"] == "UNPROVEN"


def test_build_pipeline_shapes(monkeypatch, tmp_path: Path):
    key = tmp_path / "key.asc"
    key.write_text("-----BEGIN PGP PRIVATE KEY BLOCK-----\n", encoding="utf-8")
    monkeypatch.setenv("LIVE_S3_BUCKET", "partner-bucket")
    monkeypatch.setenv("LIVE_S3_KEY", "inbox/orders.csv.pgp")
    monkeypatch.setenv("LIVE_PGP_PRIVATE_KEY_PATH", str(key))
    monkeypatch.setenv("LIVE_SNOWFLAKE_ACCOUNT", "xy12345")
    monkeypatch.setenv("LIVE_SNOWFLAKE_USER", "etl")
    monkeypatch.setenv("LIVE_SNOWFLAKE_PASSWORD", "secret")
    monkeypatch.setenv("LIVE_SNOWFLAKE_WAREHOUSE", "WH")
    monkeypatch.setenv("LIVE_SNOWFLAKE_DATABASE", "DB")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAtest")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")

    report = check_credentials()
    assert report.ok is True
    assert report.source == "s3"
    assert report.dest == "snowflake"

    pipe = build_wedge_pipeline(source="s3", dest="snowflake")
    types = [n["type"] for n in pipe["nodes"]]
    assert types == [
        "s3_source",
        "pgp_decrypt",
        "csv_parser",
        "schema_validate",
        "column_map",
        "snowflake_destination",
        "archive_files",
    ]
    assert pipe["metadata"]["live_wedge"] is True
    assert pipe["metadata"]["demo"] is False


def test_build_sftp_postgres_variant(monkeypatch, tmp_path: Path):
    key = tmp_path / "key.asc"
    key.write_text("-----BEGIN PGP PRIVATE KEY BLOCK-----\n", encoding="utf-8")
    monkeypatch.setenv("LIVE_SOURCE", "sftp")
    monkeypatch.setenv("LIVE_DEST", "postgres")
    monkeypatch.setenv("LIVE_SFTP_HOST", "sftp.partner.example")
    monkeypatch.setenv("LIVE_SFTP_USER", "etl")
    monkeypatch.setenv("LIVE_SFTP_PASSWORD", "x")
    monkeypatch.setenv("LIVE_SFTP_REMOTE_PATH", "/inbox/orders.csv.pgp")
    monkeypatch.setenv("LIVE_PGP_PRIVATE_KEY_PATH", str(key))
    monkeypatch.setenv("LIVE_POSTGRES_HOST", "pg.partner.example")
    monkeypatch.setenv("LIVE_POSTGRES_USER", "etl")
    monkeypatch.setenv("LIVE_POSTGRES_PASSWORD", "x")
    monkeypatch.setenv("LIVE_POSTGRES_DATABASE", "orders")

    report = check_credentials()
    assert report.ok, report
    pipe = build_wedge_pipeline(source="sftp", dest="postgres")
    types = [n["type"] for n in pipe["nodes"]]
    assert types[0] == "sftp_source"
    assert types[-2] == "postgres_destination"
    assert types[-1] == "archive_files"
