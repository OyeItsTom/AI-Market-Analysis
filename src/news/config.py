"""Local configuration for the SEC contact header.

The SEC asks automated clients to identify themselves with a contact address so
it can reach whoever is generating traffic. That is **contact identification,
not a secret** -- but a personal email address still has no business in a public
repository, so it is read from the environment and never committed.

Absence is not an error
-----------------------
An unset ``SEC_USER_AGENT`` disables the EDGAR source and nothing else. It
surfaces as :attr:`~src.news.source.SourceOutcome.UNCONFIGURED`, the Yahoo
source keeps working, and the dashboard says which source is switched off and
why. A missing contact address is a setup step the user has not done yet, not a
fault to crash a refresh over.

The configured value is never echoed back in an error message: it contains a
personal address, and error text ends up in screenshots and issue reports.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

#: The one environment variable Phase 8 reads. Nothing is taken from git config,
#: the GitHub account or the OS user: those would put a personal address into
#: outbound requests without the user ever choosing to.
SEC_USER_AGENT_VAR = "SEC_USER_AGENT"

MIN_LENGTH = 10
MAX_LENGTH = 200

#: Shown when EDGAR is switched off. Names the variable and the doc, and quotes
#: nothing back.
UNCONFIGURED_MESSAGE = (
    "EDGAR filings are switched off because no contact address is configured. "
    f"Set {SEC_USER_AGENT_VAR} (see docs/news.md). Yahoo news is unaffected."
)


class ConfigError(ValueError):
    """Raised only when a caller demands configuration that is absent."""


@dataclass(frozen=True)
class SecContact:
    """A validated SEC contact header."""

    user_agent: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "user_agent", validate_user_agent(self.user_agent))


def validate_user_agent(value: object) -> str:
    """Check a contact string without ever repeating it in an error.

    The SEC's guidance is a company/project name plus an administrative contact
    email, so ``@`` is required. Control characters are refused because this
    string goes straight into an HTTP header, where a newline would let a
    malformed value inject a second header.
    """
    if not isinstance(value, str):
        raise ConfigError(f"{SEC_USER_AGENT_VAR} must be a string")
    text = value.strip()
    if not text:
        raise ConfigError(f"{SEC_USER_AGENT_VAR} is empty")
    if any(ord(character) < 32 or ord(character) == 127 for character in text):
        raise ConfigError(
            f"{SEC_USER_AGENT_VAR} contains control characters and cannot be sent "
            "as an HTTP header"
        )
    if not MIN_LENGTH <= len(text) <= MAX_LENGTH:
        raise ConfigError(
            f"{SEC_USER_AGENT_VAR} must be {MIN_LENGTH}-{MAX_LENGTH} characters, "
            f"got {len(text)}"
        )
    if "@" not in text:
        raise ConfigError(
            f"{SEC_USER_AGENT_VAR} must include a contact email address, as the SEC "
            "asks automated clients to identify themselves"
        )
    return text


def read_sec_contact(environ: dict[str, str] | None = None) -> SecContact | None:
    """The configured contact, or ``None`` when EDGAR should stay switched off.

    ``environ`` is injectable so tests never depend on the developer's shell.
    An invalid value is treated exactly like an absent one -- switched off, with
    a message that names the variable and quotes nothing.
    """
    source = os.environ if environ is None else environ
    raw = source.get(SEC_USER_AGENT_VAR)
    if raw is None:
        return None
    try:
        return SecContact(raw)
    except ConfigError:
        return None


def describe_configuration(environ: dict[str, str] | None = None) -> str:
    """One line for the UI. Says configured or not; never the value."""
    return (
        "EDGAR contact configured"
        if read_sec_contact(environ) is not None
        else UNCONFIGURED_MESSAGE
    )


__all__ = [
    "SEC_USER_AGENT_VAR",
    "UNCONFIGURED_MESSAGE",
    "MIN_LENGTH",
    "MAX_LENGTH",
    "ConfigError",
    "SecContact",
    "validate_user_agent",
    "read_sec_contact",
    "describe_configuration",
]
