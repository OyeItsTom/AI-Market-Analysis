"""Orchestration for external feeds: refresh, persist, query, snapshot.

    configuration -> each feed independently -> store -> checkpoint -> FeedSnapshot

Three ordering rules do most of the work here, and each exists because getting
it backwards produces a quiet, plausible-looking lie.

**Feeds are independent.** One feed timing out must not discard another's
records. Each is fetched, normalized and persisted alone, with its own outcome,
and a refresh where some feeds failed reports ``PARTIAL`` -- never success.

**The store is durable before the checkpoint moves.** Records are appended and
fsynced *first*; only then is the ETag written. Reversed, a crash between the
two would leave a checkpoint claiming we hold entries we never stored, and the
next refresh would receive ``304`` and skip them forever. In the order used
here the worst case is re-fetching a document we already have, which the store
recognises as a duplicate.

**Store integrity dominates the checkpoint.** If a feed's store is damaged,
ingestion is refused and the checkpoint is left exactly as it was, so nothing
is appended on top of bytes nobody can read and no evidence is destroyed.

This module imports no UI framework, and it reaches neither research nor paper
state: a :class:`FeedSnapshot` is a separate object from a ``ResearchSnapshot``
and from a ``NewsSnapshot``, so nothing here can be mistaken for an input to an
assessment or an order.
"""

from __future__ import annotations

from dataclasses import dataclass, fields as dataclass_fields
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Sequence

from src.feeds.checkpoint import Checkpoint, CheckpointStore
from src.feeds.config import FeedConfiguration, FeedDefinition, load_configuration
from src.feeds.models import (
    AvailabilityBasis,
    DeclaredTrustClass,
    FeedError,
    FeedItem,
    QueryMode,
    SymbolLink,
    TrustMode,
    require_symbol,
)
from src.feeds.source import (
    IngestionCounters,
    ItemOutcome,
    SourceError,
    SourceOutcome,
    SourceResult,
)
from src.feeds.sources import normalize_feed
from src.feeds.store import (
    DEFAULT_FEEDS_ROOT,
    CorruptionKind,
    CorruptLine,
    FeedStore,
    OnCorruption,
    StorageError,
    StoreIntegrityReport,
)
from src.feeds.transport import (
    NotModified,
    PayloadTooLarge,
    RateLimited,
    TransportError,
    fetch_feed,
)
from src.feeds.validation import UnsafeDestination
from src.feeds.xmlsafe import UnsupportedFormat, XmlSafetyError, parse_feed_bytes

Clock = Callable[[], datetime]

#: Shown when nothing is configured. Phrased as a state, not a failure: a fresh
#: checkout has no feeds, and that is the correct and expected condition.
UNCONFIGURED_MESSAGE = (
    "No external feeds are configured. Copy config/external_feeds.example.json "
    "to config/external_feeds.local.json and add the feeds you want to follow. "
    "Only feeds listed in that file are ever fetched."
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RefreshStatus(str, Enum):
    """How a whole refresh went, across every configured feed."""

    ALL_OK = "all_ok"
    PARTIAL = "partial"
    ALL_FAILED = "all_failed"
    NOTHING_CONFIGURED = "nothing_configured"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class FeedSnapshot:
    """One coherent view of everything the configured feeds have supplied.

    Deliberately a separate type from ``NewsSnapshot`` and ``ResearchSnapshot``.
    Sharing one would suggest these records feed research, which they do not:
    no field here reaches a hypothesis, an assessment or a paper action.
    """

    built_at: datetime
    items: tuple[FeedItem, ...]
    links: tuple[SymbolLink, ...]
    source_results: tuple[SourceResult, ...]
    status: RefreshStatus
    definitions: tuple[FeedDefinition, ...] = ()
    integrity: StoreIntegrityReport | None = None
    symbol: str | None = None

    def __post_init__(self) -> None:
        if self.built_at.tzinfo is None or self.built_at.utcoffset() is None:
            raise FeedError("built_at must be timezone-aware")
        for name in ("items", "links", "source_results", "definitions"):
            object.__setattr__(self, name, tuple(getattr(self, name)))

    @property
    def counters(self) -> IngestionCounters:
        """Every feed's counters summed.

        Summed by reflecting over the declared fields rather than naming them,
        so a counter added later cannot be silently dropped from the total.
        """
        totals = {f.name: 0 for f in dataclass_fields(IngestionCounters)}
        for result in self.source_results:
            for name in totals:
                totals[name] += getattr(result.counters, name)
        return IngestionCounters(**totals)

    @property
    def is_configured(self) -> bool:
        return bool(self.definitions)

    @property
    def has_integrity_warning(self) -> bool:
        return self.integrity is not None and not self.integrity.is_clean

    def definition_for(self, source_id: str) -> FeedDefinition | None:
        for definition in self.definitions:
            if definition.source_id == source_id:
                return definition
        return None

    def trust_class_for(self, item: FeedItem) -> DeclaredTrustClass:
        """The trust class recorded *with the item*, not today's configuration.

        Reading it from the item is the point: re-labelling a feed "official"
        today must not retroactively make yesterday's entries look verified.
        """
        return item.declared_trust_class

    def symbols_for(self, item: FeedItem) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    link.symbol
                    for link in self.links
                    if (link.source_id, link.feed_item_id) == item.item_key
                }
            )
        )


