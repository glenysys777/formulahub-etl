#!/usr/bin/env python3
"""LOCAL/DEMO wedge performance + correctness benchmark harness.

Chain (demo only — never LIVE_CLOUD)::

    file | S3-demo → PGP decrypt → CSV parse → schema_validate
         → column_map → dedupe → file | snowflake-demo → archive

Also writes rejects from validate to a local file.

Records runtime, peak RSS (when available), rows/sec, and reconciles::

    N (parsed) = R (validate rejects) + D (dedupe drops) + L (loaded)

Usage::

    # Fast smoke (default 1k) — always LOCAL/DEMO:
    FORMULAETL_DEMO=1 python3 scripts/local_wedge_bench.py --scales 1000

    # Scale evidence (opt-in; heavy):
    RUN_BENCH=1 FORMULAETL_DEMO=1 python3 scripts/local_wedge_bench.py \\
        --scales 10000,100000,1000000

    # Optional 10M when env allows (timeboxed):
    RUN_BENCH=1 BENCH_INCLUDE_10M=1 python3 scripts/local_wedge_bench.py \\
        --scales 10000000 --timebox-s 1800

See docs/PRODUCTION_EVIDENCE.md section J. Classification: LOCAL/DEMO only.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import resource
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

COLUMNS = [
    "order_id",
    "customer_id",
    "email",
    "quantity",
    "unit_price",
    "order_date",
    "status",
]

VALIDATE_COLUMNS = {
    "order_id": "int",
    "customer_id": "int",
    "email": "email",
    "quantity": "int",
    "unit_price": "float",
    "order_date": "date",
    "status": "string",
}

COLUMN_MAPPINGS = [
    "order_id:order_id",
    "customer_id:customer_id",
    "email:email",
    "quantity:quantity",
    "unit_price:unit_price",
    "order_date:order_date",
    "status:status",
]


@dataclass
class CountPlan:
    """Deterministic N/R/D/L plan so reconciliation is exact."""

    n: int
    rejects: int
    dups: int
    loaded: int

    def validate(self) -> None:
        if self.n != self.rejects + self.dups + self.loaded:
            raise AssertionError(
                f"plan broken: N={self.n} != R={self.rejects}+D={self.dups}+L={self.loaded}"
            )


@dataclass
class BenchResult:
    classification: str = "LOCAL/DEMO"
    scale: int = 0
    source: str = "s3"
    dest: str = "snowflake"
    status: str = "failed"
    elapsed_s: float = 0.0
    peak_rss_mb: float | None = None
    rows_per_sec: float = 0.0
    input_n: int = 0
    rejected_r: int = 0
    deduped_d: int = 0
    loaded_l: int = 0
    expected_r: int = 0
    expected_d: int = 0
    expected_l: int = 0
    reconcile_ok: bool = False
    reconcile_equation: str = "N = R + D + L"
    error: str | None = None
    node_metrics: dict[str, Any] = field(default_factory=dict)
    evidence: str = "UNPROVEN"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def plan_counts(n: int) -> CountPlan:
    """~1% rejects, ~2% dups of remaining good rows; exact N=R+D+L."""
    if n < 1:
        raise ValueError("n must be >= 1")
    if n < 10:
        # Tiny smoke: 1 reject, 1 dup when possible
        rejects = 1 if n >= 3 else 0
        remaining = n - rejects
        dups = 1 if remaining >= 2 else 0
        loaded = remaining - dups
        plan = CountPlan(n=n, rejects=rejects, dups=dups, loaded=loaded)
        plan.validate()
        return plan

    rejects = max(1, n // 100)
    remaining = n - rejects
    dups = max(1, remaining // 50)
    if dups >= remaining:
        dups = max(0, remaining - 1)
    loaded = remaining - dups
    plan = CountPlan(n=n, rejects=rejects, dups=dups, loaded=loaded)
    plan.validate()
    return plan


def generate_rows(plan: CountPlan) -> list[dict[str, str]]:
    """Build deterministic CSV rows matching the count plan."""
    rows: list[dict[str, str]] = []
    # Unique good rows first (loaded set)
    for i in range(1, plan.loaded + 1):
        rows.append(
            {
                "order_id": str(i),
                "customer_id": str(1000 + (i % 5000)),
                "email": f"user{i}@example.com",
                "quantity": str(1 + (i % 9)),
                "unit_price": f"{(9.99 + (i % 50)):.2f}",
                "order_date": f"2024-{(1 + (i % 12)):02d}-{(1 + (i % 28)):02d}",
                "status": "shipped" if i % 3 else "pending",
            }
        )
    # Duplicate copies of the first `dups` unique keys (dedupe keep=first)
    for i in range(1, plan.dups + 1):
        src = rows[i - 1]
        rows.append(dict(src))
    # Rejects: invalid email (schema_validate email checker)
    for i in range(plan.rejects):
        rid = 90_000_000 + i
        rows.append(
            {
                "order_id": str(rid),
                "customer_id": str(2000 + i),
                "email": "not-an-email",
                "quantity": str(1),
                "unit_price": "1.00",
                "order_date": "2024-06-15",
                "status": "pending",
            }
        )
    if len(rows) != plan.n:
        raise AssertionError(f"generated {len(rows)} rows, expected {plan.n}")
    return rows


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def write_csv_streaming(path: Path, plan: CountPlan) -> None:
    """Generate the deterministic bench CSV without holding N row dicts in RAM."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        # Unique loaded rows
        for i in range(1, plan.loaded + 1):
            writer.writerow(
                {
                    "order_id": str(i),
                    "customer_id": str(1000 + (i % 5000)),
                    "email": f"user{i}@example.com",
                    "quantity": str(1 + (i % 9)),
                    "unit_price": f"{(9.99 + (i % 50)):.2f}",
                    "order_date": f"2024-{(1 + (i % 12)):02d}-{(1 + (i % 28)):02d}",
                    "status": "shipped" if i % 3 else "pending",
                }
            )
        # Duplicate copies of the first `dups` unique keys
        for i in range(1, plan.dups + 1):
            writer.writerow(
                {
                    "order_id": str(i),
                    "customer_id": str(1000 + (i % 5000)),
                    "email": f"user{i}@example.com",
                    "quantity": str(1 + (i % 9)),
                    "unit_price": f"{(9.99 + (i % 50)):.2f}",
                    "order_date": f"2024-{(1 + (i % 12)):02d}-{(1 + (i % 28)):02d}",
                    "status": "shipped" if i % 3 else "pending",
                }
            )
        for i in range(plan.rejects):
            rid = 90_000_000 + i
            writer.writerow(
                {
                    "order_id": str(rid),
                    "customer_id": str(2000 + i),
                    "email": "not-an-email",
                    "quantity": str(1),
                    "unit_price": "1.00",
                    "order_date": "2024-06-15",
                    "status": "pending",
                }
            )


