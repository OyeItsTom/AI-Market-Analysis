"""The one module of FUTURE_VALIDATION_V1 that touches the filesystem.

    <prospective root>/validation/<validation_id>/<fingerprint>/unlock.json   write-once
    <prospective root>/validation/<validation_id>/<fingerprint>/result.json   write-once
    <prospective root>/validation/<validation_id>/<fingerprint>/report.md     write-once

The directory is named by the definition's full fingerprint, so a run under
any other definition -- even one reusing the id -- can never occupy (or
block) the frozen definition's one opening.

Input snapshot
--------------
:func:`capture` reads the activation manifest, the run log and every file of
the outcome ledger into memory -- the caller holds the collection root's
shared lock, so no collector is mutating them -- and records each file's
length and SHA-256. The analysis never reads the live files again: it reads
:func:`materialize`'s private temporary copy of exactly those bytes. After a
crash between the unlock and the result, :func:`recapture` re-reads only the
recorded prefix of each recorded file and refuses (:class:`SnapshotMismatch`)
if any prefix changed, shrank or vanished, or if the manifest changed at all;
anything appended later is ignored.

A symbolic link or any non-regular entry under the ledger is
:class:`UnsupportedEntry`: evidence that cannot be excluded safely. Names the
provenance policy ignores (``.DS_Store``) are neither read nor recorded.

Write-once
----------
Each artifact is written to a private temporary name, fsynced and then
hard-linked to its final name, which fails if the name exists: a reader sees
either no artifact or a complete one, and nothing is ever replaced. The
directory is created only inside an existing prospective root.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping

from src.prospective.provenance import IGNORED_LEDGER_NAMES
from src.prospective.store import LEDGER_DIR, LOCK_NAME, MANIFEST_NAME, RUN_LOG_NAME

VALIDATION_DIR = "validation"
UNLOCK_NAME = "unlock.json"
RESULT_NAME = "result.json"
REPORT_NAME = "report.md"

MATCH_EXACT = "exact"
MATCH_PREFIX = "prefix"


class ValidationStoreError(RuntimeError):
    """Base class for store refusals."""


class UnsupportedEntry(ValidationStoreError):
    """The ledger holds a symbolic link or a non-regular entry."""


class SnapshotMismatch(ValidationStoreError):
    """A recorded input no longer has the recorded bytes as its prefix."""


class ArtifactExists(ValidationStoreError):
    """A write-once artifact already exists."""


class RootMissing(ValidationStoreError):
    """The prospective root does not exist; nothing is created."""


@dataclass(frozen=True)
class SnapshotFile:
    path: str
    data: bytes
    match: str

    @property
    def length(self) -> int:
        return len(self.data)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


@dataclass(frozen=True)
class InputSnapshot:
    """The frozen input bytes, in path order."""

    files: tuple[SnapshotFile, ...]
    directories: tuple[str, ...]

    def payload(self) -> dict[str, Any]:
        return {
            "directories": list(self.directories),
            "files": [{"length": f.length, "match": f.match, "path": f.path,
                       "sha256": f.sha256} for f in self.files],
        }

    @property
    def identity(self) -> str:
        """SHA-256 of the canonical JSON of :meth:`payload`."""
        text = json.dumps(self.payload(), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True)
        return hashlib.sha256(text.encode("ascii")).hexdigest()

    def data(self, path: str) -> bytes | None:
        for item in self.files:
            if item.path == path:
                return item.data
        return None


def _read_regular(path: Path) -> bytes:
    info = os.lstat(path)
    if not stat.S_ISREG(info.st_mode):
        raise UnsupportedEntry(f"{path.name} is not a regular file")
    with open(path, "rb") as handle:
        return handle.read()


def capture(root: str | Path) -> InputSnapshot:
    """Read the collection's evidence into memory. The caller holds the root's shared lock."""
    root = Path(root)
    files: list[SnapshotFile] = [SnapshotFile(MANIFEST_NAME, _read_regular(root / MANIFEST_NAME),
                                              MATCH_EXACT)]
    run_log = root / RUN_LOG_NAME
    files.append(SnapshotFile(RUN_LOG_NAME,
                              _read_regular(run_log) if os.path.lexists(run_log) else b"",
                              MATCH_PREFIX))
    directories: list[str] = []
    ledger = root / LEDGER_DIR
    if os.path.lexists(ledger):
        if not stat.S_ISDIR(os.lstat(ledger).st_mode):
            raise UnsupportedEntry("the ledger root is not a directory")
        directories.append(LEDGER_DIR)
        for current, dirs, names in os.walk(ledger, followlinks=False):
            base = Path(current)
            for name in sorted(dirs):
                if stat.S_ISLNK(os.lstat(base / name).st_mode):
                    raise UnsupportedEntry("the ledger holds a symbolic link")
                directories.append((base / name).relative_to(root).as_posix())
            for name in sorted(names):
                if name in IGNORED_LEDGER_NAMES:
                    continue
                path = base / name
                files.append(SnapshotFile(path.relative_to(root).as_posix(),
                                          _read_regular(path), MATCH_PREFIX))
    return InputSnapshot(files=tuple(sorted(files, key=lambda f: f.path)),
                         directories=tuple(sorted(directories)))


def recapture(root: str | Path, recorded: Mapping[str, Any]) -> InputSnapshot:
    """Re-read exactly the recorded inputs; refuse unless every recorded prefix is intact."""
    root = Path(root)
    files: list[SnapshotFile] = []
    for entry in recorded["files"]:
        path = root / entry["path"]
        length = entry["length"]
        if not os.path.lexists(path):
            if length == 0 and entry["match"] == MATCH_PREFIX:
                files.append(SnapshotFile(entry["path"], b"", MATCH_PREFIX))
                continue
            raise SnapshotMismatch(f"{entry['path']} vanished")
        data = _read_regular(path)
        if entry["match"] == MATCH_EXACT and len(data) != length:
            raise SnapshotMismatch(f"{entry['path']} changed length")
        if len(data) < length:
            raise SnapshotMismatch(f"{entry['path']} is shorter than its frozen prefix")
        prefix = data[:length]
        if hashlib.sha256(prefix).hexdigest() != entry["sha256"]:
            raise SnapshotMismatch(f"{entry['path']} no longer has its frozen prefix")
        files.append(SnapshotFile(entry["path"], prefix, entry["match"]))
    snapshot = InputSnapshot(files=tuple(files), directories=tuple(recorded["directories"]))
    if snapshot.payload() != dict(recorded):
        raise SnapshotMismatch("the recaptured snapshot differs from the recorded one")
    return snapshot


@contextmanager
def materialize(snapshot: InputSnapshot) -> Iterator[Path]:
    """A private temporary collection root holding exactly the snapshot's bytes."""
    holder = tempfile.mkdtemp(prefix="future-validation-")
    try:
        root = Path(holder) / "root"
        root.mkdir()
        for directory in snapshot.directories:
            (root / directory).mkdir(parents=True, exist_ok=True)
        for item in snapshot.files:
            target = root / item.path
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "wb") as handle:
                handle.write(item.data)
        (root / LOCK_NAME).touch()
        yield root
    finally:
        shutil.rmtree(holder, ignore_errors=True)


