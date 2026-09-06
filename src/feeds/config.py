"""Which feeds this installation is allowed to fetch.

Feeds are an allowlist. Nothing typed into the dashboard becomes a request, and
nothing is discovered: a URL is fetched only because it is written in a local
configuration file the user controls.

That file is still untrusted input -- a typo or a pasted line can point at a
local address just as easily as an attacker could -- so it is validated as
strictly as anything arriving over the network: size, count, slug shape, scheme,
host, limits and uniqueness.

Configuration fields do not all mean the same thing, and the difference matters
once records exist:

* **identity-bearing** (``source_id``, ``type``, ``url``) -- changing one means
  a different endpoint, so cached transport validators must be discarded;
* **association/trust** (``declared_trust_class``, ``configured_symbols``) --
  changing one changes what *future* observations mean, never past ones;
* **display-only** (``display_name``) -- changes nothing that was recorded.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

from .identity import config_fingerprint, endpoint_fingerprint
from .models import (
    MAX_CONFIG_BYTES,
    MAX_DISPLAY_NAME,
    MAX_SOURCES,
    MAX_SYMBOLS_PER_SOURCE,
    DeclaredTrustClass,
    FeedError,
    FeedFormat,
    require_source_id,
    require_symbol,
    require_text,
)
from .validation import UnsafeDestination, resolve_safely, validate_url

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_DIR = REPO_ROOT / "config"
LOCAL_CONFIG_NAME = "external_feeds.local.json"
EXAMPLE_CONFIG_NAME = "external_feeds.example.json"

#: Bumped when the meaning of the file changes. An unknown version is refused
#: rather than guessed at: a later writer may have changed what a field means.
CONFIG_SCHEMA_VERSION = 1


class ConfigError(FeedError):
    """Raised when the feed configuration cannot be used as written."""


@dataclass(frozen=True)
class FeedDefinition:
    """One configured feed. Immutable once validated."""

    source_id: str
    feed_format: FeedFormat
    url: str
    display_name: str
    declared_trust_class: DeclaredTrustClass
    configured_symbols: tuple[str, ...] = ()
    enabled: bool = True

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "source_id", require_source_id(self.source_id))
        set_(self, "feed_format", FeedFormat(self.feed_format))
        set_(self, "url", validate_url(self.url, label="feed url"))
        set_(self, "display_name",
             require_text(self.display_name, "display_name", maximum=MAX_DISPLAY_NAME))
        set_(self, "declared_trust_class", DeclaredTrustClass(self.declared_trust_class))
        symbols = tuple(require_symbol(symbol) for symbol in self.configured_symbols)
        if len(symbols) > MAX_SYMBOLS_PER_SOURCE:
            raise ConfigError(
                f"{self.source_id}: at most {MAX_SYMBOLS_PER_SOURCE} configured "
                f"symbols, got {len(symbols)}"
            )
        if len(set(symbols)) != len(symbols):
            raise ConfigError(f"{self.source_id}: duplicate configured symbols")
        set_(self, "configured_symbols", symbols)
        if not isinstance(self.enabled, bool):
            raise ConfigError(f"{self.source_id}: enabled must be a boolean")

    @property
    def host(self) -> str:
        return (urlsplit(self.url).hostname or "").lower()

    @property
    def config_fingerprint(self) -> str:
        """Identity + trust + symbols: everything that changes what a record means."""
        return config_fingerprint(
            source_id=self.source_id,
            feed_format=self.feed_format.value,
            url=self.url,
            declared_trust_class=self.declared_trust_class.value,
            configured_symbols=self.configured_symbols,
        )

    @property
    def endpoint_fingerprint(self) -> str:
        """Identity-bearing fields only; keys the cached transport validators."""
        return endpoint_fingerprint(
            source_id=self.source_id,
            feed_format=self.feed_format.value,
            url=self.url,
        )

    def check_destination(self) -> None:
        """Refuse a feed whose host resolves anywhere forbidden.

        Called at load time so a bad entry is reported before any refresh, and
        again inside the transport for the address actually connected to.
        """
        resolve_safely(self.host)


@dataclass(frozen=True)
class FeedConfiguration:
    """Every configured feed, validated."""

    sources: tuple[FeedDefinition, ...]
    schema_version: int = CONFIG_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "sources", tuple(self.sources))
        ids = [source.source_id for source in self.sources]
        duplicates = sorted({name for name in ids if ids.count(name) > 1})
        if duplicates:
            raise ConfigError(f"duplicate source_id in configuration: {duplicates}")
        if len(self.sources) > MAX_SOURCES:
            raise ConfigError(
                f"at most {MAX_SOURCES} configured feeds, got {len(self.sources)}"
            )

    @property
    def enabled(self) -> tuple[FeedDefinition, ...]:
        return tuple(source for source in self.sources if source.enabled)

    def get(self, source_id: str) -> FeedDefinition | None:
        for source in self.sources:
            if source.source_id == source_id:
                return source
        return None


def parse_configuration(payload: object) -> FeedConfiguration:
    """Build a configuration from already-decoded JSON."""
    if not isinstance(payload, Mapping):
        raise ConfigError(
            f"configuration must be a JSON object, got {type(payload).__name__}"
        )
    version = payload.get("schema_version")
    if version != CONFIG_SCHEMA_VERSION:
        raise ConfigError(
            f"configuration declares schema_version {version!r}, but this build "
            f"understands only {CONFIG_SCHEMA_VERSION}; refusing to interpret it"
        )
    raw_sources = payload.get("sources")
    if not isinstance(raw_sources, Sequence) or isinstance(raw_sources, (str, bytes)):
        raise ConfigError("configuration 'sources' must be a list")
    if len(raw_sources) > MAX_SOURCES:
        raise ConfigError(f"at most {MAX_SOURCES} configured feeds")

    definitions = []
    for index, entry in enumerate(raw_sources):
        if not isinstance(entry, Mapping):
            raise ConfigError(f"source #{index} must be a JSON object")
        try:
            definitions.append(
                FeedDefinition(
                    source_id=entry.get("source_id"),
                    feed_format=_parse_format(entry.get("type")),
                    url=entry.get("url"),
                    display_name=entry.get("display_name"),
                    declared_trust_class=_parse_trust(entry.get("declared_trust_class")),
                    configured_symbols=tuple(entry.get("configured_symbols") or ()),
                    enabled=bool(entry.get("enabled", True)),
                )
            )
        except FeedError as exc:
            raise ConfigError(f"source #{index}: {exc}") from exc
    return FeedConfiguration(tuple(definitions))


def _parse_format(value: object) -> FeedFormat:
    if not isinstance(value, str):
        raise ConfigError("type must be a string ('RSS' or 'ATOM')")
    try:
        return FeedFormat(value.strip().lower())
    except ValueError:
        raise ConfigError(
            f"unsupported type {value!r}; only 'RSS' and 'ATOM' are supported"
        ) from None


def _parse_trust(value: object) -> DeclaredTrustClass:
    if not isinstance(value, str):
        raise ConfigError("declared_trust_class must be a string")
    try:
        return DeclaredTrustClass(value.strip().lower())
    except ValueError:
        supported = ", ".join(t.value for t in DeclaredTrustClass)
        raise ConfigError(
            f"unsupported declared_trust_class {value!r}; supported: {supported}"
        ) from None


def load_configuration(path: str | Path | None = None) -> FeedConfiguration:
    """Read the local configuration, or return an empty one if absent.

    Absence is normal: a fresh checkout has no configured feeds and the panel
    simply says so. The file size is checked before reading, so an enormous
    file cannot be loaded into memory just to be rejected.
    """
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_DIR / LOCAL_CONFIG_NAME
    if not config_path.is_file():
        return FeedConfiguration(())
    size = config_path.stat().st_size
    if size > MAX_CONFIG_BYTES:
        raise ConfigError(
            f"{config_path.name} is {size} bytes, over the {MAX_CONFIG_BYTES}-byte limit"
        )
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{config_path.name} is not valid UTF-8 JSON: {exc}") from exc
    return parse_configuration(payload)


__all__ = [
    "CONFIG_SCHEMA_VERSION",
    "DEFAULT_CONFIG_DIR",
    "LOCAL_CONFIG_NAME",
    "EXAMPLE_CONFIG_NAME",
    "ConfigError",
    "FeedDefinition",
    "FeedConfiguration",
    "parse_configuration",
    "load_configuration",
]
