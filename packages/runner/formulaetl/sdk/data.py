"""Neutral execution data handles: row batches, datasets, file artifacts.

Phase B: bounded batches and on-disk artifact handles. Not a Spark/K8s
runtime. ``list[dict]`` remains the adapter for legacy components.
"""

from __future__ import annotations

import csv
import hashlib
import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_BATCH_SIZE = int(os.environ.get("FORMULAETL_BATCH_SIZE", "1024") or "1024")

_CONTENT_TYPES: dict[str, str] = {
    ".csv": "text/csv",
    ".json": "application/json",
    ".jsonl": "application/jsonl",
    ".xml": "application/xml",
    ".txt": "text/plain",
    ".pgp": "application/pgp-encrypted",
    ".gpg": "application/pgp-encrypted",
    ".asc": "application/pgp-keys",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
}


def guess_content_type(path: str | Path) -> str:
    return _CONTENT_TYPES.get(Path(path).suffix.lower(), "application/octet-stream")


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class RowBatch:
    """One bounded chunk of row dicts (adapter element for ``list[dict]``)."""

    rows: list[dict[str, Any]]
    batch_index: int = 0
    eof: bool = False

    def __len__(self) -> int:
        return len(self.rows)

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self.rows)


@dataclass
class ArtifactHandle:
    """Pointer to a file-like object. Prefer this over passing ``bytes`` in RAM."""

    uri: str
    size: int | None = None
    content_type: str | None = None
    checksum: str | None = None
    temp: bool = False
    path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "size": self.size,
            "content_type": self.content_type,
            "checksum": self.checksum,
            "temp": self.temp,
            "path": self.path,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ArtifactHandle | None:
        if not data or not data.get("uri"):
            return None
        return cls(
            uri=str(data["uri"]),
            size=data.get("size"),
            content_type=data.get("content_type"),
            checksum=data.get("checksum"),
            temp=bool(data.get("temp", False)),
            path=data.get("path"),
        )

    def local_path(self) -> Path:
        if self.path:
            return Path(self.path)
        if self.uri.startswith("file://"):
            return Path(self.uri[7:])
        return Path(self.uri)

    def open(self, mode: str = "rb"):
        return self.local_path().open(mode)

    def read_bytes(self) -> bytes:
        """Legacy adapter for components that still require a byte array."""
        return self.local_path().read_bytes()

    @classmethod
    def from_path(
        cls,
        path: str | Path,
        *,
        content_type: str | None = None,
        temp: bool = False,
        checksum: bool = True,
    ) -> ArtifactHandle:
        p = Path(path)
        size = p.stat().st_size if p.exists() else None
        digest = sha256_file(p) if checksum and p.exists() else None
        try:
            uri = p.resolve().as_uri()
        except OSError:
            uri = f"file://{p}"
        return cls(
            uri=uri,
            size=size,
            content_type=content_type or guess_content_type(p),
            checksum=digest,
            temp=temp,
            path=str(p),
        )


def write_bytes_artifact(
    path: str | Path,
    data: bytes,
    *,
    temp: bool = True,
    content_type: str | None = None,
) -> ArtifactHandle:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return ArtifactHandle.from_path(p, content_type=content_type, temp=temp)


class DatasetHandle:
    """Handle to tabular data. Iterate ``RowBatch``es; ``materialize()`` is the list[dict] adapter."""

    def __init__(
        self,
        *,
        rows: list[dict[str, Any]] | None = None,
        producer: Callable[[int], Iterator[RowBatch]] | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        row_count: int | None = None,
    ) -> None:
        self.batch_size = max(1, int(batch_size or DEFAULT_BATCH_SIZE))
        self._producer = producer
        self._rows = rows
        self._materialized = rows
        if row_count is not None:
            self._row_count = row_count
        elif rows is not None:
            self._row_count = len(rows)
        else:
            self._row_count = None

    @classmethod
    def from_rows(
        cls,
        rows: list[dict[str, Any]] | None,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> DatasetHandle:
        return cls(rows=list(rows or []), batch_size=batch_size)

    @classmethod
    def from_csv_path(
        cls,
        path: str | Path,
        *,
        delimiter: str = ",",
        encoding: str = "utf-8",
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> DatasetHandle:
        file_path = Path(path)

        def producer(bs: int) -> Iterator[RowBatch]:
            with file_path.open(newline="", encoding=encoding) as fh:
                reader = csv.DictReader(fh, delimiter=delimiter)
                buf: list[dict[str, Any]] = []
                idx = 0
                for rec in reader:
                    buf.append(dict(rec))
                    if len(buf) >= bs:
                        yield RowBatch(rows=buf, batch_index=idx, eof=False)
                        idx += 1
                        buf = []
                yield RowBatch(rows=buf, batch_index=idx, eof=True)

        return cls(producer=producer, batch_size=batch_size)

    @property
    def row_count(self) -> int | None:
        return self._row_count

    def iter_batches(self, batch_size: int | None = None) -> Iterator[RowBatch]:
        bs = max(1, int(batch_size or self.batch_size))
        if self._materialized is not None:
            yield from _chunk_rows(self._materialized, bs)
            return
        if self._producer is None:
            yield RowBatch(rows=[], batch_index=0, eof=True)
            return
        acc: list[dict[str, Any]] = []
        last: RowBatch | None = None
        for batch in self._producer(bs):
            acc.extend(batch.rows)
            last = batch
            yield batch
        if last is None:
            yield RowBatch(rows=[], batch_index=0, eof=True)
        self._materialized = acc
        self._row_count = len(acc)

    def materialize(self) -> list[dict[str, Any]]:
        """Adapter: full ``list[dict]`` for legacy ``run(ctx, rows)`` components."""
        if self._materialized is not None:
            return self._materialized
        acc: list[dict[str, Any]] = []
        for batch in self.iter_batches():
            acc.extend(batch.rows)
        self._materialized = acc
        self._row_count = len(acc)
        return acc


def _chunk_rows(rows: list[dict[str, Any]], batch_size: int) -> Iterator[RowBatch]:
    if not rows:
        yield RowBatch(rows=[], batch_index=0, eof=True)
        return
    idx = 0
    n = len(rows)
    for start in range(0, n, batch_size):
        chunk = rows[start : start + batch_size]
        eof = start + batch_size >= n
        yield RowBatch(rows=chunk, batch_index=idx, eof=eof)
        idx += 1
