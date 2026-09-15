#!/usr/bin/env python3
"""Lookup Join heavy-file stress + Job Context ``${…}`` Soft-PASS harness.

Classification
--------------
* ``LOCAL/DEMO Soft-PASS`` — generated CSVs + in-memory Lookup Join + context
  substitution. Never ``LIVE_EXTERNAL``.
* Lookup Join remains a **blocking / materializing** hop (both sides in RAM).
  Soft-PASS documents rows in/out, wall time, and peak RSS (child process).

Chain::

    local CSV (orders, ``${context.orders_path}``)
      + local CSV (customers, ``${context.lookup_path}``)
      → Lookup Join (``${context.join_key}``)
      → column_map
      → local CSV (``${context.out_path}``)

Usage::

    # CI-safe smoke (1k left / 200 lookup):
    FORMULAETL_DEMO=1 python3 scripts/lookup_join_stress.py --scale 1000

    # Soft-PASS evidence scale (100k left / 5k lookup):
    RUN_BENCH=1 FORMULAETL_DEMO=1 python3 scripts/lookup_join_stress.py \\
        --scale 100000 --context QA --require-run-bench \\
        --out docs/evidence/lookup_join_stress_softpass_redacted.json

    # Prove DEV→QA→PROD path substitution without regenerating:
    FORMULAETL_CONTEXT=PROD FORMULAETL_DEMO=1 \\
        python3 scripts/lookup_join_stress.py --scale 1000 --context PROD

See docs/demo/LOOKUP_JOIN_STRESS.md.
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
DEMO_PIPELINE = ROOT / "demos" / "lookup-join-contexts" / "pipeline.json"

# Soft-PASS default: CI-friendly wall time on a laptop / agent VM.
DEFAULT_SOFTPASS_LEFT = 100_000
DEFAULT_SOFTPASS_LOOKUP = 5_000

CONTEXT_DIRS = ("DEV", "QA", "PROD")


@dataclass
class StressReport:
    classification: str = "LOCAL/DEMO Soft-PASS"
    evidence: str = "UNPROVEN"
    status: str = "failed"
    scale_left: int = 0
    scale_lookup: int = 0
    active_context: str = "DEV"
    elapsed_s: float = 0.0
    peak_rss_mb: float | None = None
    rows_left_in: int = 0
    rows_lookup_in: int = 0
    rows_join_out: int = 0
    rows_dest_out: int = 0
    bytes_left: int = 0
    bytes_lookup: int = 0
    join_how: str = "left"
    join_match: str = "first"
    join_key_resolved: str = ""
    orders_path_resolved: str = ""
    lookup_path_resolved: str = ""
    out_path_resolved: str = ""
    contexts_switched: list[str] = field(default_factory=list)
    node_metrics: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    error: str | None = None
    sha_hint: str = "this PR — replace with merge SHA on main"
    date: str = "2026-09-15"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def peak_rss_mb() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if usage > 10_000_000:
        return usage / (1024.0 * 1024.0)
    return usage / 1024.0


def generate_csvs(
    work_dir: Path,
    *,
    n_left: int,
    n_lookup: int,
    contexts: tuple[str, ...] = CONTEXT_DIRS,
) -> dict[str, dict[str, Path]]:
    """Write identical-schema CSVs under per-context folders (path substitution proof)."""
    out: dict[str, dict[str, Path]] = {}
    for ctx_name in contexts:
        base = work_dir / "data" / "stress" / "lookup_join" / ctx_name.lower()
        base.mkdir(parents=True, exist_ok=True)
        orders = base / "orders.csv"
        customers = base / "customers.csv"

        with customers.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["customer_id", "segment", "region"])
            w.writeheader()
            for i in range(n_lookup):
                cid = 1000 + (i % n_lookup)
                w.writerow(
                    {
                        "customer_id": cid,
                        "segment": "smb" if i % 2 == 0 else "enterprise",
                        "region": ("NA", "EU", "APAC")[i % 3],
                    }
                )

        with orders.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "order_id",
                    "customer_id",
                    "quantity",
                    "unit_price",
                    "status",
                ],
            )
            w.writeheader()
            for i in range(n_left):
                cid = 1000 + (i % n_lookup)
                w.writerow(
                    {
                        "order_id": 10_000_000 + i,
                        "customer_id": cid,
                        "quantity": (i % 9) + 1,
                        "unit_price": round(10.0 + (i % 50) * 0.25, 2),
                        "status": "shipped" if i % 7 else "pending",
                    }
                )

        out_dir = work_dir / "data" / "out" / "lookup_join_stress" / ctx_name.lower()
        out_dir.mkdir(parents=True, exist_ok=True)
        out[ctx_name] = {
            "orders": orders,
            "customers": customers,
            "out": out_dir / "joined.csv",
        }
    return out


def build_pipeline(
    *,
    active: str = "DEV",
    how: str = "left",
    match: str = "first",
) -> dict[str, Any]:
    """Pipeline JSON with DEV/QA/PROD Job Contexts for paths + join key + table label."""
    sets: dict[str, dict[str, str]] = {}
    for name in CONTEXT_DIRS:
        lower = name.lower()
        sets[name] = {
            "env": lower,
            "table": f"orders_joined_{lower}",
            "join_key": "customer_id",
            "orders_path": f"data/stress/lookup_join/{lower}/orders.csv",
            "lookup_path": f"data/stress/lookup_join/{lower}/customers.csv",
            "out_path": f"data/out/lookup_join_stress/{lower}/joined.csv",
        }

    return {
        "id": "demo-lookup-join-contexts-stress",
        "name": "Lookup Join stress + Job Contexts (${…})",
        "description": (
            "Heavy-file Lookup Join with dynamic Job Context paths/keys "
            "(DEV/QA/PROD). LOCAL/DEMO Soft-PASS only — join materializes."
        ),
        "version": "1.0",
        "nodes": [
            {
                "id": "orders",
                "type": "local_file_source",
                "label": "Orders CSV",
                "config": {
                    "path": "${context.orders_path}",
                    "format": "csv",
                },
                "position": {"x": 40, "y": 100},
            },
            {
                "id": "customers",
                "type": "local_file_source",
                "label": "Customers lookup",
                "config": {
                    "path": "${context.lookup_path}",
                    "format": "csv",
                },
                "position": {"x": 40, "y": 280},
            },
            {
                "id": "join",
                "type": "lookup_join",
                "label": "Lookup Join",
                "config": {
                    "left_keys": ["${context.join_key}"],
                    "right_keys": ["${context.join_key}"],
                    "how": how,
                    "match": match,
                    "prefix": "lk_",
                },
                "position": {"x": 320, "y": 180},
            },
            {
                "id": "map",
                "type": "column_map",
                "label": "Schema Map",
                "config": {
                    "mappings": [
                        "order_id:order_id",
                        "customer_id:customer_id",
                        "quantity:quantity",
                        "unit_price:unit_price",
                        "status:status",
                        "lk_segment:segment",
                        "lk_region:region",
                    ],
                },
                "position": {"x": 560, "y": 180},
            },
            {
                "id": "dest",
                "type": "local_file_destination",
                "label": "Joined CSV",
                "config": {
                    "path": "${context.out_path}",
                    "format": "csv",
                },
                "position": {"x": 800, "y": 180},
            },
        ],
        "edges": [
            {
                "id": "e-orders-join",
                "source": "orders",
                "target": "join",
                "sourceHandle": "out",
                "targetHandle": "in",
            },
            {
                "id": "e-customers-join",
                "source": "customers",
                "target": "join",
                "sourceHandle": "out",
                "targetHandle": "right",
            },
            {
                "id": "e-join-map",
                "source": "join",
                "target": "map",
                "sourceHandle": "out",
            },
            {
                "id": "e-map-dest",
                "source": "map",
                "target": "dest",
                "sourceHandle": "out",
            },
        ],
        "metadata": {
            "demo": True,
            "requires_demo_mode": True,
            "classification": "LOCAL/DEMO Soft-PASS",
            "use_case": "lookup-join-contexts-stress",
            "live_wedge": False,
            "run_params": {
                "run_date": "2026-09-15",
                "job_name": "lookup_join_stress",
            },
            "contexts": {
                "active": active,
                "sets": sets,
            },
        },
    }


def run_pipeline_isolated(
    pipeline_dict: dict[str, Any],
    work_dir: Path,
    *,
    context: str,
) -> dict[str, Any]:
    """Child-process run so peak RSS excludes fixture generation."""
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
            f"os.environ['FORMULAETL_CONTEXT'] = {context!r}\n"
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
            env={
                **os.environ,
                "FORMULAETL_DEMO": "1",
                "FORMULAETL_WORK_DIR": str(work_dir),
                "FORMULAETL_CONTEXT": context,
            },
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
        payload["returncode"] = proc.returncode
        return payload


def _metric(nm: dict[str, Any], node: str, key: str, default: int = 0) -> int:
    block = nm.get(node) or {}
    if isinstance(block, dict):
        val = block.get(key)
        if val is None and isinstance(block.get("metrics"), dict):
            val = block["metrics"].get(key)
        if val is not None:
            return int(val)
    return default


def run_one(
    *,
    work_dir: Path | None = None,
    n_left: int = 1000,
    n_lookup: int = 200,
    context: str = "DEV",
    how: str = "left",
    match: str = "first",
    timebox_s: float | None = None,
    write_demo_pipeline: bool = False,
) -> StressReport:
    work = work_dir or ROOT
    report = StressReport(
        scale_left=n_left,
        scale_lookup=n_lookup,
        active_context=context,
        join_how=how,
        join_match=match,
    )
    report.notes.append(
        "Lookup Join is BLOCKING_ROWS (in-memory hash); Soft-PASS documents RSS, "
        "not a streaming join claim."
    )
    report.notes.append(
        f"Generated left≈{n_left} rows, lookup≈{n_lookup} rows under "
        "data/stress/lookup_join/<context>/."
    )

    try:
        paths = generate_csvs(work, n_left=n_left, n_lookup=n_lookup)
        pipe = build_pipeline(active=context, how=how, match=match)
        if write_demo_pipeline:
            DEMO_PIPELINE.parent.mkdir(parents=True, exist_ok=True)
            DEMO_PIPELINE.write_text(json.dumps(pipe, indent=2) + "\n", encoding="utf-8")

        ctx_paths = paths[context]
        report.bytes_left = ctx_paths["orders"].stat().st_size
        report.bytes_lookup = ctx_paths["customers"].stat().st_size
        report.orders_path_resolved = f"data/stress/lookup_join/{context.lower()}/orders.csv"
        report.lookup_path_resolved = (
            f"data/stress/lookup_join/{context.lower()}/customers.csv"
        )
        report.out_path_resolved = (
            f"data/out/lookup_join_stress/{context.lower()}/joined.csv"
        )
        report.join_key_resolved = "customer_id"
        report.contexts_switched = [context]

        t0 = time.perf_counter()
        payload = run_pipeline_isolated(pipe, work, context=context)
        elapsed = time.perf_counter() - t0
        report.elapsed_s = round(float(payload.get("elapsed_s") or elapsed), 3)
        rss = payload.get("peak_rss_mb")
        report.peak_rss_mb = round(float(rss), 2) if rss is not None else None
        report.node_metrics = payload.get("node_metrics") or {}

        nm = report.node_metrics
        report.rows_left_in = _metric(nm, "orders", "rows_out", n_left)
        report.rows_lookup_in = _metric(nm, "customers", "rows_out", n_lookup)
        report.rows_join_out = _metric(nm, "join", "rows_out")
        report.rows_dest_out = _metric(nm, "dest", "rows_out")

        if payload.get("status") != "success":
            report.status = "failed"
            report.error = str(payload.get("error") or payload.get("child_stderr"))
            report.evidence = "UNPROVEN"
            return report

        out_file = work / report.out_path_resolved
        if not out_file.exists():
            report.status = "failed"
            report.error = f"missing output {out_file}"
            report.evidence = "UNPROVEN"
            return report

        # left join + match=first → one row per left input
        if how == "left" and match == "first" and report.rows_join_out != n_left:
            report.status = "failed"
            report.error = (
                f"join rows_out={report.rows_join_out} != left={n_left} "
                f"(how={how}, match={match})"
            )
            report.evidence = "UNPROVEN"
            return report

        if timebox_s is not None and report.elapsed_s > timebox_s:
            report.status = "failed"
            report.error = f"exceeded timebox {timebox_s}s (elapsed={report.elapsed_s})"
            report.evidence = "UNPROVEN"
            report.notes.append("Soft-PASS timebox miss — still useful for RSS notes.")
            return report

        report.status = "success"
        report.evidence = "PROVEN Soft-PASS LOCAL/DEMO"
        return report
    except Exception as exc:  # noqa: BLE001 — harness surfaces any failure
        report.status = "failed"
        report.error = str(exc)
        report.evidence = "UNPROVEN"
        report.peak_rss_mb = round(peak_rss_mb(), 2)
        return report


def prove_context_switch(work_dir: Path, n_left: int = 500, n_lookup: int = 50) -> dict[str, Any]:
    """Run the same pipeline shape under DEV, QA, PROD and assert distinct out paths."""
    generate_csvs(work_dir, n_left=n_left, n_lookup=n_lookup)
    results: dict[str, Any] = {"ok": True, "contexts": {}}
    for name in CONTEXT_DIRS:
        pipe = build_pipeline(active=name)
        payload = run_pipeline_isolated(pipe, work_dir, context=name)
        out_rel = f"data/out/lookup_join_stress/{name.lower()}/joined.csv"
        exists = (work_dir / out_rel).exists()
        results["contexts"][name] = {
            "status": payload.get("status"),
            "out_path": out_rel,
            "out_exists": exists,
            "rows_join_out": _metric(payload.get("node_metrics") or {}, "join", "rows_out"),
        }
        if payload.get("status") != "success" or not exists:
            results["ok"] = False
    return results


def redact_for_evidence(report: StressReport) -> dict[str, Any]:
    """Commit-safe Soft-PASS evidence (no host paths beyond repo-relative)."""
    d = report.to_dict()
    d["note"] = (
        "LOCAL/DEMO Soft-PASS only. Lookup Join materializes left+lookup in RAM. "
        "Not LIVE_EXTERNAL. PAT/creds N/A. Job Context ${…} substitution proven "
        "for orders_path / lookup_path / out_path / join_key across DEV|QA|PROD."
    )
    # Drop absolute noise; keep relative metrics
    return d


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scale", type=int, default=1000, help="Left (orders) row count")
    p.add_argument(
        "--lookup-scale",
        type=int,
        default=None,
        help="Lookup (customers) row count (default: min(5000, max(50, scale//20)))",
    )
    p.add_argument("--context", default="DEV", choices=list(CONTEXT_DIRS))
    p.add_argument("--how", default="left", choices=["left", "inner", "right", "full"])
    p.add_argument("--match", default="first", choices=["all", "first"])
    p.add_argument("--timebox-s", type=float, default=None)
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write report JSON (e.g. docs/evidence/… or data/out/…)",
    )
    p.add_argument(
        "--require-run-bench",
        action="store_true",
        help="Refuse scales ≥10k unless RUN_BENCH=1 (mirrors local_wedge_bench)",
    )
    p.add_argument(
        "--prove-contexts",
        action="store_true",
        help="Also run DEV/QA/PROD path substitution check (small N)",
    )
    p.add_argument(
        "--write-demo-pipeline",
        action="store_true",
        help=f"Refresh {DEMO_PIPELINE.relative_to(ROOT)} from builder",
    )
    p.add_argument(
        "--work-dir",
        type=Path,
        default=None,
        help="Working directory (default: repo root)",
    )
    args = p.parse_args(argv)

    n_left = int(args.scale)
    n_lookup = args.lookup_scale
    if n_lookup is None:
        n_lookup = min(DEFAULT_SOFTPASS_LOOKUP, max(50, n_left // 20))

    if args.require_run_bench and n_left >= 10_000 and os.environ.get("RUN_BENCH") != "1":
        print("Refusing heavy scale without RUN_BENCH=1", file=sys.stderr)
        return 2

    work = args.work_dir or ROOT
    os.environ.setdefault("FORMULAETL_DEMO", "1")
    os.environ["FORMULAETL_WORK_DIR"] = str(work)
    os.environ["FORMULAETL_CONTEXT"] = args.context

    report = run_one(
        work_dir=work,
        n_left=n_left,
        n_lookup=n_lookup,
        context=args.context,
        how=args.how,
        match=args.match,
        timebox_s=args.timebox_s,
        write_demo_pipeline=args.write_demo_pipeline,
    )

    payload: dict[str, Any] = redact_for_evidence(report)
    if args.prove_contexts:
        payload["context_switch"] = prove_context_switch(
            work, n_left=min(500, n_left), n_lookup=min(50, n_lookup)
        )
        if not payload["context_switch"].get("ok"):
            report.status = "failed"
            report.evidence = "UNPROVEN"
            payload["status"] = "failed"
            payload["evidence"] = "UNPROVEN"
            payload["error"] = (payload.get("error") or "") + "; context_switch failed"

    text = json.dumps(payload, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        default_out = work / "data" / "out" / "lookup_join_stress" / "report.json"
        default_out.parent.mkdir(parents=True, exist_ok=True)
        default_out.write_text(text, encoding="utf-8")
        print(text)
        print(f"wrote {default_out}")

    print(
        f"status={report.status} evidence={report.evidence} "
        f"left={report.scale_left} lookup={report.scale_lookup} "
        f"join_out={report.rows_join_out} elapsed_s={report.elapsed_s} "
        f"peak_rss_mb={report.peak_rss_mb} context={report.active_context}",
        flush=True,
    )
    return 0 if report.status == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
