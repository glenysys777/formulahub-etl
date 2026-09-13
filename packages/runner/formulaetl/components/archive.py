"""Archive Files — move/copy processed files to an archive path."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.registry import register


@register
class ArchiveFiles(BaseComponent):
    component_type = "archive_files"
    display_name = "Archive Files"
    category = "utility"
    config_schema = {
        "type": "object",
        "required": ["destination"],
        "properties": {
            "source": {
                "type": "string",
                "description": "File to archive; defaults to upstream path artifact",
            },
            "destination": {"type": "string", "description": "Archive directory or file path"},
            "mode": {"type": "string", "enum": ["move", "copy"], "default": "move"},
        },
    }
    parameters = [
        {"key": "destination", "label": "Destination", "type": "string", "required": True, "help": "Archive directory or file path"},
        {"key": "source", "label": "Source", "type": "string", "required": False, "help": "File to archive; defaults to upstream path"},
        {"key": "mode", "label": "Mode", "type": "select", "required": False, "default": "move", "options": ["move", "copy"], "help": "Move or copy the file"},
    ]

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            source = (
                self.config.get("source")
                or ctx.variables.get("original_source_path")
                or ctx.variables.get("upstream_path")
            )
            if not source:
                raise ValueError("ArchiveFiles: no source path (config.source or upstream)")

            src = Path(source) if Path(source).is_absolute() else ctx.resolve(source)
            if not src.exists():
                raise FileNotFoundError(f"ArchiveFiles: source not found: {src}")

            dest_cfg = self.config["destination"]
            dest = ctx.resolve(dest_cfg)
            if dest.suffix == "" or dest.exists() and dest.is_dir() or str(dest_cfg).endswith("/"):
                dest.mkdir(parents=True, exist_ok=True)
                dest_file = dest / src.name
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest_file = dest

            mode = self.config.get("mode", "move")
            if mode == "copy":
                shutil.copy2(src, dest_file)
                ctx.emit(f"ArchiveFiles: copied {src} → {dest_file}")
            else:
                shutil.move(str(src), str(dest_file))
                ctx.emit(f"ArchiveFiles: moved {src} → {dest_file}")

            metrics.rows_in = 1
            metrics.rows_out = 1

        return ComponentResult(
            rows=rows or [],
            metrics=metrics,
            side_effects={"mode": mode, "archived_from": str(src), "archived_to": str(dest_file)},
            artifacts={"path": str(dest_file)},
        )