# -- ordering and causal filtering ---------------------------------------


def _sort_key(item: FeedItem) -> tuple[float, str, str]:
    """Newest first, ties broken deterministically by identity.

    ``declared_trust_class`` is deliberately absent. Sorting "official" feeds
    to the top would let a label the user typed into a config file reorder
    time itself. Trust is a filter and a caption; never a clock.
    """
    when = item.available_from or item.retrieved_at
    return (-when.timestamp(), item.source_id, item.feed_item_id)


def order_items(items: Sequence[FeedItem]) -> tuple[FeedItem, ...]:
    return tuple(sorted(items, key=_sort_key))


def _visible_at(
    item: FeedItem, *, as_of: datetime, mode: QueryMode, trust: TrustMode
) -> bool:
    """Whether ``item`` may be shown for a point in time."""
    if mode is QueryMode.SOURCE_TIME:
        source_time = item.source_time
        return source_time is not None and source_time <= as_of

    # STRICT_CAUSAL from here.
    if item.availability_basis is AvailabilityBasis.UNKNOWN or item.available_from is None:
        # Nothing defensible is known, so it is excluded rather than guessed in.
        return False
    if trust is TrustMode.SYSTEM_OBSERVED:
        # The later of what the source claims and when we actually saw it: an
        # entry stamped last year but first retrieved today was not knowable to
        # *this system* before today.
        return max(item.available_from, item.retrieved_at) <= as_of
    return item.available_from <= as_of


def filter_items(
    items: Sequence[FeedItem],
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    source_id: str | None = None,
    trust_class: DeclaredTrustClass | None = None,
    as_of: datetime | None = None,
    mode: QueryMode = QueryMode.STRICT_CAUSAL,
    trust: TrustMode = TrustMode.SOURCE_ASSERTED,
) -> tuple[FeedItem, ...]:
    """Apply source, trust, window and causal filters, then order chronologically."""
    selected = []
    for item in items:
        if source_id is not None and item.source_id != source_id:
            continue
        if trust_class is not None and item.declared_trust_class is not trust_class:
            continue
        when = item.available_from or item.retrieved_at
        if start is not None and when < start:
            continue
        if end is not None and when > end:
            continue
        if as_of is not None and not _visible_at(item, as_of=as_of, mode=mode, trust=trust):
            continue
        selected.append(item)
    return order_items(selected)


# -- the service ---------------------------------------------------------