def encrypt_csv(plaintext: Path, ciphertext: Path, public_key_path: Path) -> None:
    """Encrypt CSV with demo public key (pgpy). Path-only output for large files."""
    import pgpy

    key, _ = pgpy.PGPKey.from_blob(public_key_path.read_text(encoding="utf-8"))
    raw = plaintext.read_bytes()
    msg = pgpy.PGPMessage.new(raw, file=True)
    cipher = key.encrypt(msg)
    ciphertext.parent.mkdir(parents=True, exist_ok=True)
    ciphertext.write_bytes(str(cipher).encode("utf-8"))


def peak_rss_mb() -> float:
    """Linux ru_maxrss is KB; macOS is bytes — detect roughly."""
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Heuristic: values > 10_000_000 are almost certainly bytes (macOS)
    if usage > 10_000_000:
        return usage / (1024.0 * 1024.0)
    return usage / 1024.0


def run_pipeline_isolated(
    pipeline_dict: dict[str, Any],
    work_dir: Path,
) -> dict[str, Any]:
    """Execute the wedge in a child process so ru_maxrss is the pipeline only.

    Fixture encrypt / prior scales in the parent must not pollute peak RSS.
    """
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        pipe_path = Path(td) / "pipeline.json"
        out_path = Path(td) / "run.json"
        pipe_path.write_text(json.dumps(pipeline_dict), encoding="utf-8")
        child = (
            "import json, os, time, resource, sys\n"
            "from pathlib import Path\n"
            "os.environ['FORMULAETL_DEMO'] = '1'\n"
            "from formulaetl.engine.runner import PipelineRunner\n"
            "from formulaetl.models.pipeline import PipelineDefinition\n"
            "\n"
            "def peak():\n"
            "    u = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss\n"
            "    return u / (1024.0 * 1024.0) if u > 10_000_000 else u / 1024.0\n"
            "\n"
            f"work = Path({str(work_dir)!r})\n"
            f"pipe = json.loads(Path({str(pipe_path)!r}).read_text())\n"
            "pipeline = PipelineDefinition.model_validate(pipe)\n"
            "runner = PipelineRunner(work_dir=work, demo_mode=True)\n"
            "t0 = time.perf_counter()\n"
            "run = runner.run(pipeline)\n"
            "elapsed = time.perf_counter() - t0\n"
            "payload = {\n"
            "    'status': run.status,\n"
            "    'error': run.error,\n"
            "    'duration_ms': run.duration_ms,\n"
            "    'elapsed_s': elapsed,\n"
            "    'peak_rss_mb': peak(),\n"
            "    'node_metrics': run.node_metrics,\n"
            "}\n"
            f"Path({str(out_path)!r}).write_text(json.dumps(payload))\n"
            "sys.exit(0 if run.status == 'success' else 1)\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", child],
            cwd=str(work_dir),
            env={**os.environ, "FORMULAETL_DEMO": "1", "FORMULAETL_WORK_DIR": str(work_dir)},
            capture_output=True,
            text=True,
        )
        if not out_path.exists():
            raise RuntimeError(
                f"isolated pipeline child failed (code={proc.returncode}): "
                f"{(proc.stderr or proc.stdout)[-2000:]}"
            )
        payload = json.loads(out_path.read_text(encoding="utf-8"))
        payload["child_stderr"] = (proc.stderr or "")[-500:]
        return payload


