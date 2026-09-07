"""Turning a written list of symbols into a dated, attributed universe.

Everything here is pure: no file is opened and no network is touched. The
adapter in :mod:`src.scanner.config` does the reading; this module decides what
the read values *mean*.

Symbol normalization deliberately follows
:meth:`~src.data.provider.MarketDataProvider._normalize_symbol` -- strip,
upper-case, refuse anything that is not a non-empty string -- rather than
inventing a second convention. A scanner that normalized differently from the
provider it calls would ask for one symbol and record another.

Two rules are added on top, because a *list* needs them and a single argument
does not: entries that collapse to the same symbol are merged, and the result is
sorted. Both make a universe's identity independent of how the file was typed.

Exchange suffixes (``.L``, ``.TO``) pass through untouched. yfinance uses them,
and rewriting them would silently break valid symbols.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any, Iterable, Mapping, Sequence

from .models import (
    MAX_SYMBOL,
    MAX_SYMBOLS_PER_UNIVERSE,
    ScannerError,
    UniverseDefinition,
    UniverseSourceKind,
    require_universe_id,
)

#: Bumped when the meaning of a fingerprint input changes, so digests taken
#: under different rules can never silently compare equal.
FINGERPRINT_VERSION = 1


def normalize_symbol(value: object) -> str:
    """One symbol, normalized the way the provider will normalize it.

    Embedded whitespace and control characters are refused rather than stripped:
    ``"AA PL"`` is not a typo this layer can safely correct, and guessing would
    send a request for a symbol the user never wrote.
    """
    if not isinstance(value, str):
        raise ScannerError(f"symbol must be a str, got {type(value).__name__}")
    symbol = value.strip().upper()
    if not symbol:
        raise ScannerError("symbol must not be empty")
    if len(symbol) > MAX_SYMBOL:
        raise ScannerError(f"symbol {value!r} exceeds {MAX_SYMBOL} characters")
    if any(character.isspace() for character in symbol):
        raise ScannerError(f"symbol {value!r} contains embedded whitespace")
    if any(ord(character) < 32 or ord(character) == 127 for character in symbol):
        raise ScannerError(f"symbol {value!r} contains control characters")
    return symbol


def normalize_symbols(values: Iterable[object]) -> tuple[tuple[str, ...], int]:
    """Normalize, de-duplicate and sort. Returns the symbols and how many
    duplicates were removed.

    The duplicate count is returned rather than discarded so the loader can
    report it: silently collapsing ``AAPL`` and ``aapl`` would leave the user
    wondering why their twelve-symbol universe scanned eleven.
    """
    seen: dict[str, None] = {}
    duplicates = 0
    for value in values:
        symbol = normalize_symbol(value)
        if symbol in seen:
            duplicates += 1
            continue
        seen[symbol] = None
    if not seen:
        raise ScannerError("a universe must name at least one symbol")
    if len(seen) > MAX_SYMBOLS_PER_UNIVERSE:
        raise ScannerError(
            f"at most {MAX_SYMBOLS_PER_UNIVERSE} symbols per universe, got {len(seen)}"
        )
    return tuple(sorted(seen)), duplicates


def canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    """Stable JSON encoding for hashing.

    ``sort_keys`` makes key order irrelevant, ``ensure_ascii`` keeps the bytes
    identical whatever the platform encoding, and ``allow_nan`` is off because
    NaN is not JSON and a digest over it would not round-trip.
    """
    return json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def universe_fingerprint(
    *,
    universe_id: str,
    symbols: Sequence[str],
    as_of: date,
    source_kind: UniverseSourceKind | str,
    source_reference: str,
) -> str:
    """Full SHA-256 identity of a universe's research meaning.

    ``source_reference`` participates because it *is* the provenance claim. The
    same ten symbols captured on the same day are a different research universe
    depending on whether they came from a personal watchlist or from a published
    constituent list, and a scan should be distinguishable by which was claimed.

    ``display_name`` and ``enabled`` are excluded: renaming a universe or
    switching it off changes nothing about which research it describes.

    Never truncated. The digest is an identity, and shortening one to look tidy
    is how two different universes end up sharing a name.
    """
    payload = {
        "version": FINGERPRINT_VERSION,
        "universe_id": require_universe_id(universe_id),
        "symbols": sorted(symbols),
        "as_of": as_of.isoformat(),
        "source_kind": UniverseSourceKind(source_kind).value,
        "source_reference": source_reference.strip(),
    }
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def build_universe(
    *,
    universe_id: str,
    display_name: str,
    symbols: Iterable[object],
    source_kind: UniverseSourceKind | str,
    source_reference: str,
    as_of: date,
    enabled: bool = True,
) -> tuple[UniverseDefinition, int]:
    """Assemble one validated universe. Returns it and its duplicate count."""
    normalized, duplicates = normalize_symbols(symbols)
    kind = UniverseSourceKind(source_kind)
    definition = UniverseDefinition(
        universe_id=universe_id,
        display_name=display_name,
        symbols=normalized,
        source_kind=kind,
        source_reference=source_reference,
        as_of=as_of,
        enabled=enabled,
        fingerprint=universe_fingerprint(
            universe_id=require_universe_id(universe_id),
            symbols=normalized,
            as_of=as_of,
            source_kind=kind,
            source_reference=source_reference,
        ),
    )
    return definition, duplicates


__all__ = [
    "FINGERPRINT_VERSION",
    "normalize_symbol",
    "normalize_symbols",
    "canonical_bytes",
    "universe_fingerprint",
    "build_universe",
]
