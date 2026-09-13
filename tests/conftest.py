"""Shared pytest fixtures."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "runner"))
sys.path.insert(0, str(ROOT / "packages" / "api"))

os.environ["FORMULAETL_DEMO"] = "1"
os.environ["FORMULAETL_WORK_DIR"] = str(ROOT)


@pytest.fixture(scope="session", autouse=True)
def seed_demo_fixtures():
    """Ensure PGP keys + encrypted S3 object exist before any test."""
    from scripts.seed_demo import main

    # Make scripts importable
    sys.path.insert(0, str(ROOT))
    assert main() == 0
    yield


@pytest.fixture
def work_dir(tmp_path: Path) -> Path:
    """Isolated work dir with fixtures + demo S3 object copied in."""
    # Copy fixtures
    shutil.copytree(ROOT / "fixtures", tmp_path / "fixtures")
    s3_src = ROOT / "data" / "s3" / "demo" / "orders_encrypted.csv.pgp"
    dest = tmp_path / "data" / "s3" / "demo"
    dest.mkdir(parents=True)
    shutil.copy2(s3_src, dest / "orders_encrypted.csv.pgp")
    (tmp_path / "data" / "out" / "snowflake").mkdir(parents=True)
    (tmp_path / "data" / "out" / "sftp_mock").mkdir(parents=True)
    (tmp_path / "data" / "out" / "postgres_demo").mkdir(parents=True)
    (tmp_path / "data" / "out" / "mysql_demo").mkdir(parents=True)
    (tmp_path / "data" / "out" / "sftp_staging").mkdir(parents=True)
    (tmp_path / "data" / "archive").mkdir(parents=True)
    (tmp_path / "data" / "rejects").mkdir(parents=True)
    demo_db = ROOT / "data" / "demo.db"
    if demo_db.exists():
        shutil.copy2(demo_db, tmp_path / "data" / "demo.db")
    return tmp_path


@pytest.fixture
def demo_pipeline_dict():
    import json

    path = ROOT / "demos" / "s3-pgp-snowflake" / "pipeline.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def api_pipeline_dict():
    import json

    path = ROOT / "demos" / "api-map-transform" / "pipeline.json"
    return json.loads(path.read_text(encoding="utf-8"))