class FeedService:
    """Manual-refresh orchestration over the configured feeds.

    Nothing here starts a thread, a timer or a scheduler: a refresh happens
    because a human pressed a button. ``fetch`` is injected so the whole policy
    -- ordering, isolation, checkpointing, corruption handling -- is testable
    without a network.
    """

    def __init__(
        self,
        configuration: FeedConfiguration,
        store: FeedStore,
        checkpoints: CheckpointStore,
        *,
        fetch: Callable[..., object] = fetch_feed,
        now: Clock = _utc_now,
    ) -> None:
        self._configuration = configuration
        self._store = store
        self._checkpoints = checkpoints
        self._fetch = fetch
        self._now = now

    @property
    def configuration(self) -> FeedConfiguration:
        return self._configuration

    # -- refresh ---------------------------------------------------------

    def refresh(self, source_ids: Sequence[str] | None = None) -> FeedSnapshot:
        """Refresh every enabled feed (or the named ones) and build a snapshot."""
        built_at = self._now()
        definitions = self._configuration.sources
        if source_ids is not None:
            wanted = set(source_ids)
            definitions = tuple(d for d in definitions if d.source_id in wanted)

        results: list[SourceResult] = []
        for definition in sorted(definitions, key=lambda d: d.source_id):
            if not definition.enabled:
                results.append(
                    SourceResult(
                        definition.source_id,
                        SourceOutcome.UNCONFIGURED,
                        detail="This feed is switched off in configuration.",
                    )
                )
                continue
            results.append(self._refresh_one(definition, built_at))

        items, links, integrity = self._load()
        return FeedSnapshot(
            built_at=built_at,
            items=items,
            links=links,
            source_results=tuple(results),
            status=_overall_status(results, self._configuration),
            definitions=self._configuration.sources,
            integrity=integrity,
        )

    def _refresh_one(self, definition: FeedDefinition, now: datetime) -> SourceResult:
        """One feed's whole refresh, isolated from every other feed."""
        source_id = definition.source_id

        # Integrity first. A damaged store must stop ingestion before anything
        # is appended on top of unreadable bytes, and before the checkpoint is
        # allowed to move past entries we may not actually hold.
        try:
            health = self._store.health(source_id)
        except StorageError as exc:
            return SourceResult(
                source_id, SourceOutcome.STORAGE_CORRUPTION, detail=str(exc)[:300]
            )
        if not health.is_clean:
            return SourceResult(
                source_id,
                SourceOutcome.STORAGE_CORRUPTION,
                detail=(
                    f"{health.describe()} Ingestion is refused and the stored "
                    "transport state is left untouched; nothing has been repaired "
                    "or deleted."
                ),
            )

        loaded = self._checkpoints.load(
            source_id, endpoint_fingerprint=definition.endpoint_fingerprint
        )
        etag, last_modified = (
            loaded.checkpoint.validators_for(definition.endpoint_fingerprint)
            if loaded.checkpoint
            else (None, None)
        )

        try:
            fetched = self._fetch(definition.url, etag=etag, last_modified=last_modified)
        except NotModified as unchanged:
            # The source says its representation is unchanged. That is a fact
            # about the document, not about the world, and it stores nothing.
            self._save_checkpoint(definition, unchanged.etag, unchanged.last_modified, now)
            return SourceResult(
                source_id,
                SourceOutcome.NOT_MODIFIED,
                detail="The source reports nothing changed since the last refresh.",
            )
        except UnsafeDestination as exc:
            return SourceResult(source_id, SourceOutcome.UNSAFE_ENDPOINT, detail=str(exc)[:300])
        except PayloadTooLarge as exc:
            return SourceResult(source_id, SourceOutcome.PAYLOAD_TOO_LARGE, detail=str(exc)[:300])
        except RateLimited as exc:
            return SourceResult(source_id, SourceOutcome.RATE_LIMITED, detail=str(exc)[:300])
        except SourceError as exc:
            return SourceResult(source_id, exc.outcome, detail=exc.message[:300])
        except TransportError as exc:
            return SourceResult(source_id, SourceOutcome.FAILED, detail=str(exc)[:300])
        except Exception as exc:  # one feed must not take the refresh down
            return SourceResult(
                source_id, SourceOutcome.FAILED, detail=f"{type(exc).__name__}: {exc}"[:300]
            )

        try:
            parsed = parse_feed_bytes(fetched.body, expected=definition.feed_format)
        except (UnsupportedFormat, XmlSafetyError) as exc:
            return SourceResult(
                source_id, SourceOutcome.UNSUPPORTED_SOURCE_FORMAT, detail=str(exc)[:300]
            )
        except Exception as exc:
            return SourceResult(
                source_id, SourceOutcome.FAILED, detail=f"{type(exc).__name__}: {exc}"[:300]
            )

        entries, rejected = normalize_feed(parsed, definition, now=now)
        counters = IngestionCounters().with_entries(
            seen=parsed.entries_seen,
            processed=parsed.entries_processed,
            truncated=parsed.entries_truncated,
        )
        # A refused entry is counted as rejected rather than dropped silently:
        # "we saw 40 and stored 38" is a materially different report from
        # "we stored 38".
        for _ in range(rejected):
            counters = counters.plus(ItemOutcome.REJECTED)

        stored_cleanly = True
        for entry in entries:
            # Each entry independently; one failure never voids its siblings.
            try:
                result = self._store.write_item(entry.item)
                counters = counters.plus(result.outcome)
                # Links are written for a duplicate too: the item is unchanged,
                # but "it is also configured for this symbol now" is a new fact.
                # Only a conflicted identity contributes none.
                if result.outcome is not ItemOutcome.ID_REUSE_CONFLICT:
                    for link in entry.links:
                        if self._store.write_link(link):
                            counters = counters.with_association()
            except Exception:
                stored_cleanly = False
                counters = counters.plus(ItemOutcome.REJECTED)

        # Only now, with every record appended and fsynced, may the checkpoint
        # advance. A checkpoint saved before this point could promise a 304 for
        # entries that a crash prevented us from ever writing.
        if stored_cleanly:
            self._save_checkpoint(definition, fetched.etag, fetched.last_modified, now)
        else:
            # Entries were fetched and parsed but could not be written. The
            # counters already say so, but the outcome must too: reporting a
            # refresh that stored nothing as SUCCESS is exactly the quiet lie
            # this layer exists to avoid. Checked before truncation and
            # checkpoint warnings because a failed write is the graver fact.
            return SourceResult(
                source_id,
                SourceOutcome.FAILED,
                counters,
                detail=(
                    "Entries were fetched but could not be written to the store, "
                    "so nothing was recorded and the stored transport state was "
                    "left untouched; the next refresh will fetch unconditionally."
                ),
            )

        if parsed.entries_truncated:
            return SourceResult(
                source_id,
                SourceOutcome.TRUNCATED,
                counters,
                detail=(
                    f"The feed offered {parsed.entries_seen} entries; "
                    f"{parsed.entries_processed} were processed and "
                    f"{parsed.entries_truncated} were not read."
                ),
            )
        if loaded.warning:
            return SourceResult(
                source_id, SourceOutcome.CHECKPOINT_WARNING, counters, detail=loaded.warning
            )
        if not entries:
            return SourceResult(
                source_id,
                SourceOutcome.NO_ITEMS,
                counters,
                detail="The feed was readable and contained no usable entries.",
            )
        return SourceResult(source_id, SourceOutcome.SUCCESS, counters)

    def _save_checkpoint(
        self,
        definition: FeedDefinition,
        etag: str | None,
        last_modified: str | None,
        now: datetime,
    ) -> None:
        """Persist transport validators. Never fatal: this is a cache, not a record."""
        try:
            self._checkpoints.save(
                Checkpoint(
                    source_id=definition.source_id,
                    endpoint_fingerprint=definition.endpoint_fingerprint,
                    etag=etag,
                    last_modified=last_modified,
                    last_success_at=now,
                )
            )
        except Exception:
            # Losing a checkpoint costs one redundant fetch next time. Failing
            # a refresh over it would cost the records we just stored.
            pass

    # -- query -----------------------------------------------------------

    def _load(
        self,
    ) -> tuple[tuple[FeedItem, ...], tuple[SymbolLink, ...], StoreIntegrityReport | None]:
        """Read every configured feed's store, tolerating (and reporting) damage."""
        items: list[FeedItem] = []
        links: list[SymbolLink] = []
        corrupt: list[CorruptLine] = []
        for definition in sorted(self._configuration.sources, key=lambda d: d.source_id):
            source_id = definition.source_id
            # A row this build cannot decode -- a future schema_version, say --
            # is an integrity finding to report, not a reason to fail the whole
            # read and lose the feeds that are perfectly readable.
            try:
                stored, report = self._store.latest_items(
                    source_id, on_corruption=OnCorruption.REPORT
                )
                corrupt.extend(report.corrupt_lines)
            except StorageError as exc:
                corrupt.append(_unreadable(self._store.documents_path(source_id), exc))
                stored = ()
            try:
                stored_links, link_report = self._store.read_links(
                    source_id, on_corruption=OnCorruption.REPORT
                )
                corrupt.extend(link_report.corrupt_lines)
            except StorageError as exc:
                corrupt.append(_unreadable(self._store.associations_path(source_id), exc))
                stored_links = ()
            items.extend(stored)
            links.extend(stored_links)

        integrity = StoreIntegrityReport(tuple(corrupt)) if corrupt else None
        return order_items(items), tuple(links), integrity

    def snapshot(self, *, symbol: str | None = None) -> FeedSnapshot:
        """Everything currently stored, without fetching anything."""
        items, links, integrity = self._load()
        if symbol is not None:
            symbol = require_symbol(symbol)
            keys = {
                (link.source_id, link.feed_item_id)
                for link in links
                if link.symbol == symbol
            }
            items = tuple(item for item in items if item.item_key in keys)
            links = tuple(link for link in links if link.symbol == symbol)
        return FeedSnapshot(
            built_at=self._now(),
            items=items,
            links=links,
            source_results=(),
            status=(
                RefreshStatus.NOTHING_CONFIGURED
                if not self._configuration.sources
                else RefreshStatus.ALL_OK
            ),
            definitions=self._configuration.sources,
            integrity=integrity,
            symbol=symbol,
        )

    def items_for_symbol(
        self,
        symbol: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        source_id: str | None = None,
        trust_class: DeclaredTrustClass | None = None,
        as_of: datetime | None = None,
        mode: QueryMode = QueryMode.STRICT_CAUSAL,
        trust: TrustMode = TrustMode.SOURCE_ASSERTED,
    ) -> tuple[FeedItem, ...]:
        """Items linked to ``symbol`` because a feed was configured for it."""
        snapshot = self.snapshot(symbol=symbol)
        return filter_items(
            snapshot.items, start=start, end=end, source_id=source_id,
            trust_class=trust_class, as_of=as_of, mode=mode, trust=trust,
        )

    def latest_items(self, *, limit: int = 50, **kwargs) -> tuple[FeedItem, ...]:
        items, _, _ = self._load()
        return filter_items(items, **kwargs)[:limit]


