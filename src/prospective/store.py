"""The one module in Prospective Collection v1 that touches the filesystem.

    <root>/collect.lock      advisory lock file (holds no data), created at activation
    <root>/activation.json   write-once activation manifest
    <root>/runs.jsonl        append-only operational run log (run starts and run records)
    <root>/ledger/           the Phase 12 outcome ledger root for this collection

Nothing here creates the root on a read. The root is created only by
:meth:`ProspectiveStore.write_manifest`, which refuses a root that already
holds anything, creates the lock file first and the manifest second (both
``O_EXCL``), so an activated root always has its lock: if the lock cannot
be created no manifest exists and the root is simply not activated (a later
failure can leave a partial or even complete manifest -- see
:meth:`ProspectiveStore.write_manifest`). Run-log
lines are appended with one ``write``, ``flush`` and ``fsync``; a read is
strict and a torn or non-canonical line is :class:`RunLogCorruption` with
its line number, never skipped or repaired.

Locking is ``fcntl.flock`` on ``collect.lock``, opened read-only and never
created by a lock request: the collector takes it **exclusively**, waiting a
bounded time (a reader may hold it briefly); ``health`` takes it **shared and
non-blocking**, so it never inspects files a collector is mutating. A
missing lock file on an activated root is :class:`LockMissingError` -- fail
closed, never recreated silently. The kernel releases a lock when the
holding process exits for any reason, so a crashed collector leaves no
stale lock to break.
"""

from __future__ import annotations

import errno
import fcntl
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

from .records import ActivationManifest, RecordError, RunRecord, RunStart, decode_run_log_line

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


class LockMissingError(ProspectiveStoreError):
    """An activated root has no lock file; nothing recreates it silently."""


#: How long the collector waits for its exclusive lock by default (seconds).
DEFAULT_LOCK_TIMEOUT = 30.0
#: Interval between exclusive-lock attempts while waiting (seconds).
LOCK_POLL_INTERVAL = 0.25

_WOULD_BLOCK = (errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES)


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

    def lock_exists(self) -> bool:
        return self.lock_path.is_file()

    def read_run_log(self) -> tuple[RunStart | RunRecord, ...]:
        """Every run-log entry (starts and records) in append order; strict, all or nothing."""
        if not self.run_log_path.exists():
            return ()
        data = self.run_log_path.read_bytes()
        if data and not data.endswith(b"\n"):
            last = data.count(b"\n") + 1
            raise RunLogCorruption(last, "final line has no newline (torn write)")
        entries: list[RunStart | RunRecord] = []
        for number, line in enumerate(data.splitlines(keepends=True), start=1):
            try:
                entries.append(decode_run_log_line(line[:-1]))
            except RecordError as exc:
                raise RunLogCorruption(number, str(exc)) from exc
        return tuple(entries)

    def iter_runs(self) -> Iterator[RunRecord]:
        """Every run *record* in append order (run starts skipped); strict."""
        for entry in self.read_run_log():
            if isinstance(entry, RunRecord):
                yield entry

    # -- writes --------------------------------------------------------------------------

    def write_manifest(self, manifest: ActivationManifest) -> None:
        """Create the root, its lock file, then the manifest, once. Refuses a non-empty root.

        The lock file is created first: if that fails there is no manifest
        and the root is not activated. A failure while writing the manifest
        leaves no or a partial manifest; a failure in a later fsync (of the
        manifest or the root directory) may leave a complete manifest whose
        durability is unconfirmed. In every case the caller sees the error,
        nothing is cleaned up, and activation refuses the non-empty root
        until an operator inspects it.
        """
        if self.root.exists():
            if not self.root.is_dir() or any(self.root.iterdir()):
                raise ManifestExistsError(
                    "the prospective root already exists and is not empty; activation "
                    "is write-once and never reuses a root"
                )
        payload = manifest.to_bytes()
        self.root.mkdir(parents=True, exist_ok=True)
        lock = os.open(self.lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        try:
            os.fsync(lock)
        finally:
            os.close(lock)
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
        self._append_line(record.to_line())

    def append_run_start(self, start: RunStart) -> None:
        """Append one run-start record (durable before any provider work)."""
        self._append_line(start.to_line())

    def _append_line(self, line: bytes) -> None:
        if not self.manifest_path.exists():
            raise NotActivatedError("run-log lines are written only to an activated root")
        with self.run_log_path.open("ab") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())

    def _open_lock(self) -> int:
        """The lock file, opened read-only; never created here."""
        if not self.manifest_path.exists():
            raise NotActivatedError("only an activated root can be locked")
        try:
            return os.open(self.lock_path, os.O_RDONLY)
        except FileNotFoundError as exc:
            raise LockMissingError(
                "the activated root has no collect.lock; it is never recreated silently"
            ) from exc

    @contextmanager
    def exclusive_lock(
        self,
        *,
        timeout: float = 0.0,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> Iterator[None]:
        """Hold the collection lock exclusively for the body.

        Retries every :data:`LOCK_POLL_INTERVAL` until ``timeout`` seconds of
        the monotonic clock have passed, then :class:`RootLockedError`. The
        default ``timeout=0`` tries exactly once.
        """
        descriptor = self._open_lock()
        try:
            deadline = monotonic() + max(timeout, 0.0)
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if exc.errno not in _WOULD_BLOCK:
                        raise
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        raise RootLockedError("another process holds the root lock") from exc
                    sleep(min(LOCK_POLL_INTERVAL, remaining))
            try:
                yield
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

    @contextmanager
    def shared_lock(self) -> Iterator[None]:
        """Hold the lock shared, non-blocking; :class:`RootLockedError` while a collector runs."""
        descriptor = self._open_lock()
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno in _WOULD_BLOCK:
                    raise RootLockedError("a collection holds the root lock") from exc
                raise
            try:
                yield
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


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
    "LockMissingError",
    "DEFAULT_LOCK_TIMEOUT",
    "LOCK_POLL_INTERVAL",
    "ProspectiveStore",
]
