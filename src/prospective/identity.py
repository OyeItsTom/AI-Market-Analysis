"""Activation identity: the pinned M2A pre-registration and the dependency-environment contract.

Pure data and pure functions -- no file, process or clock. The Git adapter
(:mod:`src.prospective.environment`) answers questions about a repository;
the application layer compares those answers with the pins here.

**M2A binding.** Prospective Collection v1 is activated for exactly one
pre-registered future validation: ``FUTURE_VALIDATION_V1`` frozen at commit
:data:`M2A_PREREGISTRATION_COMMIT`. The commit is hard-pinned, never chosen by
an operator. Three files carry the pre-registration's science and are bound by
the SHA-256 of their bytes *at that commit*:

* ``src/research/future_validation.py`` -- the frozen question and policy;
* ``src/research/future_validation_engine.py`` -- the frozen computation;
* ``docs/research/future_validation_v1.md`` -- the human-readable pre-registration.

Activation, health and the future-validation runner require that the commit
exists, is in HEAD's history, holds exactly these bytes at these paths, and
that the same paths are byte-identical in HEAD and in the working tree. Other
code (runner, store, CLI) may receive later operational hardening; these
three may not.

**Dependency environment.** At activation the complete installed distribution
set of the running interpreter is recorded with the interpreter's
implementation and full version; every later collection recomputes it and
refuses on any difference. Names are normalised (PEP 503: lower case, runs of
``-``, ``_`` and ``.`` collapsed to one ``-``) and sorted, so only the *set*
matters, never discovery order; two distributions that normalise to one name
are refused rather than resolved. Nothing machine-specific (paths, timestamps)
is part of it. Its fingerprint is the SHA-256 of the canonical JSON of
``{schema, python_implementation, python_version, packages: [[name, version], ...]}``
(sorted keys, compact separators, ASCII).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

#: The merged M2A pre-registration commit (PR #20). Hard-pinned; never an operator input.
M2A_PREREGISTRATION_COMMIT = "3dac81078b31c4c5856419faae4f2749cc43ede5"
#: ``FUTURE_VALIDATION_V1``'s fingerprint as frozen at :data:`M2A_PREREGISTRATION_COMMIT`.
M2A_FUTURE_VALIDATION_FINGERPRINT = (
    "79f7c4da914727ca8884e594ca997b2ab8dfc1a95a7279b110a7cef69cd6d2ab")

#: The only branch activation accepts, and the fetched ref HEAD must equal.
AUTHORITATIVE_BRANCH = "main"
ORIGIN_MAIN_REF = "refs/remotes/origin/main"

DEPENDENCY_SCHEMA = "prospective_dependency_environment_v1"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_NORMALISED_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
_NAME_SEPARATORS = re.compile(r"[-_.]+")


class IdentityError(ValueError):
    """A pinned identity or a dependency environment is malformed."""


def validate_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise IdentityError(f"{label} must be a 64-character lower-case hex SHA-256")
    return value


@dataclass(frozen=True, order=True)
class BoundPath:
    """One file bound to the pre-registration by the SHA-256 of its committed bytes."""

    path: str
    sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.path, str) or not self.path or self.path.startswith(("/", "-")) \
                or ".." in self.path.split("/") or "\\" in self.path:
            raise IdentityError(f"bound path {self.path!r} is not a relative repository path")
        validate_sha256(self.sha256, f"sha256 of {self.path}")

    def to_payload(self) -> dict[str, str]:
        return {"path": self.path, "sha256": self.sha256}


#: The M2A scientific paths, sorted by path, with their bytes' SHA-256 at the commit.
M2A_BOUND_PATHS: tuple[BoundPath, ...] = (
    BoundPath("docs/research/future_validation_v1.md",
              "3cb6fe9b2968c258fa513cf826efbd868b9b7326b9318af615047c0d3307fb19"),
    BoundPath("src/research/future_validation.py",
              "b39d33aeb867c7bb9676c0f39fc910856633b4117e47f77fe0a0c36e84fe6ccf"),
    BoundPath("src/research/future_validation_engine.py",
              "5212d48f234844a8079e3270ae19ef6a9ce057a46530a944668e73772419c5f2"),
)


def bound_paths_from_payload(value: object) -> tuple[BoundPath, ...]:
    """Strictly decode a ``[{path, sha256}, ...]`` list, sorted and unique by path."""
    if not isinstance(value, list):
        raise IdentityError("bound paths must be a list")
    paths: list[BoundPath] = []
    for entry in value:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
            raise IdentityError("a bound path must be exactly {path, sha256}")
        paths.append(BoundPath(entry["path"], entry["sha256"]))
    if [p.path for p in paths] != sorted({p.path for p in paths}):
        raise IdentityError("bound paths must be sorted by path and unique")
    return tuple(paths)


# -- dependency environment ---------------------------------------------------------------------


def normalise_distribution_name(name: object) -> str:
    """PEP 503 normalisation; refuses anything that is not a distribution name."""
    if not isinstance(name, str) or not name.strip():
        raise IdentityError("a distribution has no name")
    normalised = _NAME_SEPARATORS.sub("-", name.strip()).lower()
    if not _NORMALISED_NAME.fullmatch(normalised):
        raise IdentityError(f"distribution name {name!r} is not a valid name")
    return normalised


def _version(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() \
            or not value.isascii() or not value.isprintable():
        raise IdentityError(f"{label} must be a non-empty printable ASCII version string")
    return value


@dataclass(frozen=True)
class DependencyEnvironment:
    """The interpreter and every installed distribution, canonicalised.

    ``packages`` is a tuple of ``(normalised name, version)`` pairs sorted by
    name with no repeated name. Build one from raw discovery data with
    :meth:`from_distributions`; the constructor only accepts canonical input.
    """

    python_implementation: str
    python_version: str
    packages: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        _version(self.python_implementation, "python_implementation")
        _version(self.python_version, "python_version")
        packages = tuple(tuple(pair) for pair in self.packages)
        for pair in packages:
            if len(pair) != 2:
                raise IdentityError("a package must be a (name, version) pair")
            name, version = pair
            if normalise_distribution_name(name) != name:
                raise IdentityError(f"package name {name!r} is not normalised")
            _version(version, f"version of {name}")
        names = [name for name, _ in packages]
        if len(set(names)) != len(names):
            raise IdentityError("a distribution name appears more than once")
        if names != sorted(names):
            raise IdentityError("packages must be sorted by name")
        object.__setattr__(self, "packages", packages)

    @classmethod
    def from_distributions(cls, python_implementation: str, python_version: str,
                           distributions: Iterable[tuple[object, object]]
                           ) -> "DependencyEnvironment":
        """Normalise and sort discovered ``(name, version)`` pairs; refuse duplicates."""
        seen: dict[str, str] = {}
        for raw_name, raw_version in distributions:
            name = normalise_distribution_name(raw_name)
            if name in seen:
                raise IdentityError(f"distribution {name!r} is installed more than once")
            seen[name] = _version(raw_version, f"version of {name}")
        return cls(python_implementation, python_version, tuple(sorted(seen.items())))

    def canonical_form(self) -> dict[str, object]:
        return {
            "packages": [[name, version] for name, version in self.packages],
            "python_implementation": self.python_implementation,
            "python_version": self.python_version,
            "schema": DEPENDENCY_SCHEMA,
        }

    def canonical_json(self) -> str:
        return json.dumps(self.canonical_form(), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True)

    @property
    def fingerprint(self) -> str:
        """Full SHA-256 of the canonical JSON."""
        return hashlib.sha256(self.canonical_json().encode("ascii")).hexdigest()

    def to_payload(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "packages": [{"name": name, "version": version} for name, version in self.packages],
            "python_implementation": self.python_implementation,
            "python_version": self.python_version,
            "schema": DEPENDENCY_SCHEMA,
        }

    @classmethod
    def from_payload(cls, payload: object) -> "DependencyEnvironment":
        """Strict decode: exact keys, canonical packages, and a fingerprint that matches."""
        if not isinstance(payload, Mapping) or set(payload) != {
                "fingerprint", "packages", "python_implementation", "python_version", "schema"}:
            raise IdentityError("dependency environment keys differ from the schema")
        if payload["schema"] != DEPENDENCY_SCHEMA:
            raise IdentityError(f"unknown dependency environment schema {payload['schema']!r}")
        packages = payload["packages"]
        if not isinstance(packages, list) or not all(
                isinstance(entry, dict) and set(entry) == {"name", "version"}
                and isinstance(entry["name"], str) and isinstance(entry["version"], str)
                for entry in packages):
            raise IdentityError("packages must be a list of {name, version}")
        environment = cls(payload["python_implementation"], payload["python_version"],
                          tuple((entry["name"], entry["version"]) for entry in packages))
        if validate_sha256(payload["fingerprint"], "dependency fingerprint") \
                != environment.fingerprint:
            raise IdentityError("the dependency fingerprint does not match its packages")
        return environment


__all__ = [
    "M2A_PREREGISTRATION_COMMIT",
    "M2A_FUTURE_VALIDATION_FINGERPRINT",
    "M2A_BOUND_PATHS",
    "AUTHORITATIVE_BRANCH",
    "ORIGIN_MAIN_REF",
    "DEPENDENCY_SCHEMA",
    "IdentityError",
    "BoundPath",
    "DependencyEnvironment",
    "bound_paths_from_payload",
    "normalise_distribution_name",
    "validate_sha256",
]
