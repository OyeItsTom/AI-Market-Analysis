"""Facts about the running environment that activation records: repository and versions.

Activation must happen from a clean working tree whose HEAD is the commit
the operator names, and the named M2 pre-registration commit must be in
HEAD's history. Only this adapter runs ``git``, read-only (``rev-parse
HEAD``, ``status --porcelain``, ``merge-base --is-ancestor``); the
application layer receives its answers through a small probe protocol, so
tests inject one and never depend on the repository they run in. Nothing
here touches the network.
"""

from __future__ import annotations

import platform
import subprocess
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path


class RepositoryProbeError(RuntimeError):
    """``git`` could not report the repository's state."""


@dataclass(frozen=True)
class RepositoryState:
    """The repository as activation sees it."""

    head: str
    clean: bool


class GitRepositoryProbe:
    """Reads HEAD and working-tree cleanliness of one repository. Read-only."""

    def __init__(self, repository_root: str | Path) -> None:
        self.repository_root = Path(repository_root)

    def _git(self, *arguments: str) -> str:
        try:
            completed = subprocess.run(
                ["git", "-C", str(self.repository_root), *arguments],
                capture_output=True, text=True, check=True, timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RepositoryProbeError(f"git {arguments[0]} failed") from exc
        return completed.stdout

    def is_ancestor_of_head(self, commit: str) -> bool:
        """Whether ``commit`` exists and is HEAD or one of its ancestors."""
        try:
            completed = subprocess.run(
                ["git", "-C", str(self.repository_root), "merge-base", "--is-ancestor",
                 commit, "HEAD"],
                capture_output=True, text=True, check=False, timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RepositoryProbeError("git merge-base failed") from exc
        # 0: ancestor; 1: not an ancestor; anything else: unknown commit.
        return completed.returncode == 0

    def repository_state(self) -> RepositoryState:
        head = self._git("rev-parse", "HEAD").strip()
        status = self._git("status", "--porcelain", "--untracked-files=normal")
        return RepositoryState(head=head, clean=status.strip() == "")


#: Distributions whose versions activation records.
RECORDED_DISTRIBUTIONS = ("yfinance", "pandas")


def dependency_versions() -> dict[str, str]:
    """Python and the market-data stack's installed versions, for provenance."""
    versions = {"python": platform.python_version()}
    for name in RECORDED_DISTRIBUTIONS:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = "unavailable"
    return versions


__all__ = [
    "RepositoryProbeError",
    "RepositoryState",
    "GitRepositoryProbe",
    "RECORDED_DISTRIBUTIONS",
    "dependency_versions",
]
