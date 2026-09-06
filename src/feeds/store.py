"""Append-only local storage for feed items and their symbol associations.

    data/feeds/<source_id>/documents.jsonl
    data/feeds/<source_id>/associations.jsonl

Items and associations are separate because they are different facts. An item is
what a feed published; an association is an observation made under one
configuration vintage. Adding a symbol to a feed later must create a new
association without rewriting what earlier records meant, and that is only
expressible if the two are stored apart.

Nothing is overwritten. A revision is a complete new observation, so the record
of what this system believed at any past moment survives and ``as_of`` can
replay it.

Corruption is loud: a malformed line is never skipped in silence. Reads raise by
default, naming file, line and byte offset, and nothing is truncated, rewritten
or repaired automatically -- a store that quietly discards what it cannot parse
cannot be audited, which is the whole point of keeping one.

Concurrency: one local process, one writer. No locking is implemented and none
is implied.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from .identity import url_host
from .models import (
    AvailabilityBasis,
    DeclaredTrustClass,
    FeedError,
    FeedItem,
    SymbolAssociation,
    SymbolLink,
    TrustBasis,
    require_source_id,
)
from .source import ItemOutcome

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FEEDS_ROOT = REPO_ROOT / "data" / "feeds"

SCHEMA_VERSION = 1
DOCUMENTS_FILE = "documents.jsonl"
ASSOCIATIONS_FILE = "associations.jsonl"


class StorageError(FeedError):
    """Raised when the store cannot be read or written."""


class UnsupportedSchemaError(StorageError):
    """A stored line declares a schema version this build does not know.

    Fatal rather than best-effort: a future writer may have changed what a field
    *means*, and reading it under today's rules would produce confident nonsense.
    """


class CorruptionKind(str, Enum):
    """Where the damage is, because the two mean different things."""

    #: The final line only -- consistent with an append interrupted by a crash.
    CORRUPT_TAIL = "corrupt_tail"

    #: A bad line with valid lines after it. An append cannot cause that, so
    #: already-written bytes have changed.
    CORRUPT_INTERIOR = "corrupt_interior"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class OnCorruption(str, Enum):
    RAISE = "raise"
    REPORT = "report"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class CorruptLine:
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
    corrupt_lines: tuple[CorruptLine, ...]

    @property
    def is_clean(self) -> bool:
        return not self.corrupt_lines

    def describe(self) -> str:
        return "; ".join(line.describe() for line in self.corrupt_lines)


class FeedStoreCorruption(StorageError):
    """Raised on a strict read of a damaged file."""

    def __init__(self, report: StoreIntegrityReport) -> None:
        super().__init__(
            "the feed store contains unreadable records and was not modified: "
            + report.describe()
        )
        self.report = report


@dataclass(frozen=True)
class WriteResult:
    outcome: ItemOutcome
    item: FeedItem | None = None
    detail: str = ""


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


def item_to_row(item: FeedItem) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "source_id": item.source_id,
        "feed_item_id": item.feed_item_id,
        "declared_trust_class": item.declared_trust_class.value,
        "trust_basis": item.trust_basis.value,
        "title": item.title,
        "publisher": item.publisher,
        "excerpt": item.excerpt,
        "canonical_url": item.canonical_url,
        "retrieved_at": _stamp(item.retrieved_at),
        "source_published_at": _stamp(item.source_published_at),
        "source_edited_at": _stamp(item.source_edited_at),
        "available_from": _stamp(item.available_from),
        "availability_basis": item.availability_basis.value,
        "config_fingerprint": item.config_fingerprint,
        "revision": item.revision,
        "content_hash": item.content_hash,
    }


def row_to_item(row: Mapping[str, Any]) -> FeedItem:
    version = row.get("schema_version")
    if version != SCHEMA_VERSION:
        raise UnsupportedSchemaError(
            f"stored record declares schema_version {version!r}, but this build "
            f"understands only {SCHEMA_VERSION}; refusing to reinterpret it"
        )
    return FeedItem(
        source_id=row["source_id"],
        feed_item_id=row["feed_item_id"],
        declared_trust_class=DeclaredTrustClass(row["declared_trust_class"]),
        trust_basis=TrustBasis(row["trust_basis"]),
        title=row["title"],
        canonical_url=row["canonical_url"],
        retrieved_at=_parse_stamp(row["retrieved_at"]),
        availability_basis=AvailabilityBasis(row["availability_basis"]),
        config_fingerprint=row["config_fingerprint"],
        publisher=row.get("publisher", ""),
        excerpt=row.get("excerpt", ""),
        source_published_at=_parse_stamp(row.get("source_published_at")),
        source_edited_at=_parse_stamp(row.get("source_edited_at")),
        available_from=_parse_stamp(row.get("available_from")),
        revision=row.get("revision", 1),
        content_hash=row.get("content_hash", ""),
    )


def link_to_row(link: SymbolLink) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "source_id": link.source_id,
        "feed_item_id": link.feed_item_id,
        "symbol": link.symbol,
        "association": link.association.value,
        "retrieved_at": _stamp(link.retrieved_at),
        "config_fingerprint": link.config_fingerprint,
        "declared_trust_class": link.declared_trust_class.value,
    }


def row_to_link(row: Mapping[str, Any]) -> SymbolLink:
    version = row.get("schema_version")
    if version != SCHEMA_VERSION:
        raise UnsupportedSchemaError(
            f"stored association declares schema_version {version!r}, but this "
            f"build understands only {SCHEMA_VERSION}"
        )
    return SymbolLink(
        source_id=row["source_id"],
        feed_item_id=row["feed_item_id"],
        symbol=row["symbol"],
        association=SymbolAssociation(row["association"]),
        retrieved_at=_parse_stamp(row["retrieved_at"]),
        config_fingerprint=row["config_fingerprint"],
        declared_trust_class=DeclaredTrustClass(
            row.get("declared_trust_class", DeclaredTrustClass.COMMUNITY_FEED.value)
        ),
    )


class FeedStore:
    """Append-only JSONL item and association storage for one root."""

    def __init__(self, root: str | Path = DEFAULT_FEEDS_ROOT) -> None:
        self._root = Path(root)

    def source_dir(self, source_id: str) -> Path:
        return self._root / require_source_id(source_id)

    def documents_path(self, source_id: str) -> Path:
        return self.source_dir(source_id) / DOCUMENTS_FILE

    def associations_path(self, source_id: str) -> Path:
        return self.source_dir(source_id) / ASSOCIATIONS_FILE

    # -- reading ---------------------------------------------------------

    def _read_rows(
        self, path: Path, on_corruption: OnCorruption
    ) -> tuple[list[dict[str, Any]], StoreIntegrityReport]:
        if not path.is_file():
            return [], StoreIntegrityReport(())

        rows: list[dict[str, Any]] = []
        corrupt: list[CorruptLine] = []
        offset = 0
        raw_lines = path.read_bytes().split(b"\n")
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
            except Exception as exc:
                corrupt.append(
                    CorruptLine(str(path), index, line_offset,
                                CorruptionKind.CORRUPT_INTERIOR, str(exc)[:200])
                )

        total = len(raw_lines)
        corrupt = [
            CorruptLine(
                entry.path, entry.line_number, entry.byte_offset,
                CorruptionKind.CORRUPT_TAIL if entry.line_number == total
                else CorruptionKind.CORRUPT_INTERIOR,
                entry.detail,
            )
            for entry in corrupt
        ]
        report = StoreIntegrityReport(tuple(corrupt))
        if corrupt and on_corruption is OnCorruption.RAISE:
            raise FeedStoreCorruption(report)
        return rows, report

    def read_items(
        self, source_id: str, *, on_corruption: OnCorruption = OnCorruption.RAISE
    ) -> tuple[tuple[FeedItem, ...], StoreIntegrityReport]:
        rows, report = self._read_rows(self.documents_path(source_id), on_corruption)
        return tuple(row_to_item(row) for row in rows), report

    def read_links(
        self, source_id: str, *, on_corruption: OnCorruption = OnCorruption.RAISE
    ) -> tuple[tuple[SymbolLink, ...], StoreIntegrityReport]:
        rows, report = self._read_rows(self.associations_path(source_id), on_corruption)
        return tuple(row_to_link(row) for row in rows), report

    def latest_items(
        self, source_id: str, *, as_of: datetime | None = None,
        on_corruption: OnCorruption = OnCorruption.RAISE,
    ) -> tuple[tuple[FeedItem, ...], StoreIntegrityReport]:
        """Highest revision per item, optionally as this system knew it at ``as_of``.

        ``as_of`` filters on ``retrieved_at``: it replays our own observation
        history, which is what makes "what had we seen by T?" answerable.
        """
        items, report = self.read_items(source_id, on_corruption=on_corruption)
        latest: dict[tuple[str, str], FeedItem] = {}
        for item in items:
            if as_of is not None and item.retrieved_at > as_of:
                continue
            current = latest.get(item.item_key)
            if current is None or item.revision > current.revision:
                latest[item.item_key] = item
        return tuple(latest.values()), report

    def health(self, source_id: str) -> StoreIntegrityReport:
        """Integrity of both files, without raising.

        The application calls this before ingesting: a damaged store must stop
        ingestion and freeze the checkpoint rather than have new records appended
        on top of bytes nobody can read.
        """
        _, documents = self._read_rows(
            self.documents_path(source_id), OnCorruption.REPORT
        )
        _, associations = self._read_rows(
            self.associations_path(source_id), OnCorruption.REPORT
        )
        return StoreIntegrityReport(documents.corrupt_lines + associations.corrupt_lines)

    # -- writing ---------------------------------------------------------

    def _append(self, path: Path, row: Mapping[str, Any]) -> None:
        """Append one complete line, then flush and fsync.

        No claim is made that this is atomic on every filesystem; the safety net
        is detection on the next read, not a guarantee here.
        """
        payload = json.dumps(row, ensure_ascii=False, sort_keys=True)
        if "\n" in payload or "\r" in payload:  # pragma: no cover - defensive
            raise StorageError("serialized record contains a newline")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(payload + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def write_item(self, item: FeedItem) -> WriteResult:
        """Classify ``item`` against what is stored, and append if it is new.

        The store's own identity and content hash decide this -- never a
        remembered set of ids. An item seen on an earlier refresh is examined
        again every time, which is what lets a later correction be recognised as
        a revision instead of skipped.
        """
        source_id = item.source_id
        stored, _ = self.latest_items(source_id)
        existing = {record.item_key: record for record in stored}
        current = existing.get(item.item_key)

        if current is None:
            self._append(self.documents_path(source_id), item_to_row(item))
            return WriteResult(ItemOutcome.ACCEPTED, item)

        if url_host(current.canonical_url) != url_host(item.canonical_url):
            # Publishers restructure paths while editing; they do not move host
            # under the same provider id. A host change means the id now names
            # something else, and appending would rewrite an unrelated history.
            return WriteResult(
                ItemOutcome.ID_REUSE_CONFLICT,
                current,
                f"identifier {item.feed_item_id!r} already refers to an item on "
                f"{url_host(current.canonical_url)!r}, not {url_host(item.canonical_url)!r}",
            )

        if current.content_hash and current.content_hash == item.content_hash:
            return WriteResult(ItemOutcome.DUPLICATE, current)

        revised = _with_revision(item, current.revision + 1)
        self._append(self.documents_path(source_id), item_to_row(revised))
        return WriteResult(ItemOutcome.REVISION, revised)

    def write_link(self, link: SymbolLink) -> bool:
        """Append an association unless this exact observation is already stored.

        Keyed on the configuration fingerprint as well as item and symbol, so a
        later configuration genuinely produces a new observation rather than
        being mistaken for a repeat of the old one.
        """
        stored, _ = self.read_links(link.source_id)
        if any(existing.link_key == link.link_key for existing in stored):
            return False
        self._append(self.associations_path(link.source_id), link_to_row(link))
        return True


def _with_revision(item: FeedItem, revision: int) -> FeedItem:
    """A copy at a new revision number, keeping *this* observation's values.

    ``replace`` re-runs validation and copies the newly fetched timestamps
    rather than inheriting the previous revision's, so a publisher that
    silently restates a time leaves both values on the record.
    """
    from dataclasses import replace

    return replace(item, revision=revision)


__all__ = [
    "SCHEMA_VERSION",
    "DEFAULT_FEEDS_ROOT",
    "DOCUMENTS_FILE",
    "ASSOCIATIONS_FILE",
    "StorageError",
    "UnsupportedSchemaError",
    "CorruptionKind",
    "OnCorruption",
    "CorruptLine",
    "StoreIntegrityReport",
    "FeedStoreCorruption",
    "WriteResult",
    "FeedStore",
    "item_to_row",
    "row_to_item",
    "link_to_row",
    "row_to_link",
]
