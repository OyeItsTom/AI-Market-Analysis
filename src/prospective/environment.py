"""Facts about the running environment that activation records: repository and dependencies.

Only this adapter runs ``git``, always read-only and always local: it never
fetches, so activation and collection never touch the network. The operator's
fresh ``git fetch origin`` / ``git ls-remote origin refs/heads/main`` preflight
happens before activation, outside this code, and its answer reaches activation
as an explicit argument (see ``docs/prospective_collection.md``). The commands
used are ``rev-parse``, ``status --porcelain``, ``ls-files -v``,
``symbolic-ref``, ``merge-base --is-ancestor``, ``cat-file`` and
``diff --quiet`` between two commits, each with ``core.fsmonitor`` disabled
so that no file-system monitor's cached answer stands in for Git's own scan.
The application layer receives the answers through a small probe protocol,
so tests inject one (or a temporary repository) and never depend on the
repository they run in.

:func:`capture_dependency_environment` reads the installed distribution
metadata of the running interpreter (``importlib.metadata``, standard library
only) for the dependency-drift contract in :mod:`src.prospective.identity`.
Distribution metadata cannot see a package that is importable without it, so
an interpreter whose import path ``PYTHONPATH`` or ``PYTHONHOME`` changes is
refused as unverifiable rather than recorded (:func:`import_path_overrides`).
This is the only environment read in the prospective code, and it can only
refuse.
"""

from __future__ import annotations

import hashlib
import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Iterable, Mapping

from .identity import ORIGIN_MAIN_REF, DependencyEnvironment, IdentityError

#: Interpreter variables that change where imports come from without leaving
#: distribution metadata behind. Set, they make the environment unverifiable.
IMPORT_PATH_VARIABLES = ("PYTHONHOME", "PYTHONPATH")

#: ``git ls-files -v`` tag of a tracked file Git still checks for changes. Every
#: other tag hides the file from ``status`` (``h``/lower case: assume-unchanged,
#: ``S``: skip-worktree) or marks an unmerged entry, so the tree is not clean.
_CHECKED_TAG = b"H "


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
                ["git", "-C", str(self.repository_root), "-c", "core.fsmonitor=false",
                 *arguments],
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
        """HEAD and cleanliness. Clean means ``status`` reports nothing *and* no
        tracked file is hidden from it by an index flag (assume-unchanged,
        skip-worktree): a flagged file is never trusted, edited or not, and the
        flag is reported as dirt, never cleared."""
        head = self._git("rev-parse", "--verify", "HEAD^{commit}").strip()
        status = self._git("status", "--porcelain", "--untracked-files=normal")
        return RepositoryState(head=head,
                               clean=status.strip() == "" and not self._has_hidden_files())

    def _has_hidden_files(self) -> bool:
        listed = self._run("ls-files", "-v", "-z", text=False)
        if listed.returncode != 0:
            raise RepositoryProbeError("git ls-files failed")
        return any(entry[:2] != _CHECKED_TAG for entry in listed.stdout.split(b"\0") if entry)

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


def import_path_overrides(
    variables: Mapping[str, str] | None = None, *, ignore_environment: bool | None = None
) -> tuple[str, ...]:
    """The :data:`IMPORT_PATH_VARIABLES` in effect for this interpreter, sorted.

    A variable is in effect when it is set to a non-empty value and the
    interpreter honours the environment: under ``python -E`` or ``-I``
    (``sys.flags.ignore_environment``) none is. The arguments exist for tests.
    """
    ignored = sys.flags.ignore_environment if ignore_environment is None \
        else ignore_environment
    if ignored:
        return ()
    values = os.environ if variables is None else variables
    return tuple(name for name in IMPORT_PATH_VARIABLES if values.get(name))


def running_python() -> tuple[str, str]:
    """The running interpreter's ``(implementation, version)``, as a capture records them."""
    return platform.python_implementation(), platform.python_version()


def capture_dependency_environment(
    distributions: Iterable[metadata.Distribution] | None = None,
    *,
    python_implementation: str | None = None,
    python_version: str | None = None,
    variables: Mapping[str, str] | None = None,
    ignore_environment: bool | None = None,
) -> DependencyEnvironment:
    """The running interpreter and every distribution visible on its ``sys.path``.

    Raises :class:`DependencyEnvironmentError` -- and never anything else
    short of ``KeyboardInterrupt``/``SystemExit`` -- when ``PYTHONPATH`` or
    ``PYTHONHOME`` is in effect (:func:`import_path_overrides`), when a
    distribution has no name or version, when two normalise to one name, or
    when discovery fails in any unexpected way. The arguments exist for tests.
    """
    overrides = import_path_overrides(variables, ignore_environment=ignore_environment)
    if overrides:
        raise DependencyEnvironmentError(
            f"{','.join(overrides)} is set: imports can bypass the recorded distributions")
    try:
        found = metadata.distributions() if distributions is None else distributions
        pairs = [(dist.metadata["Name"], dist.version) for dist in found]
        implementation, version = running_python()
        return DependencyEnvironment.from_distributions(
            implementation if python_implementation is None else python_implementation,
            version if python_version is None else python_version,
            pairs,
        )
    except (IdentityError, OSError, KeyError, TypeError, ValueError) as exc:
        raise DependencyEnvironmentError(str(exc)) from exc
    except Exception as exc:  # an unexpected failure is still only "unverified"
        raise DependencyEnvironmentError(
            f"unexpected {type(exc).__name__} while reading distributions") from exc


__all__ = [
    "RepositoryProbeError",
    "DependencyEnvironmentError",
    "RepositoryState",
    "GitRepositoryProbe",
    "IMPORT_PATH_VARIABLES",
    "import_path_overrides",
    "running_python",
    "capture_dependency_environment",
]
