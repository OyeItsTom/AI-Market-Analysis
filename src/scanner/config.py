"""Which universes this installation may scan.

**This is the only scanner module that touches the filesystem, and it only
reads.** Keeping the read in one adapter is what lets the pure domain stay pure
and lets the application layer stay free of file primitives.

The file is written by the user, which makes it trusted in intent and untrusted
in content: a typo can name a hundred symbols or a path-shaped id just as easily
as carelessness could. It is validated as strictly as anything arriving over a
network -- size, count, slug shape, symbol shape and uniqueness.

The size limit is enforced twice, and the second time is the one that counts.
``stat`` is a cheap pre-check that avoids opening an obviously huge file, but a
file can grow between the stat and the read, so the read itself is bounded: at
most ``MAX_UNIVERSE_CONFIG_BYTES + 1`` bytes are ever pulled into memory, and
getting that many means the file is over the limit. A stat-only check would make
the guarantee "it was small a moment ago", which is not what a resource bound is
for.

This module is stateless. There is no cached configuration and no module global:
retaining a last-good configuration across a failed reload is a session concern
belonging to the application layer, and hiding it here would make the loader's
behaviour depend on what it had been asked before.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

from .models import (
    MAX_UNIVERSE_CONFIG_BYTES,
    MAX_UNIVERSES,
    ScannerError,
    UniverseConfiguration,
    UniverseLoadReport,
    UniverseSourceKind,
)
from .universe import build_universe

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_DIR = REPO_ROOT / "config"
LOCAL_CONFIG_NAME = "universes.local.json"
EXAMPLE_CONFIG_NAME = "universes.example.json"

#: Bumped when the meaning of the file changes. An unknown version is refused
#: rather than guessed at: a later writer may have changed what a field means.
CONFIG_SCHEMA_VERSION = 1

UNCONFIGURED_MESSAGE = (
    "No scan universes are configured. Copy config/universes.example.json to "
    "config/universes.local.json and edit it. The example file is a template "
    "and is never loaded automatically."
)


class ConfigError(ScannerError):
    """Raised when the universe configuration cannot be used as written."""


def parse_configuration(payload: object) -> UniverseConfiguration:
    """Build a configuration from already-decoded JSON.

    Separate from :func:`load_configuration` so every validation rule is
    testable without a file, and so the file read has exactly one home.
    """
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

    raw = payload.get("universes")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ConfigError("configuration 'universes' must be a list")
    if len(raw) > MAX_UNIVERSES:
        raise ConfigError(f"at most {MAX_UNIVERSES} universes, got {len(raw)}")

    definitions = []
    raw_symbols = 0
    duplicates_removed = 0
    for index, entry in enumerate(raw):
        if not isinstance(entry, Mapping):
            raise ConfigError(f"universe #{index} must be a JSON object")
        label = entry.get("universe_id", f"#{index}")
        symbols = entry.get("symbols")
        if not isinstance(symbols, Sequence) or isinstance(symbols, (str, bytes)):
            raise ConfigError(f"universe {label!r}: 'symbols' must be a list")
        raw_symbols += len(symbols)
        try:
            definition, duplicates = build_universe(
                universe_id=entry.get("universe_id"),
                display_name=entry.get("display_name"),
                symbols=symbols,
                source_kind=_parse_source_kind(entry.get("source_kind"), label),
                source_reference=entry.get("source_reference"),
                as_of=_parse_as_of(entry.get("as_of"), label),
                enabled=bool(entry.get("enabled", True)),
            )
        except ScannerError as exc:
            raise ConfigError(f"universe {label!r}: {exc}") from exc
        definitions.append(definition)
        duplicates_removed += duplicates

    universes = tuple(definitions)
    report = UniverseLoadReport(
        raw_symbol_count=raw_symbols,
        normalized_symbol_count=sum(u.symbol_count for u in universes),
        duplicates_removed=duplicates_removed,
        universes_loaded=len(universes),
        universes_enabled=sum(1 for u in universes if u.enabled),
    )
    try:
        return UniverseConfiguration(
            universes=universes,
            load_report=report,
            schema_version=CONFIG_SCHEMA_VERSION,
        )
    except ScannerError as exc:
        raise ConfigError(str(exc)) from exc


def _parse_source_kind(value: object, label: object) -> UniverseSourceKind:
    if not isinstance(value, str):
        raise ConfigError(f"universe {label!r}: source_kind must be a string")
    try:
        return UniverseSourceKind(value.strip().lower())
    except ValueError:
        supported = ", ".join(k.value for k in UniverseSourceKind)
        raise ConfigError(
            f"universe {label!r}: unsupported source_kind {value!r}; supported: "
            f"{supported}. This system cannot verify index membership, so no "
            "kind claiming verified provenance exists."
        ) from None


def _parse_as_of(value: object, label: object) -> date:
    if not isinstance(value, str):
        raise ConfigError(f"universe {label!r}: as_of must be an ISO date string")
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise ConfigError(
            f"universe {label!r}: as_of {value!r} is not an ISO date (YYYY-MM-DD)"
        ) from None


def _read_bounded(path: Path, limit: int = MAX_UNIVERSE_CONFIG_BYTES) -> str:
    """Read at most ``limit`` bytes, refusing anything larger.

    Asking for one byte past the limit is what makes the check meaningful: if
    that byte arrives, the file is too big, and it is refused without the rest
    of it ever being read. This closes the window a stat-only check leaves open,
    where a file grows between being measured and being read.
    """
    with path.open("rb") as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise ConfigError(
            f"{path.name} exceeds the {limit}-byte limit; refusing to read further"
        )
    return raw.decode("utf-8")


def load_configuration(path: str | Path | None = None) -> UniverseConfiguration:
    """Read the local configuration, or return an empty one if absent.

    Absence is normal, not a failure: a fresh checkout has no local file and the
    panel simply says so. The example file is deliberately **not** used as a
    fallback -- silently scanning symbols the user never chose would be worse
    than showing an empty state.
    """
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_DIR / LOCAL_CONFIG_NAME
    if not config_path.is_file():
        return UniverseConfiguration()

    size = config_path.stat().st_size
    if size > MAX_UNIVERSE_CONFIG_BYTES:
        raise ConfigError(
            f"{config_path.name} is {size} bytes, over the "
            f"{MAX_UNIVERSE_CONFIG_BYTES}-byte limit"
        )
    try:
        text = _read_bounded(config_path)
    except ConfigError:
        raise
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{config_path.name} could not be read: {exc}") from exc
    try:
        # json.loads on text, never json.load on a handle: the size check above
        # is only meaningful if the bytes pass through a bound we control.
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{config_path.name} is not valid JSON: {exc}") from exc
    return parse_configuration(payload)


__all__ = [
    "CONFIG_SCHEMA_VERSION",
    "DEFAULT_CONFIG_DIR",
    "LOCAL_CONFIG_NAME",
    "EXAMPLE_CONFIG_NAME",
    "UNCONFIGURED_MESSAGE",
    "ConfigError",
    "parse_configuration",
    "load_configuration",
]