def _unreadable(path: Path, exc: Exception) -> CorruptLine:
    """Describe a file this build cannot decode as an integrity finding."""
    return CorruptLine(
        path=str(path),
        line_number=0,
        byte_offset=0,
        kind=CorruptionKind.CORRUPT_INTERIOR,
        detail=f"{type(exc).__name__}: {exc}"[:200],
    )


def _overall_status(
    results: Sequence[SourceResult], configuration: FeedConfiguration
) -> RefreshStatus:
    if not configuration.sources:
        return RefreshStatus.NOTHING_CONFIGURED
    # A feed the user switched off was not attempted, so it is neither a success
    # nor a failure. Counting it as a failure would report a perfectly good
    # refresh as PARTIAL and teach the user to ignore that signal.
    results = [r for r in results if r.outcome is not SourceOutcome.UNCONFIGURED]
    if not results:
        return RefreshStatus.ALL_OK
    healthy = [result for result in results if result.is_healthy]
    if len(healthy) == len(results):
        return RefreshStatus.ALL_OK
    if healthy:
        return RefreshStatus.PARTIAL
    return RefreshStatus.ALL_FAILED


def build_service(
    *,
    config_path: str | Path | None = None,
    store_root: str | Path = DEFAULT_FEEDS_ROOT,
    fetch: Callable[..., object] = fetch_feed,
    now: Clock = _utc_now,
) -> FeedService:
    """Assemble the service from local configuration.

    An absent configuration file is not an error: it yields a service with no
    feeds, and the panel says so plainly.
    """
    configuration = load_configuration(config_path)
    root = Path(store_root)
    return FeedService(
        configuration,
        FeedStore(root),
        CheckpointStore(root),
        fetch=fetch,
        now=now,
    )


__all__ = [
    "UNCONFIGURED_MESSAGE",
    "RefreshStatus",
    "FeedSnapshot",
    "FeedService",
    "order_items",
    "filter_items",
    "build_service",
]
