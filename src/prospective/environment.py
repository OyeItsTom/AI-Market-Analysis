"""Facts about the running environment that activation records: repository and dependencies.

Only this adapter runs ``git``, always read-only and always local: it never
fetches, so activation and collection never touch the network. The operator's
fresh ``git fetch origin`` / ``git ls-remote origin refs/heads/main`` preflight
happens before activation, outside this code, and its answer reaches activation
as an explicit argument (see ``docs/prospective_collection.md``). The commands
used are ``rev-parse``, ``status --porcelain``, ``symbolic-ref``,
``merge-base --is-ancestor``, ``cat-file`` and ``diff --quiet`` between two
commits. The application layer receives the answers through a small probe
protocol, so tests inject one (or a temporary repository) and never depend on
the repository they run in.

:func:`capture_dependency_environment` reads the installed distribution
metadata of the running interpreter (``importlib.metadata``, standard library
only) for the dependency-drift contract in :mod:`src.prospective.identity`.
"""

from __future__ import annotations

import hashlib
import platform
import subprocess
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Iterable

from .identity import ORIGIN_MAIN_REF, DependencyEnvironment, IdentityError


class RepositoryProbeError(RuntimeError):
    """``git`` could not report the repository's state."""


class DependencyEnvironmentError(RuntimeError):
    """The installed distributions could not be read as a canonical environment."""


@dataclass(frozen=True)
class RepositoryState:
    """The repository as activation sees it."""

    head: str
    clean: bool


class GitRepositoryProbe:
    """Reads one repository's HEAD, refs, objects and cleanliness. Read-only, offline."""

    def __init__(self, repository_root: str | Path) -> None:
        self.repository_root = Path(repository_root)

    def _run(self, *arguments: str, text: bool = True) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(
                ["git", "-C", str(self.repository_root), *arguments],
                capture_output=True, text=text, check=False, timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RepositoryProbeError(f"git {arguments[0]} failed") from exc

    def _git(self, *arguments: str) -> str:
        completed = self._run(*arguments)
        if completed.returncode != 0:
            raise RepositoryProbeError(f"git {arguments[0]} failed")
        return completed.stdout

    def is_ancestor_of_head(self, commit: str) -> bool:
        """Whether ``commit`` exists and is HEAD or one of its ancestors."""
        completed = self._run("merge-base", "--is-ancestor", commit, "HEAD")
        # 0: ancestor; 1: not an ancestor; anything else: unknown commit.
        return completed.returncode == 0

    def repository_state(self) -> RepositoryState:
        head = self._git("rev-parse", "--verify", "HEAD^{commit}").strip()
        status = self._git("status", "--porcelain", "--untracked-files=normal")
        return RepositoryState(head=head, clean=status.strip() == "")

    def current_branch(self) -> str | None:
        """The checked-out branch's short name; ``None`` on a detached HEAD."""
        completed = self._run("symbolic-ref", "--quiet", "HEAD")
        if completed.returncode == 1:
            return None
        if completed.returncode != 0:
            raise RepositoryProbeError("git symbolic-ref failed")
        ref = completed.stdout.strip()
        return ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else None

    def origin_main(self) -> str | None:
        """The locally fetched ``refs/remotes/origin/main`` commit, or ``None``. No fetch."""
        completed = self._run("rev-parse", "--verify", "--quiet",
                              f"{ORIGIN_MAIN_REF}^{{commit}}")
        if completed.returncode != 0:
            return None
        return completed.stdout.strip() or None

    def commit_exists(self, commit: str) -> bool:
        """Whether ``commit`` names a commit object in this repository."""
        return self._run("cat-file", "-e", f"{commit}^{{commit}}").returncode == 0

    def blob_sha256(self, commit: str, path: str) -> str | None:
        """SHA-256 of ``path``'s bytes at ``commit``; ``None`` unless it is a blob there."""
        spec = f"{commit}:{path}"
        kind = self._run("cat-file", "-t", spec)
        if kind.returncode != 0 or kind.stdout.strip() != "blob":
            return None
        blob = self._run("cat-file", "blob", spec, text=False)
        if blob.returncode != 0:
            raise RepositoryProbeError("git cat-file failed")
        return hashlib.sha256(blob.stdout).hexdigest()

    def working_file_sha256(self, path: str) -> str | None:
        """SHA-256 of ``path`` in the working tree; ``None`` unless a regular, non-link file."""
        target = self.repository_root / path
        if target.is_symlink() or not target.is_file():
            return None
        try:
            return hashlib.sha256(target.read_bytes()).hexdigest()
        except OSError as exc:
            raise RepositoryProbeError("a working-tree file could not be read") from exc

    def paths_unchanged_since(self, commit: str, paths: Iterable[str]) -> bool:
        """Whether ``paths`` are identical between ``commit`` and HEAD (committed trees)."""
        completed = self._run("diff", "--quiet", "--no-ext-diff", "--no-textconv", commit,
                              "HEAD", "--", *paths)
        if completed.returncode not in (0, 1):
            raise RepositoryProbeError("git diff failed")
        return completed.returncode == 0


def capture_dependency_environment(
    distributions: Iterable[metadata.Distribution] | None = None,
    *,
    python_implementation: str | None = None,
    python_version: str | None = None,
) -> DependencyEnvironment:
    """The running interpreter and every distribution visible on its ``sys.path``.

    Raises :class:`DependencyEnvironmentError` when a distribution has no name
    or version, or two normalise to one name. The arguments exist for tests.
    """
    found = metadata.distributions() if distributions is None else distributions
    try:
        pairs = [(dist.metadata["Name"], dist.version) for dist in found]
        return DependencyEnvironment.from_distributions(
            platform.python_implementation() if python_implementation is None
            else python_implementation,
            platform.python_version() if python_version is None else python_version,
            pairs,
        )
    except (IdentityError, OSError, KeyError, TypeError, ValueError) as exc:
        raise DependencyEnvironmentError(str(exc)) from exc


__all__ = [
    "RepositoryProbeError",
    "DependencyEnvironmentError",
    "RepositoryState",
    "GitRepositoryProbe",
    "capture_dependency_environment",
]