def build_pipeline(
    *,
    source: str,
    dest: str,
    encrypted_rel: str,
    reject_rel: str,
    load_rel: str,
    archive_rel: str,
    private_key_rel: str = "fixtures/keys/demo_private.asc",
) -> dict[str, Any]:
    """Build LOCAL/DEMO wedge DAG including dedupe."""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    if source == "s3":
        # key is relative to data/s3/<bucket>/
        key = encrypted_rel
        if key.startswith("data/s3/"):
            # data/s3/demo/bench.pgp → bucket=demo, key=demo/bench.pgp? 
            # S3 demo layout: data/s3/<bucket>/<key>
            parts = Path(key).parts  # data, s3, bucket, ...
            bucket = parts[2]
            key_path = "/".join(parts[3:])
        else:
            bucket = "demo"
            key_path = key
        nodes.append(
            {
                "id": "src",
                "type": "s3_source",
                "label": "S3 Source (demo)",
                "config": {"bucket": bucket, "key": key_path},
            }
        )
    else:
        nodes.append(
            {
                "id": "src",
                "type": "local_file_source",
                "label": "File Source (demo)",
                "config": {"path": encrypted_rel, "format": "bytes"},
            }
        )

    nodes.extend(
        [
            {
                "id": "pgp",
                "type": "pgp_decrypt",
                "label": "PGP Decrypt",
                "config": {
                    "private_key_path": private_key_rel,
                    "passphrase": "",
                },
            },
            {
                "id": "parse",
                "type": "csv_parser",
                "label": "CSV Parse",
                "config": {"delimiter": ","},
            },
            {
                "id": "validate",
                "type": "schema_validate",
                "label": "Schema Validate",
                "config": {
                    "columns": VALIDATE_COLUMNS,
                    "required_columns": list(VALIDATE_COLUMNS.keys()),
                    "strict": False,
                },
            },
            {
                "id": "map",
                "type": "column_map",
                "label": "Column Map",
                "config": {"mappings": COLUMN_MAPPINGS, "drop_unmapped": False},
            },
            {
                "id": "dedupe",
                "type": "dedupe",
                "label": "Dedupe",
                "config": {"keys": ["order_id"], "keep": "first"},
            },
        ]
    )

    if dest == "snowflake":
        nodes.append(
            {
                "id": "dest",
                "type": "snowflake_destination",
                "label": "Snowflake (demo)",
                "config": {
                    "database": "BENCH_DB",
                    "schema": "PUBLIC",
                    "table": "WEDGE_BENCH",
                    "demo_output_dir": load_rel,
                },
            }
        )
    else:
        nodes.append(
            {
                "id": "dest",
                "type": "local_file_destination",
                "label": "File Dest (demo)",
                "config": {"path": f"{load_rel.rstrip('/')}/loaded.csv", "format": "csv"},
            }
        )

    nodes.append(
        {
            "id": "rejects",
            "type": "local_file_destination",
            "label": "Rejects File",
            "config": {"path": reject_rel, "format": "csv"},
        }
    )
    nodes.append(
        {
            "id": "archive",
            "type": "archive_files",
            "label": "Archive Source",
            "config": {"destination": archive_rel, "mode": "copy"},
        }
    )

    # Main spine
    spine = ["src", "pgp", "parse", "validate", "map", "dedupe", "dest", "archive"]
    for i in range(len(spine) - 1):
        edges.append({"id": f"e{i + 1}", "source": spine[i], "target": spine[i + 1]})
    # Rejects branch
    edges.append(
        {
            "id": "e_rej",
            "source": "validate",
            "target": "rejects",
            "sourceHandle": "rejects",
        }
    )

    return {
        "id": "local-wedge-bench",
        "name": f"LOCAL/DEMO wedge bench: {source}→pgp→csv→validate→map→dedupe→{dest}→archive",
        "description": (
            "Local/demo performance + correctness harness. "
            "Never LIVE_CLOUD. See docs/PRODUCTION_EVIDENCE.md §J."
        ),
        "version": "1.0",
        "nodes": nodes,
        "edges": edges,
        "metadata": {
            "demo": True,
            "requires_demo_mode": True,
            "classification": "LOCAL/DEMO",
            "bench": True,
        },
    }


