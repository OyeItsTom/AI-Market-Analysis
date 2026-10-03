"""The one module in Prospective Collection v1 that touches the filesystem.

    <root>/activation.json   write-once activation manifest
    <root>/runs.jsonl        append-only operational run log
    <root>/collect.lock      advisory lock file (holds no data)
    <root>/ledger/           the Phase 12 outcome ledger root for this collection

Nothing here creates the root on a read. The root is created only by
:meth:`ProspectiveStore.write_manifest`, which refuses a root that already
holds anything, and refuses to replace a manifest (``O_EXCL``). Run records
are appended with one ``write``, ``flush`` and ``fsync``; a read is strict and
a torn or non-canonical line is :class:`RunLogCorruption` with its line
number, never skipped or repaired.

The lock is ``fcntl.flock`` (exclusive, non-blocking) on ``collect.lock``. The
kernel releases it when the holding process exits for any reason, so a
crashed collector leaves no stale lock to break; the file itself persists
and is harmless.
"""

from __future__ import annotations

import errno
import fcntl
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .records import ActivationManifest, RecordError, RunRecord

MANIFEST_NAME = "activation.json"
RUN_LOG_NAME = "runs.jsonl"
LOCK_NAME = "collect.lock"
LEDGER_DIR = "ledger"


class ProspectiveStoreError(RuntimeError):
    """Base class for store refusals."""


class ManifestExistsError(ProspectiveStoreError):
    """Activation was attempted on a root that is not empty."""


class ManifestCorruption(ProspectiveStoreError):
    """The activation manifest cannot be read as a canonical manifest."""


class RunLogCorruption(ProspectiveStoreError):
    """A run-log line is torn, non-canonical or not a run record."""

    def __init__(self, line_number: int, reason: str) -> None:
        super().__init__(f"run log line {line_number}: {reason}")
        self.line_number = line_number


class NotActivatedError(ProspectiveStoreError):
    """The root has no activation manifest."""


class RootLockedError(ProspectiveStoreError):
    """Another process holds the collection lock."""


class ProspectiveStore:
    """Files of one prospective collection root. Constructing it touches nothing."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    @property
    def manifest_path(self) -> Path:
        return self.root / MANIFEST_NAME

    @property
    def run_log_path(self) -> Path:
        return self.root / RUN_LOG_NAME

    @property
    def lock_path(self) -> Path:
        return self.root / LOCK_NAME

    @property
    def ledger_root(self) -> Path:
        return self.root / LEDGER_DIR

    # -- reads (never create anything) ---------------------------------------------------

    def root_exists(self) -> bool:
        return self.root.exists()

    def ledger_exists(self) -> bool:
        return self.ledger_root.is_dir()

    def read_manifest(self) -> ActivationManifest | None:
        """The manifest, ``None`` when absent, :class:`ManifestCorruption` when unreadable."""
        if not self.manifest_path.exists():
            return None
        try:
            return ActivationManifest.from_bytes(self.manifest_path.read_bytes())
        except RecordError as exc:
            raise ManifestCorruption(f"activation manifest: {exc}") from exc

    def iter_runs(self) -> Iterator[RunRecord]:
        """Every run record in append order; strict."""
        if not self.run_log_path.exists():
            return
        data = self.run_log_path.read_bytes()
        if data and not data.endswith(b"\n"):
            last = data.count(b"\n") + 1
            raise RunLogCorruption(last, "final line has no newline (torn write)")
        for number, line in enumerate(data.splitlines(keepends=True), start=1):
            try:
                yield RunRecord.from_line(line[:-1])
            except RecordError as exc:
                raise RunLogCorruption(number, str(exc)) from exc

    # -- writes --------------------------------------------------------------------------

    def write_manifest(self, manifest: ActivationManifest) -> None:
        """Create the root and write the manifest once. Refuses a non-empty root."""
        if self.root.exists():
            if not self.root.is_dir() or any(self.root.iterdir()):
                raise ManifestExistsError(
                    "the prospective root already exists and is not empty; activation "
                    "is write-once and never reuses a root"
                )
        self.root.mkdir(parents=True, exist_ok=True)
        payload = manifest.to_bytes()
        try:
            descriptor = os.open(self.manifest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError as exc:
            raise ManifestExistsError("an activation manifest already exists") from exc
        try:
            os.write(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _fsync_directory(self.root)

    def append_run(self, record: RunRecord) -> None:
        """Append one run record. Requires an activated root; never creates one."""
        if not self.manifest_path.exists():
            raise NotActivatedError("run records are written only to an activated root")
        line = record.to_line()
        with self.run_log_path.open("ab") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())

    @contextmanager
    def exclusive_lock(self) -> Iterator[None]:
        """Hold the collection lock for the body; :class:`RootLockedError` if held."""
        if not self.manifest_path.exists():
            raise NotActivatedError("only an activated root can be locked")
        handle = self.lock_path.open("a")
        try:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES):
                    raise RootLockedError("another collection holds the root lock") from exc
                raise
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "MANIFEST_NAME",
    "RUN_LOG_NAME",
    "LOCK_NAME",
    "LEDGER_DIR",
    "ProspectiveStoreError",
    "ManifestExistsError",
    "ManifestCorruption",
    "RunLogCorruption",
    "NotActivatedError",
    "RootLockedError",
    "ProspectiveStore",
]
