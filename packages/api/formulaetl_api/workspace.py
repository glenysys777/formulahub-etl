"""Studio Workspace folders — durable folder index + pipeline folder assignment.

Persistence:
  - Primary: ``metadata.workspace_folder`` on each pipeline (survives Save / versions)
  - Index: ``{work_dir}/data/workspace.json`` for folder list + quick lookup

UI labels only: Workspace, Pipelines, Masters, Reusable (Child pipelines).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_FOLDERS: list[str] = [
    "Pipelines/Demos",
    "Pipelines/My pipelines",
    "Masters",
    "Reusable",
]

DEFAULT_MY_PIPELINES = "Pipelines/My pipelines"
DEFAULT_DEMOS = "Pipelines/Demos"

# Seed known bundled demos into sensible folders (behavior only — no competitor names).
DEMO_WORKSPACE_FOLDERS: dict[str, str] = {
    "demo-s3-pgp-snowflake": "Pipelines/Demos",
    "demo-api-map-transform": "Pipelines/Demos",
    "demo-excel-to-file": "Pipelines/Demos",
    "demo-sftp-excel-to-file": "Pipelines/Demos",
    "demo-excel-sftp": "Pipelines/Demos",
    "demo-db-to-file": "Pipelines/Demos",
    "demo-core-path": "Pipelines/Demos",
    "demo-python-row-flex": "Pipelines/Demos",
    "demo-api-kafka-databricks": "Pipelines/Demos",
    "demo-s3-databricks": "Pipelines/Demos",
    "demo-api-databricks-sql": "Pipelines/Demos",
    "demo-lookup-join-mapper": "Pipelines/Demos",
    "demo-master-file-to-databricks": "Masters",
    "demo-master-child-ingest": "Reusable",
    "demo-master-child-load": "Reusable",
}


def workspace_path(work_dir: Path) -> Path:
    return Path(work_dir) / "data" / "workspace.json"


def _normalize_folder(folder: str | None) -> str:
    raw = (folder or "").strip().replace("\\", "/")
    while "//" in raw:
        raw = raw.replace("//", "/")
    return raw.strip("/")


def empty_workspace() -> dict[str, Any]:
    return {
        "folders": list(DEFAULT_FOLDERS),
        "pipelineFolders": {},
    }


def load_workspace(work_dir: Path) -> dict[str, Any]:
    path = workspace_path(work_dir)
    if not path.is_file():
        data = empty_workspace()
        save_workspace(work_dir, data)
        return data
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = empty_workspace()
        save_workspace(work_dir, data)
        return data
    folders = raw.get("folders") or []
    if not isinstance(folders, list):
        folders = []
    cleaned: list[str] = []
    seen: set[str] = set()
    for f in folders:
        nf = _normalize_folder(str(f))
        if nf and nf not in seen:
            cleaned.append(nf)
            seen.add(nf)
    for f in DEFAULT_FOLDERS:
        if f not in seen:
            cleaned.append(f)
            seen.add(f)
    pf_raw = raw.get("pipelineFolders") or {}
    if not isinstance(pf_raw, dict):
        pf_raw = {}
    pipeline_folders = {
        str(k): _normalize_folder(str(v))
        for k, v in pf_raw.items()
        if _normalize_folder(str(v))
    }
    return {"folders": cleaned, "pipelineFolders": pipeline_folders}


def save_workspace(work_dir: Path, data: dict[str, Any]) -> dict[str, Any]:
    path = workspace_path(work_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    folders = []
    seen: set[str] = set()
    for f in data.get("folders") or []:
        nf = _normalize_folder(str(f))
        if nf and nf not in seen:
            folders.append(nf)
            seen.add(nf)
    for f in DEFAULT_FOLDERS:
        if f not in seen:
            folders.append(f)
            seen.add(f)
    pf = {}
    for k, v in (data.get("pipelineFolders") or {}).items():
        nf = _normalize_folder(str(v))
        if nf:
            pf[str(k)] = nf
    out = {"folders": folders, "pipelineFolders": pf}
    path.write_text(
        json.dumps(out, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return out


def folder_from_metadata(metadata: dict[str, Any] | None) -> str | None:
    if not metadata:
        return None
    raw = metadata.get("workspace_folder")
    if raw is None:
        return None
    nf = _normalize_folder(str(raw))
    return nf or None


def ensure_folder_in_list(folders: list[str], folder: str) -> list[str]:
    nf = _normalize_folder(folder)
    if not nf:
        return folders
    if nf in folders:
        return folders
    return [*folders, nf]


def resolve_pipeline_folder(
    pipeline_id: str,
    metadata: dict[str, Any] | None,
    workspace: dict[str, Any],
) -> str:
    """Prefer pipeline metadata, then workspace index, then demo seed / My pipelines."""
    meta_folder = folder_from_metadata(metadata)
    if meta_folder:
        return meta_folder
    indexed = (workspace.get("pipelineFolders") or {}).get(pipeline_id)
    if indexed:
        return _normalize_folder(str(indexed))
    if pipeline_id in DEMO_WORKSPACE_FOLDERS:
        return DEMO_WORKSPACE_FOLDERS[pipeline_id]
    return DEFAULT_MY_PIPELINES


def sync_workspace_from_pipelines(
    work_dir: Path,
    pipelines: list[Any],
) -> dict[str, Any]:
    """Rebuild index from pipeline metadata; seed demos; persist workspace.json."""
    ws = load_workspace(work_dir)
    folders = list(ws["folders"])
    pipeline_folders: dict[str, str] = dict(ws.get("pipelineFolders") or {})

    for p in pipelines:
        pid = getattr(p, "id", None) or (p.get("id") if isinstance(p, dict) else None)
        if not pid:
            continue
        meta = getattr(p, "metadata", None)
        if meta is None and isinstance(p, dict):
            meta = p.get("metadata")
        folder = resolve_pipeline_folder(str(pid), meta if isinstance(meta, dict) else None, ws)
        pipeline_folders[str(pid)] = folder
        folders = ensure_folder_in_list(folders, folder)

    for pid, folder in DEMO_WORKSPACE_FOLDERS.items():
        pipeline_folders.setdefault(pid, folder)
        folders = ensure_folder_in_list(folders, folder)

    return save_workspace(
        work_dir,
        {"folders": folders, "pipelineFolders": pipeline_folders},
    )


def stamp_workspace_folder(
    metadata: dict[str, Any] | None,
    folder: str,
) -> dict[str, Any]:
    meta = dict(metadata or {})
    meta["workspace_folder"] = _normalize_folder(folder) or DEFAULT_MY_PIPELINES
    return meta


def apply_demo_workspace_folder(pipeline_id: str, metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Ensure demo metadata carries workspace_folder (idempotent)."""
    meta = dict(metadata or {})
    if folder_from_metadata(meta):
        return meta
    seed = DEMO_WORKSPACE_FOLDERS.get(pipeline_id)
    if seed:
        meta["workspace_folder"] = seed
    return meta