def reconcile(
    *,
    n: int,
    r: int,
    d: int,
    l: int,
) -> tuple[bool, str]:
    ok = n == r + d + l
    eq = f"N={n} R={r} D={d} L={l} → R+D+L={r + d + l}"
    return ok, eq


def prepare_fixture(
    work_dir: Path,
    plan: CountPlan,
    *,
    source: str,
) -> tuple[Path, Path]:
    """Write plaintext CSV + encrypted object under work_dir. Returns (csv, pgp)."""
    pub = work_dir / "fixtures" / "keys" / "demo_public.asc"
    if not pub.exists():
        # Fall back to repo fixtures
        pub = ROOT / "fixtures" / "keys" / "demo_public.asc"
    if not pub.exists():
        raise FileNotFoundError(
            f"demo public key missing at {pub}; run scripts/seed_demo.py first"
        )

    bench_dir = work_dir / "data" / "bench"
    bench_dir.mkdir(parents=True, exist_ok=True)
    csv_path = bench_dir / f"wedge_{plan.n}.csv"
    write_csv_streaming(csv_path, plan)

    if source == "s3":
        pgp_path = work_dir / "data" / "s3" / "demo" / f"wedge_bench_{plan.n}.csv.pgp"
    else:
        pgp_path = bench_dir / f"wedge_{plan.n}.csv.pgp"

    encrypt_csv(csv_path, pgp_path, pub)
    return csv_path, pgp_path


