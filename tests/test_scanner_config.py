"""Phase 10 universe configuration: the one adapter allowed to read a file.

Two properties matter beyond ordinary parsing. The size ceiling must fire
*before* the file is read, or the limit protects nothing. And the example file
must never be loaded as a fallback: silently scanning symbols the user never
chose would be worse than an empty panel.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from src.scanner.config import (
    CONFIG_SCHEMA_VERSION,
    EXAMPLE_CONFIG_NAME,
    LOCAL_CONFIG_NAME,
    UNCONFIGURED_MESSAGE,
    ConfigError,
    load_configuration,
    parse_configuration,
)
from src.scanner.models import (
    MAX_SYMBOLS_PER_UNIVERSE,
    MAX_UNIVERSE_CONFIG_BYTES,
    MAX_UNIVERSES,
    UniverseSourceKind,
)

REPO = pathlib.Path(__file__).resolve().parent.parent


def entry(**overrides):
    fields = {
        "universe_id": "demo",
        "display_name": "Demo",
        "source_kind": "local_static",
        "source_reference": "illustrative demo membership",
        "as_of": "2026-09-06",
        "symbols": ["AAPL", "MSFT"],
    }
    fields.update(overrides)
    return fields


def payload(*universes, **overrides):
    body = {"schema_version": CONFIG_SCHEMA_VERSION, "universes": list(universes) or [entry()]}
    body.update(overrides)
    return body


# -- schema --------------------------------------------------------------


@pytest.mark.parametrize("version", [None, 0, 2, 99, "1"])
def test_an_unknown_schema_version_is_refused(version):
    with pytest.raises(ConfigError):
        parse_configuration({"schema_version": version, "universes": []})


def test_the_current_version_parses():
    assert parse_configuration(payload()).schema_version == CONFIG_SCHEMA_VERSION


@pytest.mark.parametrize("body", [[], "universes", 42, None])
def test_a_configuration_that_is_not_an_object_is_refused(body):
    with pytest.raises(ConfigError):
        parse_configuration(body)


@pytest.mark.parametrize("value", ["nope", {"a": 1}, 42, None])
def test_universes_must_be_a_list(value):
    with pytest.raises(ConfigError):
        parse_configuration({"schema_version": CONFIG_SCHEMA_VERSION, "universes": value})


def test_symbols_must_be_a_list():
    with pytest.raises(ConfigError):
        parse_configuration(payload(entry(symbols="AAPL")))


def test_an_error_names_the_offending_universe():
    with pytest.raises(ConfigError) as caught:
        parse_configuration(payload(entry(universe_id="broken", symbols=["AA PL"])))
    assert "broken" in str(caught.value)


# -- provenance ----------------------------------------------------------


@pytest.mark.parametrize("kind", ["local_static", "user_defined", "LOCAL_STATIC"])
def test_supported_source_kinds_parse(kind):
    parsed = parse_configuration(payload(entry(source_kind=kind)))
    assert parsed.universes[0].source_kind in UniverseSourceKind


@pytest.mark.parametrize(
    "kind", ["verified_index", "official_index", "external_index", "", None, 1]
)
def test_a_provenance_claim_the_system_cannot_support_is_refused(kind):
    with pytest.raises(ConfigError):
        parse_configuration(payload(entry(source_kind=kind)))


@pytest.mark.parametrize("as_of", ["", "not-a-date", "06/09/2026", None, 20260906])
def test_a_malformed_as_of_is_refused(as_of):
    with pytest.raises(ConfigError):
        parse_configuration(payload(entry(as_of=as_of)))


def test_source_reference_is_required():
    with pytest.raises(ConfigError):
        parse_configuration(payload(entry(source_reference="")))


# -- identity and limits -------------------------------------------------


@pytest.mark.parametrize("bad", ["", "a/b", "a\\b", "../etc", "a b", "x" * 200, None, 1])
def test_a_malformed_universe_id_is_refused(bad):
    with pytest.raises(ConfigError):
        parse_configuration(payload(entry(universe_id=bad)))


def test_duplicate_universe_ids_are_refused():
    with pytest.raises(ConfigError):
        parse_configuration(payload(entry(), entry(display_name="Other")))


def test_too_many_universes_are_refused():
    many = [entry(universe_id=f"u{n}") for n in range(MAX_UNIVERSES + 1)]
    with pytest.raises(ConfigError):
        parse_configuration(payload(*many))


def test_too_many_symbols_are_refused():
    over = [f"S{n:04d}" for n in range(MAX_SYMBOLS_PER_UNIVERSE + 1)]
    with pytest.raises(ConfigError):
        parse_configuration(payload(entry(symbols=over)))


@pytest.mark.parametrize("bad", ["AA PL", "", "A\x00B", 1, None])
def test_an_invalid_symbol_is_refused(bad):
    with pytest.raises(ConfigError):
        parse_configuration(payload(entry(symbols=["AAPL", bad])))


def test_disabled_universes_are_kept_but_excluded_from_enabled():
    parsed = parse_configuration(
        payload(entry(), entry(universe_id="off", enabled=False))
    )
    assert len(parsed.universes) == 2
    assert [u.universe_id for u in parsed.enabled] == ["demo"]


def test_all_universes_disabled_is_valid():
    parsed = parse_configuration(payload(entry(enabled=False)))
    assert parsed.enabled == ()
    assert not parsed.is_empty


# -- load report ---------------------------------------------------------


def test_the_load_report_counts_what_the_loader_observed():
    parsed = parse_configuration(
        payload(entry(symbols=["aapl", "AAPL", "msft"]),
                entry(universe_id="two", symbols=["GOOGL"], enabled=False))
    )
    report = parsed.load_report
    assert report.raw_symbol_count == 4
    assert report.normalized_symbol_count == 3
    assert report.duplicates_removed == 1
    assert report.universes_loaded == 2
    assert report.universes_enabled == 1
    assert "duplicates removed" in report.describe()


# -- loading from disk ---------------------------------------------------


def test_a_missing_file_is_an_empty_configuration_not_an_error(tmp_path):
    config = load_configuration(tmp_path / "absent.json")
    assert config.is_empty
    assert config.load_report.universes_loaded == 0


def test_an_oversized_file_is_refused_even_when_it_is_valid_json(tmp_path):
    """Proves the size ceiling fires, not merely that huge junk fails to parse."""
    path = tmp_path / LOCAL_CONFIG_NAME
    body = payload()
    body["_padding"] = "x" * (MAX_UNIVERSE_CONFIG_BYTES + 1000)
    path.write_text(json.dumps(body))
    assert path.stat().st_size > MAX_UNIVERSE_CONFIG_BYTES
    json.loads(path.read_text())  # it is perfectly valid JSON
    with pytest.raises(ConfigError) as caught:
        load_configuration(path)
    assert "limit" in str(caught.value) or "bytes" in str(caught.value)


def test_the_size_check_happens_before_the_read(tmp_path, monkeypatch):
    """A limit enforced after loading the bytes protects nothing."""
    path = tmp_path / LOCAL_CONFIG_NAME
    path.write_text("x" * (MAX_UNIVERSE_CONFIG_BYTES + 10))

    def forbidden(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("the file was read before its size was checked")

    monkeypatch.setattr(pathlib.Path, "read_text", forbidden)
    with pytest.raises(ConfigError):
        load_configuration(path)


def test_malformed_json_is_reported_clearly(tmp_path):
    path = tmp_path / LOCAL_CONFIG_NAME
    path.write_text("{not json")
    with pytest.raises(ConfigError):
        load_configuration(path)


def test_a_valid_file_loads(tmp_path):
    path = tmp_path / LOCAL_CONFIG_NAME
    path.write_text(json.dumps(payload()))
    assert load_configuration(path).universes[0].universe_id == "demo"


def test_loading_performs_no_network_call(tmp_path, monkeypatch):
    """Choosing universes must put nothing on the wire."""
    import socket

    def forbidden(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("configuration loading resolved a hostname")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    path = tmp_path / LOCAL_CONFIG_NAME
    path.write_text(json.dumps(payload()))
    assert load_configuration(path).universes


def test_loading_writes_nothing(tmp_path):
    path = tmp_path / LOCAL_CONFIG_NAME
    path.write_text(json.dumps(payload()))
    before = {p.name for p in tmp_path.iterdir()}
    load_configuration(path)
    assert {p.name for p in tmp_path.iterdir()} == before


def test_the_loader_is_stateless(tmp_path):
    """No module-level cache: a second load reflects the file as it now is."""
    path = tmp_path / LOCAL_CONFIG_NAME
    path.write_text(json.dumps(payload()))
    assert load_configuration(path).universes[0].display_name == "Demo"
    path.write_text(json.dumps(payload(entry(display_name="Renamed"))))
    assert load_configuration(path).universes[0].display_name == "Renamed"


def test_a_failed_load_retains_nothing_itself(tmp_path):
    """Last-good retention belongs to a later layer, not to this adapter."""
    path = tmp_path / LOCAL_CONFIG_NAME
    path.write_text(json.dumps(payload()))
    load_configuration(path)
    path.write_text("{broken")
    with pytest.raises(ConfigError):
        load_configuration(path)


# -- the example file ----------------------------------------------------


def test_the_example_configuration_parses():
    path = REPO / "config" / EXAMPLE_CONFIG_NAME
    assert path.is_file()
    parsed = parse_configuration(json.loads(path.read_text()))
    assert parsed.universes
    assert parsed.universes[0].symbol_count == 10


def test_the_example_claims_only_supportable_provenance():
    parsed = parse_configuration(
        json.loads((REPO / "config" / EXAMPLE_CONFIG_NAME).read_text())
    )
    universe = parsed.universes[0]
    assert universe.source_kind is UniverseSourceKind.LOCAL_STATIC
    reference = universe.source_reference.lower()
    assert "illustrative" in reference or "demo" in reference
    for forbidden in ("s&p", "nasdaq-100", "current constituents", "official"):
        assert forbidden not in reference


def test_the_example_is_never_loaded_as_a_fallback(tmp_path):
    """A missing local file yields an empty configuration, not the example."""
    assert load_configuration(tmp_path / "absent.json").is_empty


def test_no_local_configuration_is_committed():
    assert not (REPO / "config" / LOCAL_CONFIG_NAME).exists()


def test_the_local_config_is_gitignored():
    assert LOCAL_CONFIG_NAME in (REPO / ".gitignore").read_text()


def test_the_unconfigured_message_explains_the_copy_step():
    assert LOCAL_CONFIG_NAME in UNCONFIGURED_MESSAGE
    assert EXAMPLE_CONFIG_NAME in UNCONFIGURED_MESSAGE


# -- the size bound is enforced on the read, not just on the stat --------


def test_an_oversized_file_is_refused_even_if_stat_understates_it(tmp_path, monkeypatch):
    """A file can grow between being measured and being read.

    A stat-only check would make the guarantee "it was small a moment ago",
    which is not what a resource bound is for. The read itself must be bounded.
    """
    path = tmp_path / LOCAL_CONFIG_NAME
    path.write_text(
        '{"schema_version":1,"_pad":"' + "x" * (MAX_UNIVERSE_CONFIG_BYTES + 5000)
        + '","universes":[]}'
    )
    real_stat = pathlib.Path.stat

    class Understated:
        st_size = 100

        def __init__(self, wrapped):
            self._wrapped = wrapped

        def __getattr__(self, name):
            return getattr(self._wrapped, name)

    def lying_stat(self, *args, **kwargs):
        result = real_stat(self, *args, **kwargs)
        return Understated(result) if self == path else result

    monkeypatch.setattr(pathlib.Path, "stat", lying_stat)
    with pytest.raises(ConfigError, match="limit"):
        load_configuration(path)


def test_the_read_never_pulls_in_more_than_the_limit(tmp_path, monkeypatch):
    """Asserted on the request itself: at most limit + 1 bytes are ever asked for."""
    path = tmp_path / LOCAL_CONFIG_NAME
    path.write_text(json.dumps(payload()))
    requested: list[int] = []
    real_open = pathlib.Path.open

    def recording_open(self, *args, **kwargs):
        handle = real_open(self, *args, **kwargs)
        real_read = handle.read

        def read(size=-1):
            requested.append(size)
            return real_read(size)

        handle.read = read
        return handle

    monkeypatch.setattr(pathlib.Path, "open", recording_open)
    load_configuration(path)
    assert requested, "the file was not read through a bounded handle"
    assert all(0 < size <= MAX_UNIVERSE_CONFIG_BYTES + 1 for size in requested), requested


def test_a_file_exactly_at_the_limit_is_accepted(tmp_path):
    """The boundary itself is legal; only one byte past it is not."""
    path = tmp_path / LOCAL_CONFIG_NAME
    body = payload()
    body["_padding"] = "y"
    text = json.dumps(body)
    text = text[:-1] + " " * (MAX_UNIVERSE_CONFIG_BYTES - len(text)) + "}"
    path.write_text(text)
    assert len(path.read_bytes()) == MAX_UNIVERSE_CONFIG_BYTES
    assert load_configuration(path).universes
