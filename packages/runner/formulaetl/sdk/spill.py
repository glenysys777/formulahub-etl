"""JSONL spill helpers — bound RAM between hops (Talend-style OOM avoidance).

Large intermediates are written as newline-delimited JSON under the run temp
dir and re-read as ``DatasetHandle`` batches. This is LOCAL process spill,
not a distributed filesystem.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from formulaetl.sdk.data import DEFAULT_BATCH_SIZE, DatasetHandle, RowBatch

# Rows kept in ComponentResult.rows for small/debug convenience. Above this,
# results are spill-backed and ``rows`` stays empty (use ``dataset``).
SPILL_THRESHOLD = int(os.environ.get("FORMULAETL_SPILL_THRESHOLD", "25000") or "25000")

# When "1" (default), batched hops spill instead of concatenating full lists.
STREAM_SPILL = os.environ.get("FORMULAETL_STREAM_SPILL", "1") != "0"


def spill_enabled() -> bool:
    return STREAM_SPILL


class JsonlSpillWriter:
    """Append row dicts to a JSONL file; close() → DatasetHandle."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("w", encoding="utf-8")
        self.row_count = 0

    def write_rows(self, rows: list[dict[str, Any]] | None) -> None:
        if not rows:
            return
        for row in rows:
            self._fh.write(json.dumps(row, default=str, separators=(",", ":")))
            self._fh.write("\n")
        self.row_count += len(rows)

    def close(self, *, batch_size: int = DEFAULT_BATCH_SIZE) -> DatasetHandle:
        self._fh.close()
        return DatasetHandle.from_jsonl_path(
            self.path, batch_size=batch_size, row_count=self.row_count
        )


def new_spill_path(spill_dir: Path, label: str = "out") -> Path:
    spill_dir.mkdir(parents=True, exist_ok=True)
    return spill_dir / f"{label}_{uuid.uuid4().hex[:12]}.jsonl"


def iter_jsonl_batches(
    path: str | Path,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> Iterator[RowBatch]:
    bs = max(1, int(batch_size))
    p = Path(path)
    if not p.exists():
        yield RowBatch(rows=[], batch_index=0, eof=True)
        return
    buf: list[dict[str, Any]] = []
    batch_idx = 0
    with p.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            buf.append(json.loads(line))
            if len(buf) >= bs:
                yield RowBatch(rows=buf, batch_index=batch_idx, eof=False)
                batch_idx += 1
                buf = []
    yield RowBatch(rows=buf, batch_index=batch_idx, eof=True)
