"""Prospective Collection v1: frozen definition, activation manifest, run log, lock.

The outcome ledger itself is Phase 12's (``src.outcomes``), used unchanged
under this collection's own root. This package holds what Phase 12 does not:
the frozen collection definition and its time rules, the write-once
activation manifest, the operational run log, the root lock, and the
repository/version probe activation records. Every record here is Level 1
(identities, clocks, counts, bar timestamps, status classes); none carries a
price, a return or a research state. See ``docs/prospective_collection.md``
and ADR 0013.
"""

from .definition import (
    COLLECTION_V1,
    COLLECTION_WINDOW_END,
    COLLECTION_WINDOW_START,
    NEW_YORK,
    CollectionDefinition,
    DefinitionError,
    HypothesisPin,
    first_non_midnight,
    in_collection_window,
    is_current_tail,
    is_new_york_midnight,
    is_pre_activation,
    missed_tails,
    new_york_date,
    settles_at,
    validate_commit_sha,
)
from .environment import (
    GitRepositoryProbe,
    RepositoryProbeError,
    RepositoryState,
    dependency_versions,
)
from .records import (
    SUCCESS_STATUSES,
    ActivationManifest,
    CollectionStatus,
    RecordError,
    RunRecord,
    RunStatus,
    SymbolRun,
)
from .store import (
    ManifestCorruption,
    ManifestExistsError,
    NotActivatedError,
    ProspectiveStore,
    ProspectiveStoreError,
    RootLockedError,
    RunLogCorruption,
)

__all__ = [
    "COLLECTION_V1",
    "COLLECTION_WINDOW_END",
    "COLLECTION_WINDOW_START",
    "NEW_YORK",
    "CollectionDefinition",
    "DefinitionError",
    "HypothesisPin",
    "first_non_midnight",
    "in_collection_window",
    "is_current_tail",
    "is_new_york_midnight",
    "is_pre_activation",
    "missed_tails",
    "new_york_date",
    "settles_at",
    "validate_commit_sha",
    "GitRepositoryProbe",
    "RepositoryProbeError",
    "RepositoryState",
    "dependency_versions",
    "SUCCESS_STATUSES",
    "ActivationManifest",
    "CollectionStatus",
    "RecordError",
    "RunRecord",
    "RunStatus",
    "SymbolRun",
    "ManifestCorruption",
    "ManifestExistsError",
    "NotActivatedError",
    "ProspectiveStore",
    "ProspectiveStoreError",
    "RootLockedError",
    "RunLogCorruption",
]