def run_one(
    *,
    work_dir: Path,
    n: int,
    source: str = "s3",
    dest: str = "snowflake",
    timebox_s: float | None = None,
) -> BenchResult:
    """Run one LOCAL/DEMO scale point and return metrics + reconciliation."""
    os.environ["FORMULAETL_DEMO"] = "1"
    plan = plan_counts(n)
    result = BenchResult(
        scale=n,
        source=source,
        dest=dest,
        expected_r=plan.rejects,
        expected_d=plan.dups,
        expected_l=plan.loaded,
        notes=[
            "classification=LOCAL/DEMO — not LIVE_CLOUD",
            f"plan N={plan.n} R={plan.rejects} D={plan.dups} L={plan.loaded}",
        ],
    )

    try:
        # Ensure keys exist in work_dir
        keys_dst = work_dir / "fixtures" / "keys"
        keys_dst.mkdir(parents=True, exist_ok=True)
        for name in ("demo_private.asc", "demo_public.asc"):
            src = ROOT / "fixtures" / "keys" / name
            dst = keys_dst / name
            if src.exists() and not dst.exists():
                dst.write_bytes(src.read_bytes())

        t_prep0 = time.perf_counter()
        _csv_path, pgp_path = prepare_fixture(work_dir, plan, source=source)
        prep_s = time.perf_counter() - t_prep0
        result.notes.append(f"fixture_prep_s={prep_s:.3f}")

        if source == "s3":
            encrypted_rel = str(pgp_path.relative_to(work_dir))
        else:
            encrypted_rel = str(pgp_path.relative_to(work_dir))

        reject_rel = f"data/rejects/bench_{n}_rejects.csv"
        load_rel = f"data/out/bench_{n}_{dest}"
        archive_rel = f"data/archive/bench_{n}/"

        pipeline_dict = build_pipeline(
            source=source,
            dest=dest,
            encrypted_rel=encrypted_rel,
            reject_rel=reject_rel,
            load_rel=load_rel,
            archive_rel=archive_rel,
        )

        payload = run_pipeline_isolated(pipeline_dict, work_dir)

        class _Run:
            status: str
            error: str | None
            duration_ms: float
            node_metrics: dict

        run = _Run()
        run.status = payload["status"]
        run.error = payload.get("error")
        run.duration_ms = payload.get("duration_ms") or 0
        run.node_metrics = payload.get("node_metrics") or {}
        elapsed = float(payload.get("elapsed_s") or 0)
        rss_peak = float(payload.get("peak_rss_mb") or 0)

        if timebox_s is not None and elapsed > timebox_s:
            result.status = "failed"
            result.error = f"exceeded timebox {timebox_s}s (elapsed={elapsed:.1f}s)"
            result.elapsed_s = round(elapsed, 4)
            result.peak_rss_mb = round(rss_peak, 2)
            result.evidence = "FAILED"
            return result

        nm = run.node_metrics or {}
        parse_out = int(nm.get("parse", {}).get("rows_out") or 0)
        validate_rej = int(nm.get("validate", {}).get("rows_rejected") or 0)
        dedupe_rej = int(nm.get("dedupe", {}).get("rows_rejected") or 0)
        dest_out = int(nm.get("dest", {}).get("rows_out") or 0)

        ok, eq = reconcile(n=parse_out, r=validate_rej, d=dedupe_rej, l=dest_out)

        # Also enforce expected plan counts
        counts_match = (
            parse_out == plan.n
            and validate_rej == plan.rejects
            and dedupe_rej == plan.dups
            and dest_out == plan.loaded
        )
        if not counts_match:
            ok = False
            eq += (
                f" | expected N={plan.n} R={plan.rejects} D={plan.dups} L={plan.loaded}"
            )

        result.input_n = parse_out
        result.rejected_r = validate_rej
        result.deduped_d = dedupe_rej
        result.loaded_l = dest_out
        result.reconcile_ok = ok
        result.reconcile_equation = eq
        result.elapsed_s = round(elapsed, 4)
        result.peak_rss_mb = round(rss_peak, 2)
        result.rows_per_sec = round(parse_out / elapsed, 2) if elapsed > 0 else 0.0
        result.node_metrics = nm
        result.status = run.status if ok and run.status == "success" else (
            "failed" if run.status != "success" or not ok else "success"
        )
        if run.status != "success":
            result.error = run.error or payload.get("child_stderr")
            result.evidence = "FAILED"
            result.status = "failed"
        elif not ok:
            result.error = f"reconciliation failed: {eq}"
            result.evidence = "FAILED"
            result.status = "failed"
        else:
            result.evidence = "PROVEN"
            result.status = "success"
            result.notes.append(
                f"duration_ms={run.duration_ms:.1f} peak_rss_mb≈{result.peak_rss_mb} "
                "(child-process RSS; excludes fixture encrypt)"
            )

    except Exception as exc:  # noqa: BLE001 — bench harness surfaces any failure
        result.status = "failed"
        result.error = str(exc)
        result.evidence = "FAILED"
        result.peak_rss_mb = round(peak_rss_mb(), 2)

    return result


