"""Live wedge E2E harness (honest / opt-in).

Chain: S3|SFTP → PGP decrypt → CSV parse → schema_validate → column_map
       → Postgres|Snowflake → archive_files

Never claims PROVEN by itself. Without credentials this module reports what is
missing and exits 0 with status UNPROVEN / skipped.

Usage::

    # Inspect required env (always safe):
    python3 scripts/live_wedge_e2e.py --check

    # Attempt live run (requires RUN_LIVE_WEDGE=1 + credentials):
    RUN_LIVE_WEDGE=1 FORMULAETL_DEMO=0 python3 scripts/live_wedge_e2e.py

See docs/design-partner/LIVE_WEDGE.md.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class CredReport:
    ok: bool
    source: str | None = None  # "s3" | "sftp"
    dest: str | None = None  # "snowflake" | "postgres"
    missing: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "source": self.source,
            "dest": self.dest,
            "missing": self.missing,
            "notes": self.notes,
        }


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _has_aws_creds() -> bool:
    if _env("AWS_ACCESS_KEY_ID") and _env("AWS_SECRET_ACCESS_KEY"):
        return True
    if _env("AWS_PROFILE") or _env("AWS_ROLE_ARN"):
        return True
    return False


def check_credentials() -> CredReport:
    """Return whether a live wedge can run from the current environment."""
    report = CredReport(ok=False)
    missing: list[str] = []

    source_pref = (_env("LIVE_SOURCE") or "").lower()
    dest_pref = (_env("LIVE_DEST") or "").lower()

    s3_ready = bool(_env("LIVE_S3_BUCKET") and _env("LIVE_S3_KEY"))
    sftp_ready = bool(
        _env("LIVE_SFTP_HOST")
        and _env("LIVE_SFTP_USER")
        and _env("LIVE_SFTP_REMOTE_PATH")
        and (
            _env("LIVE_SFTP_PASSWORD")
            or _env("LIVE_SFTP_KEY_PATH")
            or _env("FORMULAETL_SFTP_PASSWORD")
        )
    )

    if source_pref == "s3":
        if not s3_ready:
            missing.extend([n for n in ("LIVE_S3_BUCKET", "LIVE_S3_KEY") if not _env(n)])
        elif not _has_aws_creds():
            report.notes.append(
                "LIVE_S3_* set; AWS keys/profile not in env — relying on default credential chain"
            )
        report.source = "s3" if s3_ready else None
    elif source_pref == "sftp":
        if not sftp_ready:
            for n in ("LIVE_SFTP_HOST", "LIVE_SFTP_USER", "LIVE_SFTP_REMOTE_PATH"):
                if not _env(n):
                    missing.append(n)
            if not (
                _env("LIVE_SFTP_PASSWORD")
                or _env("LIVE_SFTP_KEY_PATH")
                or _env("FORMULAETL_SFTP_PASSWORD")
            ):
                missing.append(
                    "LIVE_SFTP_PASSWORD|LIVE_SFTP_KEY_PATH|FORMULAETL_SFTP_PASSWORD"
                )
        report.source = "sftp" if sftp_ready else None
    else:
        if s3_ready:
            report.source = "s3"
            if not _has_aws_creds():
                report.notes.append(
                    "Using S3 source; AWS keys/profile not in env — default chain must work"
                )
        elif sftp_ready:
            report.source = "sftp"
        else:
            missing.append(
                "LIVE_SOURCE=s3|sftp plus matching LIVE_S3_* or LIVE_SFTP_* vars"
            )

    if not _env("LIVE_PGP_PRIVATE_KEY_PATH"):
        missing.append("LIVE_PGP_PRIVATE_KEY_PATH")
    else:
        pgp_path = Path(_env("LIVE_PGP_PRIVATE_KEY_PATH"))
        if not pgp_path.is_file():
            missing.append(f"LIVE_PGP_PRIVATE_KEY_PATH (file not found: {pgp_path})")

    sf_ready = bool(
        _env("LIVE_SNOWFLAKE_ACCOUNT")
        and _env("LIVE_SNOWFLAKE_USER")
        and (_env("LIVE_SNOWFLAKE_PASSWORD") or _env("SF_PASS"))
        and _env("LIVE_SNOWFLAKE_WAREHOUSE")
        and _env("LIVE_SNOWFLAKE_DATABASE")
    )
    pg_ready = bool(
        _env("LIVE_POSTGRES_DSN")
        or (
            _env("LIVE_POSTGRES_HOST")
            and _env("LIVE_POSTGRES_USER")
            and (_env("LIVE_POSTGRES_PASSWORD") or _env("FORMULAETL_POSTGRES_PASSWORD"))
            and _env("LIVE_POSTGRES_DATABASE")
        )
    )

    if dest_pref == "snowflake":
        if not sf_ready:
            for n in (
                "LIVE_SNOWFLAKE_ACCOUNT",
                "LIVE_SNOWFLAKE_USER",
                "LIVE_SNOWFLAKE_PASSWORD|SF_PASS",
                "LIVE_SNOWFLAKE_WAREHOUSE",
                "LIVE_SNOWFLAKE_DATABASE",
            ):
                if "|" in n:
                    if not any(_env(p) for p in n.split("|")):
                        missing.append(n)
                elif not _env(n):
                    missing.append(n)
        report.dest = "snowflake" if sf_ready else None
    elif dest_pref == "postgres":
        if not pg_ready:
            missing.append(
                "LIVE_POSTGRES_DSN or LIVE_POSTGRES_HOST+USER+PASSWORD+DATABASE"
            )
        report.dest = "postgres" if pg_ready else None
    else:
        if sf_ready:
            report.dest = "snowflake"
        elif pg_ready:
            report.dest = "postgres"
        else:
            missing.append(
                "LIVE_DEST=snowflake|postgres plus matching LIVE_SNOWFLAKE_* or LIVE_POSTGRES_* vars"
            )

    report.missing = missing
    report.ok = report.source is not None and report.dest is not None and not missing
    return report


def build_wedge_pipeline(*, source: str, dest: str) -> dict[str, Any]:
    """Build the live wedge DAG as a pipeline dict."""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    if source == "s3":
        cfg: dict[str, Any] = {
            "bucket": _env("LIVE_S3_BUCKET"),
            "key": _env("LIVE_S3_KEY"),
            "region": _env("LIVE_S3_REGION") or _env("AWS_DEFAULT_REGION") or "us-east-1",
        }
        if _env("LIVE_S3_ENDPOINT"):
            cfg["endpoint_url"] = _env("LIVE_S3_ENDPOINT")
        nodes.append(
            {"id": "src", "type": "s3_source", "label": "S3 Source (live)", "config": cfg}
        )
    else:
        sftp_cfg: dict[str, Any] = {
            "host": _env("LIVE_SFTP_HOST"),
            "port": int(_env("LIVE_SFTP_PORT") or "22"),
            "username": _env("LIVE_SFTP_USER"),
            "password": _env("LIVE_SFTP_PASSWORD")
            or _env("FORMULAETL_SFTP_PASSWORD")
            or "",
            "remote_path": _env("LIVE_SFTP_REMOTE_PATH"),
            "local_staging_path": _env("LIVE_SFTP_STAGING")
            or "data/out/sftp_staging/live_wedge",
        }
        if _env("LIVE_SFTP_KEY_PATH"):
            sftp_cfg["key_path"] = _env("LIVE_SFTP_KEY_PATH")
        nodes.append(
            {
                "id": "src",
                "type": "sftp_source",
                "label": "SFTP Source (live)",
                "config": sftp_cfg,
            }
        )

    nodes.append(
        {
            "id": "pgp",
            "type": "pgp_decrypt",
            "label": "PGP Decrypt (live)",
            "config": {
                "private_key_path": _env("LIVE_PGP_PRIVATE_KEY_PATH"),
                "passphrase": _env("LIVE_PGP_PASSPHRASE"),
            },
        }
    )
    nodes.append(
        {
            "id": "parse",
            "type": "csv_parser",
            "label": "CSV Parse",
            "config": {"delimiter": _env("LIVE_CSV_DELIMITER") or ","},
        }
    )

    columns_raw = _env("LIVE_VALIDATE_COLUMNS")
    columns = json.loads(columns_raw) if columns_raw else {"order_id": "string"}
    nodes.append(
        {
            "id": "validate",
            "type": "schema_validate",
            "label": "Schema Validate",
            "config": {
                "columns": columns,
                "required_columns": list(columns.keys())[:1],
                "strict": False,
            },
        }
    )

    mappings_raw = _env("LIVE_COLUMN_MAPPINGS")
    mappings = (
        [ln.strip() for ln in mappings_raw.split(",") if ln.strip()]
        if mappings_raw
        else ["order_id:order_id"]
    )
    nodes.append(
        {
            "id": "map",
            "type": "column_map",
            "label": "Column Map",
            "config": {"mappings": mappings, "drop_unmapped": False},
        }
    )

    if dest == "snowflake":
        nodes.append(
            {
                "id": "dest",
                "type": "snowflake_destination",
                "label": "Snowflake (live)",
                "config": {
                    "account": _env("LIVE_SNOWFLAKE_ACCOUNT"),
                    "user": _env("LIVE_SNOWFLAKE_USER"),
                    "password": _env("LIVE_SNOWFLAKE_PASSWORD") or _env("SF_PASS"),
                    "warehouse": _env("LIVE_SNOWFLAKE_WAREHOUSE"),
                    "database": _env("LIVE_SNOWFLAKE_DATABASE"),
                    "schema": _env("LIVE_SNOWFLAKE_SCHEMA") or "PUBLIC",
                    "table": _env("LIVE_SNOWFLAKE_TABLE") or "FORMULAETL_LIVE_WEDGE",
                },
            }
        )
    else:
        pg_cfg: dict[str, Any] = {
            "table": _env("LIVE_POSTGRES_TABLE") or "formulaetl_live_wedge",
            "if_exists": _env("LIVE_POSTGRES_IF_EXISTS") or "append",
        }
        if _env("LIVE_POSTGRES_DSN"):
            pg_cfg["dsn"] = _env("LIVE_POSTGRES_DSN")
        else:
            pg_cfg.update(
                {
                    "host": _env("LIVE_POSTGRES_HOST"),
                    "port": int(_env("LIVE_POSTGRES_PORT") or "5432"),
                    "database": _env("LIVE_POSTGRES_DATABASE"),
                    "user": _env("LIVE_POSTGRES_USER"),
                    "password": _env("LIVE_POSTGRES_PASSWORD")
                    or _env("FORMULAETL_POSTGRES_PASSWORD")
                    or "",
                }
            )
        nodes.append(
            {
                "id": "dest",
                "type": "postgres_destination",
                "label": "Postgres (live)",
                "config": pg_cfg,
            }
        )

    nodes.append(
        {
            "id": "archive",
            "type": "archive_files",
            "label": "Archive Source",
            "config": {
                "destination": _env("LIVE_ARCHIVE_DIR") or "data/archive/live_wedge/",
                "mode": _env("LIVE_ARCHIVE_MODE") or "copy",
            },
        }
    )

    order = ["src", "pgp", "parse", "validate", "map", "dest", "archive"]
    for i in range(len(order) - 1):
        edges.append(
            {"id": f"e{i + 1}", "source": order[i], "target": order[i + 1]}
        )

    return {
        "id": "live-wedge-e2e",
        "name": f"LIVE wedge: {source}→pgp→csv→validate→map→{dest}→archive",
        "description": (
            "Design-partner live harness. Not a demo. Requires FORMULAETL_DEMO=0 "
            "and real credentials. See docs/design-partner/LIVE_WEDGE.md."
        ),
        "version": "1.0",
        "nodes": nodes,
        "edges": edges,
        "metadata": {
            "demo": False,
            "live_wedge": True,
            "source": source,
            "dest": dest,
            "classification": "LIVE_CLOUD",
        },
    }


def run_wedge(*, work_dir: Path | None = None) -> dict[str, Any]:
    """Execute the live wedge. Returns skipped/UNPROVEN when gated off."""
    if _env("RUN_LIVE_WEDGE") != "1":
        return {
            "status": "skipped",
            "evidence": "UNPROVEN",
            "reason": "RUN_LIVE_WEDGE is not 1 — live wedge not attempted",
            "classification": "LIVE_CLOUD",
        }

    report = check_credentials()
    if not report.ok:
        return {
            "status": "skipped",
            "evidence": "UNPROVEN",
            "reason": "missing live credentials",
            "credentials": report.to_dict(),
            "classification": "LIVE_CLOUD",
        }

    os.environ["FORMULAETL_DEMO"] = "0"

    from formulaetl.engine.runner import PipelineRunner
    from formulaetl.models.pipeline import PipelineDefinition

    pipeline_dict = build_wedge_pipeline(
        source=report.source or "", dest=report.dest or ""
    )
    pipeline = PipelineDefinition.model_validate(pipeline_dict)
    work = Path(work_dir or _env("FORMULAETL_WORK_DIR") or ROOT)
    runner = PipelineRunner(work_dir=work, demo_mode=False)
    result = runner.run(pipeline)

    out: dict[str, Any] = {
        "status": result.status,
        "evidence": "PROVEN" if result.status == "success" else "FAILED",
        "run_id": result.run_id,
        "error": result.error,
        "duration_ms": result.duration_ms,
        "metrics": result.metrics,
        "node_metrics": result.node_metrics,
        "source": report.source,
        "dest": report.dest,
        "pipeline_id": pipeline_dict["id"],
        "classification": "LIVE_CLOUD",
    }
    if result.status != "success":
        out["logs_tail"] = (result.logs or [])[-20:]
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FormulaETL live wedge E2E (opt-in)")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only report credential readiness (never runs pipeline)",
    )
    parser.add_argument(
        "--print-pipeline",
        action="store_true",
        help="Print built pipeline JSON if credentials allow (redacts passwords)",
    )
    parser.add_argument("--work-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    report = check_credentials()
    if args.check:
        print(
            json.dumps(
                {"evidence": "UNPROVEN", "classification": "LIVE_CLOUD", "credentials": report.to_dict()},
                indent=2,
            )
        )
        return 0

    if args.print_pipeline:
        if not report.ok:
            print(
                json.dumps(
                    {"error": "missing credentials", "credentials": report.to_dict()},
                    indent=2,
                )
            )
            return 2
        pipe = build_wedge_pipeline(source=report.source or "", dest=report.dest or "")
        for n in pipe["nodes"]:
            cfg = n.get("config") or {}
            for k in list(cfg):
                if k in ("password", "passphrase", "secret_access_key"):
                    cfg[k] = "***"
        print(json.dumps(pipe, indent=2))
        return 0

    result = run_wedge(work_dir=args.work_dir)
    print(json.dumps(result, indent=2, default=str))
    if result.get("status") == "skipped":
        return 0
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
