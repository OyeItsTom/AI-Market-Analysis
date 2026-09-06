"""Phase 9 configuration: an allowlist, validated as untrusted input.

The file is written by the user, which makes it trusted in intent and untrusted
in content: a typo points somewhere private just as effectively as an attacker
would. It is therefore validated exactly as strictly as anything from the
network.
"""

from __future__ import annotations

import json

import pytest

from src.feeds.config import (
    CONFIG_SCHEMA_VERSION,
    EXAMPLE_CONFIG_NAME,
    LOCAL_CONFIG_NAME,
    ConfigError,
    FeedConfiguration,
    FeedDefinition,
    load_configuration,
    parse_configuration,
)
from src.feeds.models import MAX_CONFIG_BYTES, MAX_SOURCES, DeclaredTrustClass, FeedFormat

REPO = __import__("pathlib").Path(__file__).resolve().parent.parent


def source(**overrides):
    entry = {
        "source_id": "demo",
        "type": "ATOM",
        "url": "https://example.com/feed.xml",
        "display_name": "Demo",
        "declared_trust_class": "publisher_feed",
        "configured_symbols": ["AAPL"],
    }
    entry.update(overrides)
    return entry


def payload(*sources, **overrides):
    body = {"schema_version": CONFIG_SCHEMA_VERSION, "sources": list(sources)}
    body.update(overrides)
    return body


# -- schema version ------------------------------------------------------


def test_a_configuration_without_a_version_is_refused():
    with pytest.raises(ConfigError):
        parse_configuration({"sources": []})


@pytest.mark.parametrize("version", [0, 2, 99, "1", None])
def test_an_unknown_version_is_refused_rather_than_guessed_at(version):
    """A later writer may have changed what a field means."""
    with pytest.raises(ConfigError):
        parse_configuration({"schema_version": version, "sources": []})


def test_the_current_version_parses():
    assert parse_configuration(payload()).schema_version == CONFIG_SCHEMA_VERSION


# -- shape ---------------------------------------------------------------


@pytest.mark.parametrize("body", [[], "sources", 42, None])
def test_a_configuration_that_is_not_an_object_is_refused(body):
    with pytest.raises(ConfigError):
        parse_configuration(body)


@pytest.mark.parametrize("sources", ["not a list", {"a": 1}, 42, None])
def test_sources_must_be_a_list(sources):
    with pytest.raises(ConfigError):
        parse_configuration({"schema_version": CONFIG_SCHEMA_VERSION, "sources": sources})


def test_a_source_that_is_not_an_object_is_refused():
    with pytest.raises(ConfigError):
        parse_configuration(payload("not an object"))


def test_an_error_names_the_offending_source():
    with pytest.raises(ConfigError) as caught:
        parse_configuration(payload(source(), source(source_id="bad", url="http://x.test/f")))
    assert "#1" in str(caught.value)


# -- destinations --------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/feed.xml",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "https://user:pass@example.com/feed.xml",
        "ftp://example.com/feed.xml",
        "",
        None,
    ],
)
def test_a_feed_url_that_is_not_plain_https_is_refused(url):
    with pytest.raises(ConfigError):
        parse_configuration(payload(source(url=url)))


def test_a_url_pointing_at_a_literal_private_address_is_refused():
    with pytest.raises(ConfigError):
        parse_configuration(payload(source(url="https://169.254.169.254/latest/")))


# -- vocabulary ----------------------------------------------------------


@pytest.mark.parametrize("kind", ["RSS", "rss", "ATOM", "Atom"])
def test_the_two_supported_types_are_accepted_case_insensitively(kind):
    assert parse_configuration(payload(source(type=kind))).sources[0].feed_format


@pytest.mark.parametrize("kind", ["JSON", "telegram", "rdf", "", None, 1])
def test_any_other_type_is_refused(kind):
    """Including Telegram, which is deferred and must not be configurable."""
    with pytest.raises(ConfigError):
        parse_configuration(payload(source(type=kind)))


@pytest.mark.parametrize("trust", ["official_feed", "publisher_feed", "community_feed"])
def test_the_three_trust_classes_are_accepted(trust):
    parsed = parse_configuration(payload(source(declared_trust_class=trust)))
    assert parsed.sources[0].declared_trust_class.value == trust


@pytest.mark.parametrize("trust", ["verified", "trusted", "", None, 1])
def test_an_invented_trust_class_is_refused(trust):
    with pytest.raises(ConfigError):
        parse_configuration(payload(source(declared_trust_class=trust)))


# -- identifiers and limits ----------------------------------------------


@pytest.mark.parametrize("bad", ["", "a b", "a/b", "../etc", "x" * 200, None, 1])
def test_a_malformed_source_id_is_refused(bad):
    """It becomes a directory name, so path characters are refused outright."""
    with pytest.raises(ConfigError):
        parse_configuration(payload(source(source_id=bad)))


def test_duplicate_source_ids_are_refused():
    """Two feeds sharing an id would write into one another's store."""
    with pytest.raises(ConfigError):
        parse_configuration(payload(source(), source(url="https://other.example.com/f.xml")))


