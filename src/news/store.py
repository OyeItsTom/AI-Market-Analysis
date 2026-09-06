"""Append-only local storage for external records.

    data/news/<source>/documents.jsonl       one line per document revision
    data/news/<source>/associations.jsonl    one line per (document, symbol) link

Documents and associations are stored separately because they are different
facts. A document is global to its source; an association is *query-specific*.
One Yahoo article is routinely returned for several symbols -- measured, not
assumed -- so storing a copy per symbol would duplicate documents and make
"deduplicated" a false claim. One document, several links, is what actually
happened.

Append-only, and why
--------------------
Nothing is ever overwritten. A revision is a **new complete observation**, so
the record of what this system believed at any past moment survives: an
``as_of`` query replays the file up to a point in time. Editing a row in place
would answer "what is true now?" while destroying "what did we think then?",
and the second question is the one a research system is built to answer.

Corruption is loud
------------------
A malformed line is never skipped in silence. Reads raise by default, naming the
file, line and byte offset; a caller that wants to continue must ask for
:data:`OnCorruption.REPORT` and is handed an integrity report it has to deal
with. Nothing is truncated, rewritten or repaired automatically -- the bad bytes
stay on disk as evidence, because a store that quietly discards what it cannot
parse cannot be audited.

Concurrency
-----------
**One local process, one writer.** No locking is implemented and none is
implied. This is a single-user local research tool; the assumption is stated
here rather than left to be discovered.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence

from .cik_map import DEFAULT_NEWS_ROOT
from .identity import immutable_signature
from .models import (
    AvailabilityBasis,
    Document,
    EventType,
    NewsError,
    NewsItem,
    OfficialFiling,
    SourceClass,
    SymbolAssociation,
    SymbolLink,
)
from .source import ItemOutcome

#: Bumped when the meaning of a stored line changes. A reader refuses a version
#: it does not know rather than interpreting unfamiliar bytes as current.
SCHEMA_VERSION = 1

DOCUMENTS_FILE = "documents.jsonl"
ASSOCIATIONS_FILE = "associations.jsonl"


class StorageError(NewsError):
    """Raised when the store cannot read or write."""


class UnsupportedSchemaError(StorageError):
    """A stored line declares a schema version this build does not know.

    Deliberately fatal rather than best-effort: a future writer may have
    changed what a field *means*, and interpreting it under today's rules would
    produce confident nonsense.
    """


class CorruptionKind(str, Enum):
    """Where the damage is, because the two mean different things."""

    #: The final line only -- consistent with an append interrupted by a crash
    #: or a full disk. Everything before it is intact.
    CORRUPT_TAIL = "corrupt_tail"

    #: A line with valid lines after it. An append cannot cause this, so it
    #: indicates real corruption of already-written bytes.
    CORRUPT_INTERIOR = "corrupt_interior"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class OnCorruption(str, Enum):
    """What a read should do when it meets a line it cannot parse."""

    #: Raise. The default, so corruption cannot pass unnoticed.
    RAISE = "raise"

    #: Return the valid records plus a report the caller must handle.
    REPORT = "report"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class CorruptLine:
    """One unparseable line, located precisely enough to inspect by hand."""

    path: str
    line_number: int
    byte_offset: int
    kind: CorruptionKind
    detail: str

    def describe(self) -> str:
        return (
            f"{self.path}:{self.line_number} (byte {self.byte_offset}) "
            f"{self.kind.value}: {self.detail}"
        )


@dataclass(frozen=True)
class StoreIntegrityReport:
    """Damage found during a tolerant read. Never empty when it exists."""

    corrupt_lines: tuple[CorruptLine, ...]

    @property
    def is_clean(self) -> bool:
        return not self.corrupt_lines

    def describe(self) -> str:
        return "; ".join(line.describe() for line in self.corrupt_lines)


class NewsStoreCorruption(StorageError):
    """Raised on a strict read of a damaged file."""

    def __init__(self, report: StoreIntegrityReport) -> None:
        super().__init__(
            "the news store contains unreadable records and was not modified: "
            + report.describe()
        )
        self.report = report


@dataclass(frozen=True)
class WriteResult:
    """What happened to one record, and why."""

    outcome: ItemOutcome
    document: Document | None = None
    detail: str = ""


# -- serialization -------------------------------------------------------


def _stamp(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(timezone.utc).isoformat()


def _parse_stamp(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise StorageError(f"timestamp must be a string, got {type(value).__name__}")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise StorageError(f"stored timestamp {value!r} is not timezone-aware")
    return parsed


def document_to_row(document: Document) -> dict[str, Any]:
    """Flatten a document for storage, keeping both record kinds distinguishable."""
    common = {
        "schema_version": SCHEMA_VERSION,
        "source": document.source,
        "source_item_id": document.source_item_id,
        "source_class": document.source_class.value,
        "headline": document.headline,
        "canonical_url": document.canonical_url,
        "retrieved_at": _stamp(document.retrieved_at),
        "available_from": _stamp(document.available_from),
        "availability_basis": document.availability_basis.value,
        "event_type": document.event_type.value,
        "revision": document.revision,
        "content_hash": document.content_hash,
    }
    if isinstance(document, OfficialFiling):
        common.update(
            {
                "record_kind": "official_filing",
                "cik": document.cik,
                "form": document.form,
                "items": list(document.items),
                "filing_date": document.filing_date,
                "report_date": document.report_date,
                "primary_document_url": document.primary_document_url,
                "source_event_time": _stamp(document.source_event_time),
            }
        )
    else:
        common.update(
            {
                "record_kind": "news_item",
                "publisher": document.publisher,
                "summary": document.summary,
                "source_published_at": _stamp(document.source_published_at),
            }
        )
    return common


def row_to_document(row: Mapping[str, Any]) -> Document:
    version = row.get("schema_version")
    if version != SCHEMA_VERSION:
        raise UnsupportedSchemaError(
            f"stored record declares schema_version {version!r}, but this build "
            f"understands only {SCHEMA_VERSION}; refusing to reinterpret it"
        )
    kind = row.get("record_kind")
    if kind == "official_filing":
        return OfficialFiling(
            source=row["source"],
            source_item_id=row["source_item_id"],
            source_class=SourceClass(row["source_class"]),
            cik=row["cik"],
            form=row["form"],
            headline=row["headline"],
            canonical_url=row["canonical_url"],
            primary_document_url=row["primary_document_url"],
            retrieved_at=_parse_stamp(row["retrieved_at"]),
            availability_basis=AvailabilityBasis(row["availability_basis"]),
            filing_date=row.get("filing_date", ""),
            report_date=row.get("report_date", ""),
            items=tuple(row.get("items", ())),
            source_event_time=_parse_stamp(row.get("source_event_time")),
            available_from=_parse_stamp(row.get("available_from")),
            event_type=EventType(row.get("event_type", EventType.FILING.value)),
            revision=row.get("revision", 1),
            content_hash=row.get("content_hash", ""),
        )
    if kind == "news_item":
        return NewsItem(
            source=row["source"],
            source_item_id=row["source_item_id"],
            source_class=SourceClass(row["source_class"]),
            publisher=row.get("publisher", ""),
            headline=row["headline"],
            canonical_url=row["canonical_url"],
            retrieved_at=_parse_stamp(row["retrieved_at"]),
            availability_basis=AvailabilityBasis(row["availability_basis"]),
            summary=row.get("summary", ""),
            source_published_at=_parse_stamp(row.get("source_published_at")),
            available_from=_parse_stamp(row.get("available_from")),
            event_type=EventType(row.get("event_type", EventType.UNKNOWN.value)),
            revision=row.get("revision", 1),
            content_hash=row.get("content_hash", ""),
        )
    raise StorageError(f"unknown record_kind {kind!r}")


def link_to_row(link: SymbolLink) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "source": link.source,
        "source_item_id": link.source_item_id,
        "symbol": link.symbol,
        "association": link.association.value,
        "queried_symbol": link.queried_symbol,
        "retrieved_at": _stamp(link.retrieved_at),
        "cik_map_last_modified": link.cik_map_last_modified,
    }


def row_to_link(row: Mapping[str, Any]) -> SymbolLink:
    version = row.get("schema_version")
    if version != SCHEMA_VERSION:
        raise UnsupportedSchemaError(
            f"stored association declares schema_version {version!r}, but this build "
            f"understands only {SCHEMA_VERSION}"
        )
    return SymbolLink(
        source=row["source"],
        source_item_id=row["source_item_id"],
        symbol=row["symbol"],
        association=SymbolAssociation(row["association"]),
        retrieved_at=_parse_stamp(row["retrieved_at"]),
        queried_symbol=row.get("queried_symbol", ""),
        cik_map_last_modified=row.get("cik_map_last_modified", ""),
    )


# -- the store -----------------------------------------------------------


class NewsStore:
    """Append-only JSONL document and association storage for one root."""

    def __init__(self, root: str | Path = DEFAULT_NEWS_ROOT) -> None:
        self._root = Path(root)

    # -- paths -----------------------------------------------------------

    def documents_path(self, source: str) -> Path:
        return self._root / _safe_component(source) / DOCUMENTS_FILE

    def associations_path(self, source: str) -> Path:
        return self._root / _safe_component(source) / ASSOCIATIONS_FILE

    # -- reading ---------------------------------------------------------

    def _read_rows(
        self, path: Path, on_corruption: OnCorruption
    ) -> tuple[list[dict[str, Any]], StoreIntegrityReport]:
        """Parse a JSONL file, locating any damage precisely."""
        if not path.is_file():
            return [], StoreIntegrityReport(())

        rows: list[dict[str, Any]] = []
        corrupt: list[CorruptLine] = []
        offset = 0
        raw_lines = path.read_bytes().split(b"\n")
        # A trailing newline yields a final empty element, which is not a record.
        if raw_lines and raw_lines[-1] == b"":
            raw_lines.pop()

        for index, raw in enumerate(raw_lines, start=1):
            line_offset = offset
            offset += len(raw) + 1
            if not raw.strip():
                continue
            try:
                row = json.loads(raw.decode("utf-8"))
                if not isinstance(row, dict):
                    raise ValueError("line is not a JSON object")
                rows.append(row)
            except UnicodeDecodeError as exc:
                corrupt.append(
                    CorruptLine(str(path), index, line_offset,
                                CorruptionKind.CORRUPT_INTERIOR, f"invalid UTF-8: {exc}")
                )
            except Exception as exc:
                corrupt.append(
                    CorruptLine(str(path), index, line_offset,
                                CorruptionKind.CORRUPT_INTERIOR, str(exc)[:200])
                )

        # A damaged final line is consistent with an interrupted append; damage
        # anywhere else means already-written bytes changed, which is worse.
        total = len(raw_lines)
        corrupt = [
            CorruptLine(entry.path, entry.line_number, entry.byte_offset,
                        CorruptionKind.CORRUPT_TAIL if entry.line_number == total
                        else CorruptionKind.CORRUPT_INTERIOR,
                        entry.detail)
            for entry in corrupt
        ]
        report = StoreIntegrityReport(tuple(corrupt))
        if corrupt and on_corruption is OnCorruption.RAISE:
            raise NewsStoreCorruption(report)
        return rows, report

    def read_documents(
        self, source: str, *, on_corruption: OnCorruption = OnCorruption.RAISE
    ) -> tuple[tuple[Document, ...], StoreIntegrityReport]:
        rows, report = self._read_rows(self.documents_path(source), on_corruption)
        return tuple(row_to_document(row) for row in rows), report

    def read_links(
        self, source: str, *, on_corruption: OnCorruption = OnCorruption.RAISE
    ) -> tuple[tuple[SymbolLink, ...], StoreIntegrityReport]:
        rows, report = self._read_rows(self.associations_path(source), on_corruption)
        return tuple(row_to_link(row) for row in rows), report

    def latest_documents(
        self, source: str, *, as_of: datetime | None = None,
        on_corruption: OnCorruption = OnCorruption.RAISE,
    ) -> tuple[tuple[Document, ...], StoreIntegrityReport]:
        """Highest revision per document, optionally as this system knew it at
        ``as_of``.

        ``as_of`` filters on ``retrieved_at``, which is what makes the question
        "what had we observed by T?" answerable: it replays our own observation
        history rather than the world's.
        """
        documents, report = self.read_documents(source, on_corruption=on_corruption)
        latest: dict[tuple[str, str], Document] = {}
        for document in documents:
            if as_of is not None and document.retrieved_at > as_of:
                continue
            current = latest.get(document.item_key)
            if current is None or document.revision > current.revision:
                latest[document.item_key] = document
        return tuple(latest.values()), report

    # -- writing ---------------------------------------------------------

    def _append(self, path: Path, row: Mapping[str, Any]) -> None:
        """Append one complete line, then flush and fsync.

        No claim is made that this is atomic on every filesystem. The safety
        net is detection on the next read, not a guarantee here: a line that
        was half written is found and reported rather than assumed absent.
        """
        payload = json.dumps(row, ensure_ascii=False, sort_keys=True)
        if "\n" in payload or "\r" in payload:  # pragma: no cover - defensive
            raise StorageError("serialized record contains a newline")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(payload + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def write_document(self, document: Document) -> WriteResult:
        """Classify ``document`` against what is stored, and append if it is new.

        Three outcomes, and the third is the one that matters:

        * identical content -> ``DUPLICATE``, nothing written;
        * changed content -> ``REVISION``, appended with the next revision number;
        * a field that may never change has changed -> ``ID_REUSE_CONFLICT``,
          nothing written, because the identifier now refers to something else
          and appending would rewrite an unrelated document's history.
        """
        source = document.source
        stored, _ = self.latest_documents(source)
        existing = {item.item_key: item for item in stored}
        current = existing.get(document.item_key)

        if current is None:
            self._append(self.documents_path(source), document_to_row(document))
            return WriteResult(ItemOutcome.ACCEPTED, document)

        row_current = document_to_row(current)
        row_new = document_to_row(document)
        if immutable_signature(source, row_current) != immutable_signature(source, row_new):
            return WriteResult(
                ItemOutcome.ID_REUSE_CONFLICT,
                current,
                f"identifier {document.source_item_id!r} already refers to a different "
                "record; its immutable fields changed",
            )

        if current.content_hash and current.content_hash == document.content_hash:
            return WriteResult(ItemOutcome.DUPLICATE, current)

        revised = _with_revision(document, current.revision + 1)
        self._append(self.documents_path(source), document_to_row(revised))
        return WriteResult(ItemOutcome.REVISION, revised)

    def write_link(self, link: SymbolLink) -> bool:
        """Append an association unless the identical one is already stored."""
        stored, _ = self.read_links(link.source)
        if any(existing.link_key == link.link_key for existing in stored):
            return False
        self._append(self.associations_path(link.source), link_to_row(link))
        return True


def _with_revision(document: Document, revision: int) -> Document:
    """A copy at a new revision number, preserving every observed timestamp.

    ``dataclasses.replace`` is used deliberately: it re-runs validation, and it
    copies *this* observation's source timestamps rather than inheriting the
    previous revision's, so a provider that silently restated when it published
    leaves both values on the record.
    """
    from dataclasses import replace

    return replace(document, revision=revision)


def _safe_component(value: str) -> str:
    """Reject anything that could escape the store root."""
    text = str(value).strip()
    if (
        not text
        or text in {".", ".."}
        or any(character in text for character in ("/", "\\", "..", "\0"))
    ):
        raise StorageError(f"unsafe path component {value!r}")
    return text


__all__ = [
    "SCHEMA_VERSION",
    "DOCUMENTS_FILE",
    "ASSOCIATIONS_FILE",
    "StorageError",
    "UnsupportedSchemaError",
    "CorruptionKind",
    "OnCorruption",
    "CorruptLine",
    "StoreIntegrityReport",
    "NewsStoreCorruption",
    "WriteResult",
    "NewsStore",
    "document_to_row",
    "row_to_document",
    "link_to_row",
    "row_to_link",
]
