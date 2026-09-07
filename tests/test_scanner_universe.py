"""Phase 10 universe identity: normalization, de-duplication and fingerprints.

The fingerprint tests are the important ones. A fingerprint that changed when a
universe was merely renamed would discard valid history; one that stayed the
same when membership or provenance changed would let two different research
universes share an identity.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.scanner.models import MAX_SYMBOLS_PER_UNIVERSE, ScannerError, UniverseSourceKind
from src.scanner.universe import (
    build_universe,
    canonical_bytes,
    normalize_symbol,
    normalize_symbols,
    universe_fingerprint,
)

AS_OF = date(2026, 9, 6)


def base(**overrides):
    fields = dict(
        universe_id="demo",
        symbols=("AAPL", "MSFT"),
        as_of=AS_OF,
        source_kind=UniverseSourceKind.LOCAL_STATIC,
        source_reference="illustrative demo membership",
    )
    fields.update(overrides)
    return fields


# -- symbol normalization ------------------------------------------------


def test_normalization_matches_provider_semantics():
    """strip + upper, exactly as MarketDataProvider._normalize_symbol does."""
    from src.data.provider import MarketDataProvider

    for raw in (" aapl ", "AAPL", "AaPl"):
        assert normalize_symbol(raw) == MarketDataProvider._normalize_symbol(raw)


def test_exchange_suffixes_are_preserved():
    """yfinance uses them; rewriting them would break valid symbols."""
    assert normalize_symbol("vod.l") == "VOD.L"
    assert normalize_symbol("shop.to") == "SHOP.TO"
    assert normalize_symbol("brk.b") == "BRK.B"


@pytest.mark.parametrize(
    "bad", ["", "   ", "AA PL", "AA\tPL", "AA\nPL", "A\x00B", "A\x7fB", "x" * 100, 1, None, b"AAPL"]
)
def test_malformed_symbols_are_refused(bad):
    with pytest.raises(ScannerError):
        normalize_symbol(bad)


def test_duplicates_are_merged_and_counted():
    symbols, duplicates = normalize_symbols([" aapl ", "AAPL", "AaPl", "MSFT"])
    assert symbols == ("AAPL", "MSFT")
    assert duplicates == 2


def test_symbols_are_sorted_so_file_order_does_not_matter():
    assert normalize_symbols(["MSFT", "AAPL"])[0] == normalize_symbols(["AAPL", "MSFT"])[0]


def test_an_empty_universe_is_refused():
    with pytest.raises(ScannerError):
        normalize_symbols([])


def test_the_symbol_ceiling_is_enforced():
    too_many = [f"S{n:04d}" for n in range(MAX_SYMBOLS_PER_UNIVERSE + 1)]
    with pytest.raises(ScannerError):
        normalize_symbols(too_many)
    assert len(normalize_symbols(too_many[:MAX_SYMBOLS_PER_UNIVERSE])[0]) == (
        MAX_SYMBOLS_PER_UNIVERSE
    )


# -- canonical encoding --------------------------------------------------


def test_key_order_does_not_change_the_encoding():
    assert canonical_bytes({"b": 1, "a": 2}) == canonical_bytes({"a": 2, "b": 1})


def test_encoding_is_ascii_safe():
    assert all(byte < 128 for byte in canonical_bytes({"t": "café ☕"}))


def test_non_finite_numbers_are_refused():
    with pytest.raises(ValueError):
        canonical_bytes({"x": float("nan")})


# -- fingerprint ---------------------------------------------------------


def test_fingerprint_is_a_full_untruncated_sha256():
    digest = universe_fingerprint(**base())
    assert len(digest) == 64
    int(digest, 16)


def test_fingerprint_is_deterministic():
    assert universe_fingerprint(**base()) == universe_fingerprint(**base())


def test_symbol_order_does_not_change_the_fingerprint():
    """Reordering a list in a file is not a change of research meaning."""
    assert universe_fingerprint(**base(symbols=("MSFT", "AAPL"))) == (
        universe_fingerprint(**base(symbols=("AAPL", "MSFT")))
    )


@pytest.mark.parametrize(
    "change",
    [
        {"symbols": ("AAPL", "MSFT", "GOOGL")},
        {"symbols": ("AAPL",)},
        {"as_of": date(2026, 9, 5)},
        {"source_kind": UniverseSourceKind.USER_DEFINED},
        {"source_reference": "a different provenance claim"},
        {"universe_id": "other"},
    ],
)
def test_a_material_change_changes_the_fingerprint(change):
    assert universe_fingerprint(**base()) != universe_fingerprint(**base(**change))


def test_source_reference_participates_because_it_is_the_provenance_claim():
    """Same symbols, same date, different claimed origin -- a different universe."""
    watchlist = universe_fingerprint(**base(source_reference="my personal watchlist"))
    published = universe_fingerprint(**base(source_reference="published constituents"))
    assert watchlist != published


def test_display_name_does_not_change_the_fingerprint():
    """Renaming a universe must not invalidate anything.

    Asserted on the signature: display_name is not a parameter, so there is no
    route by which it could influence the digest.
    """
    import inspect

    assert "display_name" not in inspect.signature(universe_fingerprint).parameters
    first, _ = build_universe(display_name="One", **base(), enabled=True)
    second, _ = build_universe(display_name="A Nicer Name", **base(), enabled=True)
    assert first.fingerprint == second.fingerprint


def test_enabled_does_not_change_the_fingerprint():
    """An on/off switch is not an identity."""
    import inspect

    assert "enabled" not in inspect.signature(universe_fingerprint).parameters
    on, _ = build_universe(display_name="D", **base(), enabled=True)
    off, _ = build_universe(display_name="D", **base(), enabled=False)
    assert on.fingerprint == off.fingerprint


# -- assembly ------------------------------------------------------------


def test_build_universe_normalizes_sorts_and_fingerprints():
    definition, duplicates = build_universe(
        universe_id="Demo-1", display_name="Demo",
        symbols=[" msft ", "AAPL", "aapl", "vod.l"],
        source_kind="local_static", source_reference="illustrative", as_of=AS_OF,
    )
    assert definition.universe_id == "demo-1"
    assert definition.symbols == ("AAPL", "MSFT", "VOD.L")
    assert duplicates == 1
    assert len(definition.fingerprint) == 64


def test_build_universe_rejects_an_unsupported_source_kind():
    with pytest.raises(ValueError):
        build_universe(universe_id="d", display_name="D", symbols=["AAPL"],
                       source_kind="verified_index", source_reference="x", as_of=AS_OF)


def test_the_universe_module_opens_no_files():
    """Purity asserted structurally, not by inspection of behaviour."""
    import ast
    import pathlib

    tree = ast.parse(pathlib.Path("src/scanner/universe.py").read_text(encoding="utf-8"))
    called = {
        node.func.id for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    attrs = {
        node.func.attr for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "open" not in called
    assert not {"read_text", "write_text", "read_bytes", "write_bytes"} & attrs


def test_surrounding_whitespace_in_provenance_does_not_change_identity():
    """The same claim typed with stray spaces is the same claim.

    Otherwise a user tidying their config file would silently create a new
    universe identity.
    """
    base_fp = universe_fingerprint(**base(source_reference="my watchlist"))
    for variant in ("my watchlist ", " my watchlist", "  my watchlist  ", "my watchlist\n"):
        assert universe_fingerprint(**base(source_reference=variant)) == base_fp


def test_internal_provenance_text_remains_meaningful():
    """Only surrounding whitespace is ignored; the content itself is not rewritten."""
    base_fp = universe_fingerprint(**base(source_reference="my watchlist"))
    assert universe_fingerprint(**base(source_reference="my  watchlist")) != base_fp
    assert universe_fingerprint(**base(source_reference="my\twatchlist")) != base_fp


def test_the_stored_reference_matches_what_was_hashed():
    """A record whose text differed from its digest input would be misleading."""
    first, _ = build_universe(display_name="D", **base(source_reference="  my watchlist  "))
    second, _ = build_universe(display_name="D", **base(source_reference="my watchlist"))
    assert first.source_reference == second.source_reference == "my watchlist"
    assert first.fingerprint == second.fingerprint
