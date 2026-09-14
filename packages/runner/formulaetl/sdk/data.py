"""Neutral execution data handles: row batches, datasets, file artifacts.

Phase B: bounded batches and on-disk artifact handles. Not a Spark/K8s
runtime. ``list[dict]`` remains the adapter for legacy components.

Phase C: CSV streaming with malformed-row policy, row numbers, Unicode.
"""

from __future__ import annotations

import csv
import hashlib
import io
import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

DEFAULT_BATCH_SIZE = int(os.environ.get("FORMULAETL_BATCH_SIZE", "1024") or "1024")

MalformedPolicy = Literal["fail", "skip", "reject"]
ExtraColumnsPolicy = Literal["keep", "drop", "reject"]
MissingColumnsPolicy = Literal["fill", "reject"]

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
        quotechar: str = '"',
        has_header: bool = True,
        fieldnames: list[str] | None = None,
        null_values: tuple[str, ...] = ("", "NULL", "null", "None"),
        empty_as_null: bool = False,
        malformed_policy: MalformedPolicy = "reject",
        extra_columns: ExtraColumnsPolicy = "keep",
        missing_columns: MissingColumnsPolicy = "fill",
        add_row_numbers: bool = False,
        row_number_field: str = "_row_number",
        rejects_out: list[dict[str, Any]] | None = None,
    ) -> DatasetHandle:
        """Stream a CSV file as ``RowBatch``es without loading the whole file first.

        Malformed rows (wrong field counts that csv cannot recover, encoding
        issues already surface as UnicodeDecodeError) follow ``malformed_policy``.
        Extra/missing columns relative to the header follow ``extra_columns`` /
        ``missing_columns``. Rejects are appended to ``rejects_out`` when provided.
        """
        file_path = Path(path)
        opts = CsvReadOptions(
            delimiter=delimiter,
            encoding=encoding,
            quotechar=quotechar,
            has_header=has_header,
            fieldnames=fieldnames,
            null_values=null_values,
            empty_as_null=empty_as_null,
            malformed_policy=malformed_policy,
            extra_columns=extra_columns,
            missing_columns=missing_columns,
            add_row_numbers=add_row_numbers,
            row_number_field=row_number_field,
        )

        def producer(bs: int) -> Iterator[RowBatch]:
            yield from iter_csv_batches(
                file_path,
                batch_size=bs,
                options=opts,
                rejects_out=rejects_out,
            )

        return cls(producer=producer, batch_size=batch_size)

    @classmethod
    def from_csv_text(
        cls,
        content: str,
        *,
        delimiter: str = ",",
        encoding: str = "utf-8",
        batch_size: int = DEFAULT_BATCH_SIZE,
        quotechar: str = '"',
        has_header: bool = True,
        fieldnames: list[str] | None = None,
        null_values: tuple[str, ...] = ("", "NULL", "null", "None"),
        empty_as_null: bool = False,
        malformed_policy: MalformedPolicy = "reject",
        extra_columns: ExtraColumnsPolicy = "keep",
        missing_columns: MissingColumnsPolicy = "fill",
        add_row_numbers: bool = False,
        row_number_field: str = "_row_number",
        rejects_out: list[dict[str, Any]] | None = None,
    ) -> DatasetHandle:
        opts = CsvReadOptions(
            delimiter=delimiter,
            encoding=encoding,
            quotechar=quotechar,
            has_header=has_header,
            fieldnames=fieldnames,
            null_values=null_values,
            empty_as_null=empty_as_null,
            malformed_policy=malformed_policy,
            extra_columns=extra_columns,
            missing_columns=missing_columns,
            add_row_numbers=add_row_numbers,
            row_number_field=row_number_field,
        )

        def producer(bs: int) -> Iterator[RowBatch]:
            yield from iter_csv_batches(
                io.StringIO(content),
                batch_size=bs,
                options=opts,
                rejects_out=rejects_out,
            )

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


@dataclass
class CsvReadOptions:
    delimiter: str = ","
    encoding: str = "utf-8"
    quotechar: str = '"'
    has_header: bool = True
    fieldnames: list[str] | None = None
    null_values: tuple[str, ...] = ("", "NULL", "null", "None")
    empty_as_null: bool = False
    malformed_policy: MalformedPolicy = "reject"
    extra_columns: ExtraColumnsPolicy = "keep"
    missing_columns: MissingColumnsPolicy = "fill"
    add_row_numbers: bool = False
    row_number_field: str = "_row_number"


_RESTKEY = "__csv_extra__"
_MISSING = "__csv_missing__"


