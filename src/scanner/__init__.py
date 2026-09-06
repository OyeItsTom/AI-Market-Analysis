"""Scanning a configured universe of symbols for research candidates.

    universe config -> normalized universe -> per-symbol research
                    -> eligibility -> structural category -> ordered rows

This package **orders research attention**; it does not rate securities. There
is no score, no confidence, no probability and no recommendation anywhere in it,
because the assessment layer it builds on refuses to produce one.

Stages A-D are implemented here: models, universe identity, the configuration
adapter, and the eligibility and ranking rules. Orchestration over a real
provider is deliberately absent -- it belongs to the application layer.

Boundaries that are structural rather than conventional:

* the pure modules import no filesystem, no network and no UI, so a scan result
  cannot be built from anything but data handed to it;
* :mod:`src.scanner.config` is the only module that reads a file, and it never
  writes one;
* nothing here imports the news, feeds or portfolio packages, so a scan result
  has no name in scope through which it could reach an order.
"""

from .config import (
    CONFIG_SCHEMA_VERSION,
    UNCONFIGURED_MESSAGE,
    ConfigError,
    load_configuration,
    parse_configuration,
)
from .eligibility import eligibility_for, error_for
from .models import (
    ASSESSABLE_CATEGORIES,
    CATEGORY_ORDER,
    MAX_ERROR_DETAIL_CHARS,
    MAX_SYMBOLS_PER_UNIVERSE,
    MAX_UNIVERSE_CONFIG_BYTES,
    MAX_UNIVERSES,
    EligibilityStatus,
    MarketScanSnapshot,
    ScanCounters,
    ScanErrorCode,
    ScannerError,
    ScanStatus,
    StructuralCategory,
    SymbolScanResult,
    UniverseConfiguration,
    UniverseDefinition,
    UniverseLoadReport,
    UniverseSourceKind,
    status_for,
)
from .ranking import category_for, order_results, ordered_rows, rank_key
from .universe import build_universe, normalize_symbol, normalize_symbols, universe_fingerprint

__all__ = [
    "ScannerError", "ConfigError",
    "UniverseSourceKind", "UniverseDefinition", "UniverseLoadReport",
    "UniverseConfiguration",
    "EligibilityStatus", "StructuralCategory", "ScanStatus", "ScanErrorCode",
    "ScanCounters", "SymbolScanResult", "MarketScanSnapshot",
    "CATEGORY_ORDER", "ASSESSABLE_CATEGORIES", "status_for",
    "MAX_SYMBOLS_PER_UNIVERSE", "MAX_UNIVERSES", "MAX_UNIVERSE_CONFIG_BYTES",
    "MAX_ERROR_DETAIL_CHARS", "CONFIG_SCHEMA_VERSION", "UNCONFIGURED_MESSAGE",
    "load_configuration", "parse_configuration",
    "normalize_symbol", "normalize_symbols", "universe_fingerprint", "build_universe",
    "eligibility_for", "error_for",
    "category_for", "rank_key", "order_results", "ordered_rows",
]
