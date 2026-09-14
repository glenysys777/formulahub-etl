#!/usr/bin/env python3
"""Customer001 LOCAL wedge harness — filesystem + optional local Postgres.

Classification
--------------
* ``LOCAL_PROVEN`` — real local filesystem + real local Postgres INSERT
  (``FORMULAETL_DEMO=0`` + ``LOCAL_POSTGRES_DSN`` / host).
* ``LOCAL/DEMO`` — same DAG with postgres_destination demo SQLite/CSV mirror
  (default CI / no Postgres).
* Never ``LIVE_EXTERNAL`` — no SFTP/S3/Snowflake/Databricks credentials.

Chain::

    local encrypted drop → PGP → CSV → schema_validate → Field Mapper
        → lookup → dedupe → rejects → Postgres → archive

Reconciliation (must hold)::

    N (parsed) = R (validate rejects) + D (dedupe drops) + L (loaded)

Usage::

    # DEMO mirror (always safe):
    python3 scripts/customer001_local_wedge.py --mode demo

    # Real local Postgres:
    FORMULAETL_DEMO=0 LOCAL_POSTGRES_DSN='host=127.0.0.1 dbname=formulaetl user=formula password=formula' \\
        python3 scripts/customer001_local_wedge.py --mode postgres

    # Credential / readiness check only:
    python3 scripts/customer001_local_wedge.py --check

See docs/CUSTOMER001_LOCAL_WEDGE.md.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import shutil
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "fixtures" / "customer001_local_wedge"
PIPELINE_PATH = ROOT / "demos" / "customer001-local-wedge" / "pipeline.json"
DROP_REL = Path("data/drop/customer001/orders.csv.pgp")
EXPECTED_PATH = FIXTURE_DIR / "expected_counts.json"


@dataclass
class WedgeReport:
    classification: str = "LOCAL/DEMO"
    evidence: str = "UNPROVEN"
    status: str = "failed"
    mode: str = "demo"
    elapsed_s: float = 0.0
    peak_rss_mb: float | None = None
    files_in: int = 0
    bytes_in: int = 0
    files_archived: int = 0
    bytes_archived: int = 0
    input_n: int = 0
    rejected_r: int = 0
    deduped_d: int = 0
    loaded_l: int = 0
    expected_n: int = 12
    expected_r: int = 2
    expected_d: int = 2
    expected_l: int = 8
    reconcile_ok: bool = False
    reconcile_equation: str = "N = R + D + L"
    node_timings_ms: dict[str, float] = field(default_factory=dict)
    node_metrics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    notes: list[str] = field(default_factory=list)
    postgres_mode: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def peak_rss_mb() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if usage > 10_000_000:
        return usage / (1024.0 * 1024.0)
    return usage / 1024.0


def load_expected() -> dict[str, Any]:
    if EXPECTED_PATH.exists():
        return json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))
    return {"N": 12, "R": 2, "D": 2, "L": 8}


def ensure_drop_file(work_dir: Path) -> Path:
    """Encrypt fixture CSV with current demo public key into the local drop folder."""
    csv_path = work_dir / "fixtures" / "customer001_local_wedge" / "orders.csv"
    if not csv_path.exists():
        csv_path = FIXTURE_DIR / "orders.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"missing {csv_path}")

    pub = work_dir / "fixtures" / "keys" / "demo_public.asc"
    if not pub.exists():
        pub = ROOT / "fixtures" / "keys" / "demo_public.asc"
    if not pub.exists():
        raise FileNotFoundError(f"missing demo public key at {pub}; run scripts/seed_demo.py")

    import pgpy
    from pgpy.constants import CompressionAlgorithm

    key, _ = pgpy.PGPKey.from_blob(pub.read_text(encoding="utf-8"))
    msg = pgpy.PGPMessage.new(csv_path.read_bytes(), file=True)
    try:
        cipher = key.encrypt(msg, compression=CompressionAlgorithm.Uncompressed)
    except TypeError:
        cipher = key.encrypt(msg)

    drop = work_dir / DROP_REL
    drop.parent.mkdir(parents=True, exist_ok=True)
    drop.write_bytes(str(cipher).encode("utf-8"))

    # Keep fixture pgp in sync when working from repo root
    fixture_pgp = work_dir / "fixtures" / "customer001_local_wedge" / "orders.csv.pgp"
    if fixture_pgp.parent.exists():
        fixture_pgp.write_bytes(drop.read_bytes())
    return drop


def prepare_fixtures(work_dir: Path | None = None) -> Path:
    """Ensure drop + lookup fixtures exist under work_dir (default repo root)."""
    work = work_dir or ROOT
    keys = work / "fixtures" / "keys" / "demo_private.asc"
    if not keys.exists():
        from scripts.seed_demo import main as seed_main

        seed_main()
    # Copy fixture tree if running from a tmp work_dir
    if work.resolve() != ROOT.resolve():
        dst = work / "fixtures" / "customer001_local_wedge"
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(FIXTURE_DIR, dst)
        keys_dst = work / "fixtures" / "keys"
        keys_dst.mkdir(parents=True, exist_ok=True)
        for name in ("demo_private.asc", "demo_public.asc"):
            src = ROOT / "fixtures" / "keys" / name
            if src.exists():
                shutil.copy2(src, keys_dst / name)
    return ensure_drop_file(work)


def postgres_env_ready() -> tuple[bool, str, dict[str, Any]]:
    """Return (ok, reason, config) for real local Postgres."""
    cfg: dict[str, Any] = {
        "table": os.environ.get("LOCAL_POSTGRES_TABLE") or "customer001_orders",
        "if_exists": os.environ.get("LOCAL_POSTGRES_IF_EXISTS") or "replace",
    }
    dsn = os.environ.get("LOCAL_POSTGRES_DSN") or os.environ.get("LIVE_POSTGRES_DSN")
    if dsn:
        cfg["dsn"] = dsn
    else:
        host = os.environ.get("LOCAL_POSTGRES_HOST") or os.environ.get("PGHOST")
        if not host:
            return False, "LOCAL_POSTGRES_DSN or LOCAL_POSTGRES_HOST not set", cfg
        cfg.update(
            {
                "host": host,
                "port": int(os.environ.get("LOCAL_POSTGRES_PORT") or os.environ.get("PGPORT") or "5432"),
                "database": os.environ.get("LOCAL_POSTGRES_DATABASE")
                or os.environ.get("PGDATABASE")
                or "formulaetl",
                "user": os.environ.get("LOCAL_POSTGRES_USER") or os.environ.get("PGUSER") or "formula",
                "password": os.environ.get("LOCAL_POSTGRES_PASSWORD")
                or os.environ.get("PGPASSWORD")
                or os.environ.get("FORMULAETL_POSTGRES_PASSWORD")
                or "",
            }
        )
    # Connectivity probe
    try:
        import psycopg

        dsn_str = cfg.get("dsn")
        if not dsn_str:
            dsn_str = (
                f"host={cfg['host']} port={cfg['port']} dbname={cfg['database']} "
                f"user={cfg['user']} password={cfg.get('password') or ''}"
            )
        with psycopg.connect(dsn_str, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return True, "postgres reachable", cfg
    except Exception as exc:  # noqa: BLE001 — readiness probe
        return False, f"postgres unreachable: {exc}", cfg


def build_pipeline(*, mode: str, pg_cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    pipe = json.loads(PIPELINE_PATH.read_text(encoding="utf-8"))
    if mode == "postgres":
        if not pg_cfg:
            raise ValueError("postgres mode requires pg_cfg")
        for node in pipe["nodes"]:
            if node["id"] == "dest":
                node["config"] = dict(pg_cfg)
                node["label"] = "Postgres (LOCAL)"
        pipe["metadata"]["demo"] = False
        pipe["metadata"]["requires_demo_mode"] = False
        pipe["metadata"]["classification"] = "LOCAL_PROVEN"
        pipe["metadata"]["honesty"] = (
            "LOCAL filesystem + LOCAL Postgres INSERT. NOT LIVE_EXTERNAL."
        )
    else:
        pipe["metadata"]["classification"] = "LOCAL/DEMO"
    return pipe


def reconcile(n: int, r: int, d: int, l: int) -> tuple[bool, str]:
    ok = n == r + d + l
    return ok, f"N={n} R={r} D={d} L={l} → R+D+L={r + d + l}"


def _metric(node_metrics: dict[str, Any], node_id: str, key: str, default: int = 0) -> int:
    m = node_metrics.get(node_id) or {}
    return int(m.get(key, default) or default)


def run_wedge(
    *,
    mode: str = "demo",
    work_dir: Path | None = None,
    prepare: bool = True,
) -> WedgeReport:
    """Execute the customer001 LOCAL wedge and return a reconciliation report."""
    expected = load_expected()
    report = WedgeReport(
        mode=mode,
        expected_n=int(expected.get("N", 12)),
        expected_r=int(expected.get("R", 2)),
        expected_d=int(expected.get("D", 2)),
        expected_l=int(expected.get("L", 8)),
        notes=[],
    )

    work = Path(work_dir or os.environ.get("FORMULAETL_WORK_DIR") or ROOT)
    if prepare:
        drop = prepare_fixtures(work)
    else:
        drop = work / DROP_REL
        if not drop.exists():
            report.status = "failed"
            report.evidence = "FAILED"
            report.error = f"drop missing (prepare=False): {drop}"
            report.classification = "LOCAL_ONLY"
            return report
    report.files_in = 1
    report.bytes_in = drop.stat().st_size

    pg_cfg: dict[str, Any] | None = None
    if mode == "postgres":
        ok, reason, pg_cfg = postgres_env_ready()
        if not ok:
            report.status = "skipped"
            report.evidence = "UNPROVEN"
            report.classification = "LOCAL_ONLY"
            report.error = reason
            report.notes.append("LOCAL_ONLY marker — Postgres not available; not LIVE_EXTERNAL")
            return report
        os.environ["FORMULAETL_DEMO"] = "0"
        report.classification = "LOCAL_PROVEN"
        report.notes.append("FORMULAETL_DEMO=0 + real local Postgres DSN")
        demo_mode = False
    else:
        os.environ["FORMULAETL_DEMO"] = "1"
        report.classification = "LOCAL/DEMO"
        report.notes.append("DEMO postgres mirror (SQLite/CSV) — not a live INSERT")
        demo_mode = True

    from formulaetl.engine.runner import PipelineRunner
    from formulaetl.models.pipeline import PipelineDefinition

    pipeline_dict = build_pipeline(mode=mode, pg_cfg=pg_cfg)
    pipeline = PipelineDefinition.model_validate(pipeline_dict)
    runner = PipelineRunner(work_dir=work, demo_mode=demo_mode)

    t0 = time.perf_counter()
    try:
        result = runner.run(pipeline)
    except Exception as exc:  # noqa: BLE001
        report.status = "failed"
        report.evidence = "FAILED"
        report.error = str(exc)
        report.elapsed_s = time.perf_counter() - t0
        report.peak_rss_mb = peak_rss_mb()
        return report

    report.elapsed_s = time.perf_counter() - t0
    report.peak_rss_mb = peak_rss_mb()
    report.node_metrics = result.node_metrics or {}
    report.node_timings_ms = {
        nid: float((m or {}).get("duration_ms") or 0.0)
        for nid, m in report.node_metrics.items()
    }

    n = _metric(report.node_metrics, "parse", "rows_out")
    r = _metric(report.node_metrics, "validate", "rows_rejected")
    d = _metric(report.node_metrics, "dedupe", "rows_rejected")
    l = _metric(report.node_metrics, "dest", "rows_out")
    report.input_n = n
    report.rejected_r = r
    report.deduped_d = d
    report.loaded_l = l
    ok, eq = reconcile(n, r, d, l)
    report.reconcile_ok = ok
    report.reconcile_equation = eq

    # Archive evidence
    archive_dir = work / "data" / "archive" / "customer001"
    archived = list(archive_dir.glob("orders.csv.pgp")) if archive_dir.exists() else []
    report.files_archived = len(archived)
    report.bytes_archived = sum(p.stat().st_size for p in archived)

    dest_side = None
    # Best-effort: infer postgres mode from metrics extras if present
    dest_m = report.node_metrics.get("dest") or {}
    report.postgres_mode = "postgres" if mode == "postgres" else "demo"

    if result.status != "success":
        report.status = "failed"
        report.evidence = "FAILED"
        report.error = result.error
        report.notes.append(f"run_id={result.run_id}")
        return report

    counts_match = (
        n == report.expected_n
        and r == report.expected_r
        and d == report.expected_d
        and l == report.expected_l
    )
    if not ok or not counts_match:
        report.status = "failed"
        report.evidence = "FAILED"
        report.error = (
            f"reconciliation mismatch: {eq}; "
            f"expected N={report.expected_n} R={report.expected_r} "
            f"D={report.expected_d} L={report.expected_l}"
        )
        return report

    if report.files_archived < 1:
        report.status = "failed"
        report.evidence = "FAILED"
        report.error = "archive missing — expected copied drop file"
        return report

    report.status = "success"
    report.evidence = "PROVEN"
    if mode == "postgres":
        report.notes.append("LOCAL_PROVEN — real local Postgres write")
        # Verify row count in Postgres when possible
        try:
            import psycopg

            dsn = pg_cfg.get("dsn") if pg_cfg else None
            if not dsn and pg_cfg:
                dsn = (
                    f"host={pg_cfg['host']} port={pg_cfg['port']} dbname={pg_cfg['database']} "
                    f"user={pg_cfg['user']} password={pg_cfg.get('password') or ''}"
                )
            table = (pg_cfg or {}).get("table") or "customer001_orders"
            with psycopg.connect(dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(f'SELECT COUNT(*) FROM "{table}"')
                    db_count = int(cur.fetchone()[0])
            report.notes.append(f"postgres_count={db_count}")
            if db_count != l:
                report.status = "failed"
                report.evidence = "FAILED"
                report.error = f"Postgres COUNT(*)={db_count} != loaded L={l}"
                return report
        except Exception as exc:  # noqa: BLE001
            report.status = "failed"
            report.evidence = "FAILED"
            report.error = f"Postgres verify failed: {exc}"
            return report
    else:
        report.notes.append("LOCAL/DEMO PROVEN — demo destination mirror only")

    _ = dest_side  # reserved
    return report


def check_only() -> dict[str, Any]:
    expected = load_expected()
    ok, reason, cfg = postgres_env_ready()
    return {
        "classification": "LOCAL_ONLY",
        "fixture_dir": str(FIXTURE_DIR),
        "pipeline": str(PIPELINE_PATH),
        "expected": expected,
        "postgres_ready": ok,
        "postgres_reason": reason,
        "postgres_config_keys": sorted(k for k in cfg if k != "password"),
        "honesty": "This check never contacts SFTP/S3/Snowflake/Databricks.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Customer001 LOCAL wedge harness")
    parser.add_argument(
        "--mode",
        choices=("demo", "postgres", "auto"),
        default="auto",
        help="demo=SQLite/CSV mirror; postgres=real local PG; auto=postgres if ready else demo",
    )
    parser.add_argument("--check", action="store_true", help="Readiness only (no pipeline run)")
    parser.add_argument("--prepare", action="store_true", help="Ensure drop file exists and exit")
    parser.add_argument(
        "--no-prepare",
        action="store_true",
        help="Do not refresh/encrypt drop (use existing file — for fail injects)",
    )
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write JSON report path (default data/out/customer001/wedge_report.json)",
    )
    args = parser.parse_args(argv)

    if args.check:
        print(json.dumps(check_only(), indent=2))
        return 0

    if args.prepare:
        path = prepare_fixtures(args.work_dir or ROOT)
        print(json.dumps({"prepared": str(path), "bytes": path.stat().st_size}))
        return 0

    mode = args.mode
    if mode == "auto":
        ok, _, _ = postgres_env_ready()
        mode = "postgres" if ok and os.environ.get("FORMULAETL_DEMO") == "0" else "demo"
        # If user explicitly wants postgres when available without DEMO=0 force:
        if args.mode == "auto" and ok and os.environ.get("CUSTOMER001_FORCE_POSTGRES") == "1":
            mode = "postgres"

    report = run_wedge(
        mode=mode,
        work_dir=args.work_dir,
        prepare=not args.no_prepare,
    )
    out = args.out or (ROOT / "data" / "out" / "customer001" / "wedge_report.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report.to_dict(), indent=2))

    if report.status == "skipped":
        return 0
    return 0 if report.status == "success" and report.reconcile_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