def _normalize_cell(value: Any, opts: CsvReadOptions) -> Any:
    if value is None or value is _MISSING:
        return None
    if not isinstance(value, str):
        return value
    if opts.empty_as_null and value in opts.null_values:
        return None
    if value in opts.null_values and value != "":
        return None
    return value


def _open_csv_source(source: str | Path | io.StringIO, encoding: str):
    if isinstance(source, io.StringIO):
        source.seek(0)
        return source, False
    path = Path(source)
    return path.open(newline="", encoding=encoding), True


def iter_csv_batches(
    source: str | Path | io.StringIO,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    options: CsvReadOptions | None = None,
    rejects_out: list[dict[str, Any]] | None = None,
) -> Iterator[RowBatch]:
    """Yield bounded ``RowBatch``es from a CSV path or in-memory text buffer."""
    opts = options or CsvReadOptions()
    bs = max(1, int(batch_size))
    fh, close = _open_csv_source(source, opts.encoding)
    try:
        # DictReader handles quoted commas / multiline quotes. restval=_MISSING
        # distinguishes physically absent columns from empty strings.
        if opts.has_header:
            reader = csv.DictReader(
                fh,
                delimiter=opts.delimiter,
                quotechar=opts.quotechar,
                restkey=_RESTKEY,
                restval=_MISSING,
            )
            headers = list(reader.fieldnames or [])
        else:
            headers = list(opts.fieldnames or [])
            if not headers:
                raise ValueError("CSV: has_header=false requires fieldnames")
            reader = csv.DictReader(
                fh,
                fieldnames=headers,
                delimiter=opts.delimiter,
                quotechar=opts.quotechar,
                restkey=_RESTKEY,
                restval=_MISSING,
            )

        buf: list[dict[str, Any]] = []
        batch_idx = 0
        data_row = 0

        for raw in reader:
            data_row += 1
            try:
                row, reject_reason = _normalize_csv_row(raw, headers, opts, data_row)
            except csv.Error as exc:
                reject_reason = f"csv parse error: {exc}"
                row = None
            except UnicodeError as exc:
                if opts.malformed_policy == "fail":
                    raise
                reject_reason = f"unicode error: {exc}"
                row = None

            if reject_reason:
                bad = {
                    k: (None if v is _MISSING else v)
                    for k, v in (raw.items() if isinstance(raw, dict) else [])
                    if k != _RESTKEY
                }
                if opts.add_row_numbers:
                    bad[opts.row_number_field] = data_row
                bad["_reject_reason"] = reject_reason
                if opts.malformed_policy == "fail":
                    raise ValueError(
                        f"CSV malformed at row {data_row}: {reject_reason}"
                    )
                if opts.malformed_policy == "reject" and rejects_out is not None:
                    rejects_out.append(bad)
                continue

            assert row is not None
            buf.append(row)
            if len(buf) >= bs:
                yield RowBatch(rows=buf, batch_index=batch_idx, eof=False)
                batch_idx += 1
                buf = []

        yield RowBatch(rows=buf, batch_index=batch_idx, eof=True)
    finally:
        if close:
            fh.close()


def _normalize_csv_row(
    raw: dict[str, Any],
    headers: list[str],
    opts: CsvReadOptions,
    data_row: int,
) -> tuple[dict[str, Any] | None, str | None]:
    """Return (row, reject_reason). Exactly one of them is non-None on reject."""
    extra_vals = raw.pop(_RESTKEY, None)
    raw.pop(None, None)

    if extra_vals is not None:
        reason = f"extra columns beyond header ({len(extra_vals)} value(s))"
        if opts.malformed_policy == "fail":
            raise ValueError(f"CSV malformed at row {data_row}: {reason}")
        if opts.extra_columns == "reject":
            return None, reason
        if opts.extra_columns == "keep":
            for i, val in enumerate(extra_vals):
                raw[f"_extra_{i}"] = _normalize_cell(val, opts)

    missing = [h for h in headers if h and raw.get(h) is _MISSING]
    if missing and opts.missing_columns == "reject":
        return None, f"missing columns: {missing}"

    out: dict[str, Any] = {}
    for h in headers:
        if not h:
            continue
        if h not in raw or raw[h] is _MISSING:
            out[h] = None
        else:
            out[h] = _normalize_cell(raw[h], opts)

    for k, v in raw.items():
        if k not in out and k != _RESTKEY:
            out[k] = _normalize_cell(v, opts)

    if opts.add_row_numbers:
        out[opts.row_number_field] = data_row
    return out, None
