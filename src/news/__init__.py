"""External information: official filings and reported news.

    source adapter -> normalize -> validate -> identity -> store -> query

This package **records**; it does not interpret. There is no sentiment, no
relevance score, no classifier and no direction anywhere in it: Phase 8 answers
"what did a source publish, and how well do we know when?" and stops there.

Two boundaries are structural rather than conventional. This package imports
nothing from ``src.strategies``, ``src.assessments`` or ``src.portfolio``, so no
headline can reach a research state or a paper action -- there is no name in
scope to reach them with. And it imports no UI framework, so everything here is
testable headlessly.

The hardest thing it does is refuse to overstate what it knows: EDGAR proves a
filing was accepted, not that it was disseminated; Yahoo proves a story came
back for a query, not that it is about that company. Both distinctions are
carried in the data rather than left to a reader's good sense.

See ``docs/news.md`` and ``docs/adr/0006-news-and-announcements.md``.
"""

from .cik_map import CikMap, CikMapError, CikMapStore, load_cik_map
from .config import SecContact, read_sec_contact, validate_user_agent
from .identity import canonical_bytes, content_hash
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
from .source import (
    FetchedRecord,
    IngestionCounters,
    ItemOutcome,
    NewsSource,
    SourceError,
    SourceOutcome,
    SourceResult,
)
from .sources import EdgarFilingsSource, YahooNewsSource
from .store import (
    NewsStore,
    NewsStoreCorruption,
    OnCorruption,
    StorageError,
    StoreIntegrityReport,
    UnsupportedSchemaError,
)
from .validation import UrlValidationError, validate_url

__all__ = [
    "NewsError",
    "NewsItem",
    "OfficialFiling",
    "SymbolLink",
    "Document",
    "SourceClass",
    "SymbolAssociation",
    "AvailabilityBasis",
    "EventType",
    "SourceOutcome",
    "ItemOutcome",
    "SourceError",
    "SourceResult",
    "IngestionCounters",
    "FetchedRecord",
    "NewsSource",
    "EdgarFilingsSource",
    "YahooNewsSource",
    "NewsStore",
    "OnCorruption",
    "StorageError",
    "StoreIntegrityReport",
    "NewsStoreCorruption",
    "UnsupportedSchemaError",
    "CikMap",
    "CikMapStore",
    "CikMapError",
    "load_cik_map",
    "SecContact",
    "read_sec_contact",
    "validate_user_agent",
    "validate_url",
    "UrlValidationError",
    "canonical_bytes",
    "content_hash",
]