def run_scales(
    scales: list[int],
    *,
    work_dir: Path | None = None,
    source: str = "s3",
    dest: str = "snowflake",
    timebox_s: float | None = None,
) -> dict[str, Any]:
    work = Path(work_dir or ROOT)
    results: list[BenchResult] = []
    for n in scales:
        results.append(
            run_one(
                work_dir=work,
                n=n,
                source=source,
                dest=dest,
                timebox_s=timebox_s,
            )
        )
    all_ok = all(r.status == "success" and r.reconcile_ok for r in results)
    return {
        "classification": "LOCAL/DEMO",
        "evidence": "PROVEN" if all_ok else "FAILED",
        "source": source,
        "dest": dest,
        "results": [r.to_dict() for r in results],
    }


def _parse_scales(raw: str) -> list[int]:
    out: list[int] = []
    for part in raw.split(","):
        part = part.strip().lower().replace("_", "")
        if not part:
            continue
        if part.endswith("k"):
            out.append(int(float(part[:-1]) * 1000))
        elif part.endswith("m"):
            out.append(int(float(part[:-1]) * 1_000_000))
        else:
            out.append(int(part))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="LOCAL/DEMO wedge bench (never LIVE_CLOUD)"
    )
    parser.add_argument(
        "--scales",
        default="1000",
        help="Comma-separated row counts (e.g. 10000,100000,1000000)",
    )
    parser.add_argument(
        "--source",
        choices=("s3", "file"),
        default="s3",
        help="Demo source: s3 mock or local file",
    )
    parser.add_argument(
        "--dest",
        choices=("snowflake", "file"),
        default="snowflake",
        help="Demo destination: snowflake CSV or local file",
    )
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument(
        "--timebox-s",
        type=float,
        default=None,
        help="Fail a scale if wall time exceeds this many seconds",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write JSON results to this path",
    )
    parser.add_argument(
        "--require-run-bench",
        action="store_true",
        help="Exit 0 skipped unless RUN_BENCH=1 (for make/pytest gating)",
    )
    args = parser.parse_args(argv)

    if args.require_run_bench and os.environ.get("RUN_BENCH") != "1":
        print(
            json.dumps(
                {
                    "status": "skipped",
                    "classification": "LOCAL/DEMO",
                    "evidence": "UNPROVEN",
                    "reason": "RUN_BENCH is not 1 — heavy bench not attempted",
                },
                indent=2,
            )
        )
        return 0

    scales = _parse_scales(args.scales)
    if any(s >= 10_000_000 for s in scales) and os.environ.get("BENCH_INCLUDE_10M") != "1":
        print(
            json.dumps(
                {
                    "status": "skipped",
                    "classification": "LOCAL/DEMO",
                    "reason": "10M scale requires BENCH_INCLUDE_10M=1",
                    "scales": scales,
                },
                indent=2,
            )
        )
        return 0

    # Force demo — never claim live
    os.environ["FORMULAETL_DEMO"] = "1"

    payload = run_scales(
        scales,
        work_dir=args.work_dir,
        source=args.source,
        dest=args.dest,
        timebox_s=args.timebox_s,
    )
    text = json.dumps(payload, indent=2)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")

    return 0 if payload.get("evidence") == "PROVEN" else 1


if __name__ == "__main__":
    raise SystemExit(main())
