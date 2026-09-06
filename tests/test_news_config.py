"""Phase 8 configuration: the SEC contact address.

Two things matter here. A missing contact must switch EDGAR off rather than
break a refresh, and the configured value -- a personal email -- must never
appear in an error message or in the repository.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from src.news.config import (
    MAX_LENGTH,
    MIN_LENGTH,
    SEC_USER_AGENT_VAR,
    UNCONFIGURED_MESSAGE,
    ConfigError,
    SecContact,
    describe_configuration,
    read_sec_contact,
    validate_user_agent,
)

VALID = "AI-Market-Analysis someone@example.com"


# -- validation ----------------------------------------------------------


def test_a_valid_contact_is_accepted():
    assert validate_user_agent(VALID) == VALID
    assert SecContact(VALID).user_agent == VALID


def test_whitespace_is_trimmed():
    assert validate_user_agent(f"  {VALID}  ") == VALID


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "short",                       # under the minimum
        "no-at-sign-here-but-long",    # no contact address
        "x" * (MAX_LENGTH + 1),
    ],
)
def test_invalid_contacts_are_rejected(value):
    with pytest.raises(ConfigError):
        validate_user_agent(value)


def test_non_string_is_rejected():
    with pytest.raises(ConfigError):
        validate_user_agent(12345)


@pytest.mark.parametrize("bad", ["contact@example.com\nX-Injected: 1", "contact@example.com\rmore", "c@ex\x00.com"])
def test_control_characters_are_rejected(bad):
    """A newline in a header value would let a second header be injected."""
    with pytest.raises(ConfigError):
        validate_user_agent("AI-Market-Analysis " + bad)


def test_bounds_are_what_they_claim():
    assert MIN_LENGTH == 10 and MAX_LENGTH == 200


# -- reading the environment --------------------------------------------


def test_absent_variable_reads_as_none():
    assert read_sec_contact({}) is None


def test_present_variable_reads_as_a_contact():
    contact = read_sec_contact({SEC_USER_AGENT_VAR: VALID})
    assert contact is not None and contact.user_agent == VALID


def test_invalid_variable_reads_as_none_rather_than_raising():
    """An unusable value switches EDGAR off; it does not break a refresh."""
    assert read_sec_contact({SEC_USER_AGENT_VAR: "nope"}) is None


def test_only_this_one_variable_is_consulted():
    """Nothing is taken from git config, the OS user or any other variable."""
    environ = {
        "EMAIL": "not-consulted@example.org",
        "USER": "someone",
        "GIT_AUTHOR_EMAIL": "not-consulted@example.org",
    }
    assert read_sec_contact(environ) is None


# -- the value never leaks ----------------------------------------------


def test_the_unconfigured_message_names_the_variable_and_nothing_else():
    assert SEC_USER_AGENT_VAR in UNCONFIGURED_MESSAGE
    assert "docs/news.md" in UNCONFIGURED_MESSAGE
    assert "Yahoo" in UNCONFIGURED_MESSAGE
    assert "@" not in UNCONFIGURED_MESSAGE.replace(SEC_USER_AGENT_VAR, "")


def test_configuration_description_never_echoes_the_value():
    described = describe_configuration({SEC_USER_AGENT_VAR: VALID})
    assert "someone@example.com" not in described
    assert "configured" in described.lower()


def test_validation_errors_never_echo_the_value():
    secret = "AI-Market-Analysis private.person@example.net\nInjected"
    with pytest.raises(ConfigError) as info:
        validate_user_agent(secret)
    assert "private.person" not in str(info.value)


# -- nothing personal is committed --------------------------------------

REPO = pathlib.Path(__file__).resolve().parent.parent

PHASE_8_PATHS = [
    REPO / ".env.example",
    REPO / "docs" / "news.md",
    REPO / "docs" / "adr" / "0006-news-and-announcements.md",
    *(REPO / "src" / "news").rglob("*.py"),
    REPO / "src" / "application" / "news.py",
    REPO / "src" / "dashboard" / "news_view.py",
    *(REPO / "tests").glob("test_news_*.py"),
    REPO / "tests" / "test_application_news.py",
]

#: RFC 2606 reserves these domains for documentation, so an address at one of
#: them is provably not a real person's. Anything else is treated as real.
EXAMPLE_DOMAINS = ("example.com", "example.org", "example.net")

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _is_example(address: str) -> bool:
    return address.lower().endswith(EXAMPLE_DOMAINS)


def _addresses_in(path: pathlib.Path) -> set[str]:
    if not path.is_file():
        return set()
    return set(EMAIL.findall(path.read_text(encoding="utf-8")))


def test_env_example_carries_only_an_example_address():
    found = _addresses_in(REPO / ".env.example")
    assert found, "the example file should show the expected shape"
    assert all(_is_example(a) for a in found), f"non-example address: {found}"


@pytest.mark.parametrize("path", PHASE_8_PATHS, ids=lambda p: p.name)
def test_no_real_contact_address_is_committed(path):
    """A personal address is not a secret, but it does not belong in a repo."""
    offenders = {a for a in _addresses_in(path) if not _is_example(a)}
    assert not offenders, f"{path.name} contains non-example address(es): {offenders}"


def test_the_example_address_is_not_treated_as_configured():
    """The example is a placeholder, but it is still structurally valid: the
    point of the scan is that it is obviously not a real person."""
    assert "your-email@example.com" in (REPO / ".env.example").read_text()


def test_no_phase_eight_source_hardcodes_a_user_agent():
    """The contact must come from the environment, never from the source."""
    for path in (REPO / "src" / "news").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            code = line.split("#", 1)[0]
            if "user_agent" in code.lower() and "=" in code:
                assert "@" not in code, f"{path.name} looks like a hardcoded contact: {line.strip()}"
