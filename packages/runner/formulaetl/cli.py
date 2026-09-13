"""CLI entrypoint for FormulaETL runner."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from formulaetl.engine.runner import PipelineRunner
from formulaetl.models.pipeline import PipelineDefinition


def load_pipeline(path: Path) -> PipelineDefinition:
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    return PipelineDefinition.model_validate(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="formulaetl", description="FormulaETL pipeline runner")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="Run a pipeline JSON/YAML file")
    run_p.add_argument("pipeline", type=Path)
    run_p.add_argument("--work-dir", type=Path, default=None)
    run_p.add_argument("--demo", action="store_true", default=True)
    run_p.add_argument("--no-demo", action="store_true")

    sub.add_parser("components", help="List registered components")

    args = parser.parse_args(argv)

    if args.cmd == "components":
        from formulaetl.sdk.registry import list_components

        for c in list_components():
            print(f"{c['type']:28} {c['category']:12} {c['display_name']}")
        return 0

    if args.cmd == "run":
        demo = not args.no_demo
        work = args.work_dir or Path.cwd()
        pipeline = load_pipeline(args.pipeline)
        runner = PipelineRunner(work_dir=work, demo_mode=demo)
        result = runner.run(pipeline)
        print(json.dumps({
            "run_id": result.run_id,
            "status": result.status,
            "metrics": result.metrics,
            "error": result.error,
            "duration_ms": result.duration_ms,
        }, indent=2))
        for line in result.logs:
            print(line, file=sys.stderr)
        return 0 if result.status == "success" else 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