def test_too_many_sources_are_refused():
    many = [source(source_id=f"feed-{n}") for n in range(MAX_SOURCES + 1)]
    with pytest.raises(ConfigError):
        parse_configuration(payload(*many))


def test_too_many_symbols_for_one_source_are_refused():
    with pytest.raises(ConfigError):
        parse_configuration(payload(source(configured_symbols=[f"S{n}" for n in range(50)])))


def test_duplicate_symbols_in_one_source_are_refused():
    with pytest.raises(ConfigError):
        parse_configuration(payload(source(configured_symbols=["AAPL", "AAPL"])))


def test_a_malformed_symbol_is_refused():
    with pytest.raises(ConfigError):
        parse_configuration(payload(source(configured_symbols=["AA PL"])))


def test_no_configured_symbols_is_allowed():
    """A general feed covers no particular company, and says so by having none."""
    assert parse_configuration(payload(source(configured_symbols=[]))).sources[0].configured_symbols == ()


def test_enabled_must_be_a_boolean():
    with pytest.raises(ConfigError):
        FeedDefinition(
            source_id="demo", feed_format=FeedFormat.RSS,
            url="https://example.com/f.xml", display_name="D",
            declared_trust_class=DeclaredTrustClass.COMMUNITY_FEED, enabled="yes",
        )


def test_disabled_sources_are_kept_but_excluded_from_enabled():
    parsed = parse_configuration(payload(source(), source(source_id="off", enabled=False)))
    assert len(parsed.sources) == 2
    assert [d.source_id for d in parsed.enabled] == ["demo"]


def test_a_source_can_be_looked_up_by_id():
    parsed = parse_configuration(payload(source()))
    assert parsed.get("demo").display_name == "Demo"
    assert parsed.get("missing") is None


# -- loading from disk ---------------------------------------------------


def test_an_absent_file_is_an_empty_configuration_not_an_error(tmp_path):
    """A fresh checkout has no feeds, and that is the correct state."""
    assert load_configuration(tmp_path / "nope.json").sources == ()


def test_an_oversized_file_is_refused_by_size_before_being_read(tmp_path):
    path = tmp_path / LOCAL_CONFIG_NAME
    path.write_text("x" * (MAX_CONFIG_BYTES + 1))
    with pytest.raises(ConfigError):
        load_configuration(path)


def test_invalid_json_is_reported_clearly(tmp_path):
    path = tmp_path / LOCAL_CONFIG_NAME
    path.write_text("{not json")
    with pytest.raises(ConfigError):
        load_configuration(path)


def test_a_valid_file_loads(tmp_path):
    path = tmp_path / LOCAL_CONFIG_NAME
    path.write_text(json.dumps(payload(source())))
    assert load_configuration(path).sources[0].source_id == "demo"


# -- the shipped example -------------------------------------------------


def test_the_example_configuration_parses():
    path = REPO / "config" / EXAMPLE_CONFIG_NAME
    assert path.is_file()
    assert parse_configuration(json.loads(path.read_text())).sources


def test_every_example_feed_ships_disabled():
    """Copying the example must not start fetching anything."""
    path = REPO / "config" / EXAMPLE_CONFIG_NAME
    assert parse_configuration(json.loads(path.read_text())).enabled == ()


def test_no_local_configuration_is_committed():
    assert not (REPO / "config" / LOCAL_CONFIG_NAME).exists()


# -- fingerprints on the definition --------------------------------------


def test_renaming_a_feed_changes_neither_fingerprint():
    original = parse_configuration(payload(source())).sources[0]
    renamed = parse_configuration(payload(source(display_name="A Nicer Name"))).sources[0]
    assert original.endpoint_fingerprint == renamed.endpoint_fingerprint
    assert original.config_fingerprint == renamed.config_fingerprint


def test_relabelling_trust_changes_only_the_config_fingerprint():
    original = parse_configuration(payload(source())).sources[0]
    relabelled = parse_configuration(
        payload(source(declared_trust_class="official_feed"))
    ).sources[0]
    assert original.endpoint_fingerprint == relabelled.endpoint_fingerprint
    assert original.config_fingerprint != relabelled.config_fingerprint


def test_the_host_is_exposed_lowercased():
    parsed = parse_configuration(payload(source(url="https://WWW.Example.COM/f.xml")))
    assert parsed.sources[0].host == "www.example.com"


def test_an_oversized_file_is_refused_even_when_it_is_valid_json(tmp_path):
    """Proves the size ceiling fires, not merely that huge junk fails to parse."""
    path = tmp_path / LOCAL_CONFIG_NAME
    body = payload(source())
    body["_padding"] = "x" * (MAX_CONFIG_BYTES + 1000)
    path.write_text(json.dumps(body))
    assert path.stat().st_size > MAX_CONFIG_BYTES
    json.loads(path.read_text())  # it is perfectly valid JSON
    with pytest.raises(ConfigError) as caught:
        load_configuration(path)
    assert "limit" in str(caught.value) or "bytes" in str(caught.value)
