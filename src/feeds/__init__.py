"""Public RSS and Atom feeds: configured, fetched manually, recorded honestly.

    configured feed -> safe fetch -> safe parse -> normalize -> identity -> store

This package **records**; it does not interpret. There is no sentiment, no
relevance score, no classifier and no truth judgement anywhere in it.

Three boundaries are structural rather than conventional:

* it imports nothing from the news, strategies, assessments or portfolio
  packages, so no feed entry has a route to a research state or a paper action
  -- there is no name in scope to reach them with;
* it imports no UI framework, so everything is testable headlessly;
* it fetches only URLs written in local configuration, never a link found
  inside a feed and never anything typed into the dashboard.

The hardest thing it does is decline to overstate what a feed told it. A user
calling a source "official" is a configuration assertion, not a verification. An
Atom ``updated`` is an update time, not a publication time. An entry vanishing
from a feed window is not a deletion. Each of those distinctions is carried in
the data rather than left to the reader's good sense.

See ``docs/feeds.md`` and ``docs/adr/0007-external-feeds.md``.
"""

from .checkpoint import Checkpoint, CheckpointLoad, CheckpointStore
from .config import (
    ConfigError,
    FeedConfiguration,
    FeedDefinition,
    load_configuration,
    parse_configuration,
)
from .identity import canonical_bytes, config_fingerprint, item_content_hash
from .models import (
    AvailabilityBasis,
    DeclaredTrustClass,
    FeedError,
    FeedFormat,
    FeedItem,
    QueryMode,
    SymbolAssociation,
    SymbolLink,
    TrustBasis,
    TrustMode,
)
from .source import (
    IngestionCounters,
    ItemOutcome,
    SourceError,
    SourceOutcome,
    SourceResult,
)
from .sources import NormalizedEntry, normalize_feed
from .store import (
    FeedStore,
    FeedStoreCorruption,
    OnCorruption,
    StorageError,
    StoreIntegrityReport,
    UnsupportedSchemaError,
)
from .transport import (
    FetchResult,
    NotModified,
    PayloadTooLarge,
    RateLimited,
    RedirectRefused,
    TransportError,
    fetch_feed,
)
from .validation import UnsafeDestination, UrlValidationError, is_safe_display_url, validate_url
from .xmlsafe import ParsedFeed, UnsupportedFormat, XmlSafetyError, parse_feed_bytes

__all__ = [
    "FeedError",
    "FeedFormat",
    "FeedItem",
    "SymbolLink",
    "DeclaredTrustClass",
    "TrustBasis",
    "SymbolAssociation",
    "AvailabilityBasis",
    "QueryMode",
    "TrustMode",
    "FeedDefinition",
    "FeedConfiguration",
    "ConfigError",
    "load_configuration",
    "parse_configuration",
    "SourceOutcome",
    "ItemOutcome",
    "SourceError",
    "SourceResult",
    "IngestionCounters",
    "FeedStore",
    "OnCorruption",
    "StorageError",
    "StoreIntegrityReport",
    "FeedStoreCorruption",
    "UnsupportedSchemaError",
    "Checkpoint",
    "CheckpointLoad",
    "CheckpointStore",
    "fetch_feed",
    "FetchResult",
    "NotModified",
    "TransportError",
    "PayloadTooLarge",
    "RedirectRefused",
    "RateLimited",
    "parse_feed_bytes",
    "ParsedFeed",
    "XmlSafetyError",
    "UnsupportedFormat",
    "normalize_feed",
    "NormalizedEntry",
    "validate_url",
    "is_safe_display_url",
    "UrlValidationError",
    "UnsafeDestination",
    "canonical_bytes",
    "config_fingerprint",
    "item_content_hash",
]