class ValidationArtifacts:
    """The write-once artifacts of one validation. Constructing it touches nothing."""

    def __init__(self, prospective_root: str | Path, validation_id: str,
                 fingerprint: str) -> None:
        self.prospective_root = Path(prospective_root)
        self.directory = self.prospective_root / VALIDATION_DIR / validation_id / fingerprint

    def path(self, name: str) -> Path:
        return self.directory / name

    def exists(self, name: str) -> bool:
        return os.path.lexists(self.path(name))

    def read(self, name: str) -> bytes | None:
        path = self.path(name)
        if not os.path.lexists(path):
            return None
        return _read_regular(path)

    def write_once(self, name: str, data: bytes) -> None:
        """Create ``name`` with ``data`` atomically; :class:`ArtifactExists` if present."""
        if not self.prospective_root.is_dir():
            raise RootMissing("the prospective root does not exist")
        (self.prospective_root / VALIDATION_DIR).mkdir(exist_ok=True)
        self.directory.parent.mkdir(exist_ok=True)
        self.directory.mkdir(exist_ok=True)
        final = self.path(name)
        temporary = self.directory / f".{name}.{uuid.uuid4().hex}.tmp"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        try:
            view = memoryview(data)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            os.link(temporary, final)
        except FileExistsError as exc:
            raise ArtifactExists(f"{name} already exists; it is never replaced") from exc
        finally:
            os.unlink(temporary)
        directory = os.open(self.directory, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


__all__ = [
    "VALIDATION_DIR",
    "UNLOCK_NAME",
    "RESULT_NAME",
    "REPORT_NAME",
    "MATCH_EXACT",
    "MATCH_PREFIX",
    "ValidationStoreError",
    "UnsupportedEntry",
    "SnapshotMismatch",
    "ArtifactExists",
    "RootMissing",
    "SnapshotFile",
    "InputSnapshot",
    "capture",
    "recapture",
    "materialize",
    "ValidationArtifacts",
]
