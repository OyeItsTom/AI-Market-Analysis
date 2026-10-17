"""Prospective Collection v1: frozen definition, activation manifest, run log, lock.

The outcome ledger itself is Phase 12's (``src.outcomes``), used unchanged
under this collection's own root. This package holds what Phase 12 does not:
the frozen collection definition and its time rules, the write-once
activation manifest, the operational run log (run starts and run records),
the root lock, the repository and dependency-environment probe, the pinned
M2A pre-registration identity and dependency-environment contract
(:mod:`.identity`), and the frozen provenance
policy that reconciles every ledger record with that run log. Every record here is Level 1
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
    DependencyEnvironmentError,
    GitRepositoryProbe,
    RepositoryProbeError,
    RepositoryState,
    capture_dependency_environment,
)
from .identity import (
    AUTHORITATIVE_BRANCH,
    DEPENDENCY_SCHEMA,
    M2A_BOUND_PATHS,
    M2A_FUTURE_VALIDATION_FINGERPRINT,
    M2A_PREREGISTRATION_COMMIT,
    ORIGIN_MAIN_REF,
    BoundPath,
    DependencyEnvironment,
    IdentityError,
    normalise_distribution_name,
)
from .provenance import (
    PROVENANCE_V1,
    ClaimMeta,
    Finding,
    OutcomeMeta,
    PartitionMeta,
    ProvenancePolicy,
    ProvenanceReport,
    provenance_policy_for,
    unknown_report,
    verify_provenance,
)
from .records import (
    SUCCESS_STATUSES,
    ActivationManifest,
    CollectionStatus,
    RecordError,
    RunRecord,
    RunStart,
    RunStatus,
    SymbolRun,
)
from .store import (
    DEFAULT_LOCK_TIMEOUT,
    LockMissingError,
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
    "DependencyEnvironmentError",
    "GitRepositoryProbe",
    "RepositoryProbeError",
    "RepositoryState",
    "capture_dependency_environment",
    "AUTHORITATIVE_BRANCH",
    "DEPENDENCY_SCHEMA",
    "M2A_BOUND_PATHS",
    "M2A_FUTURE_VALIDATION_FINGERPRINT",
    "M2A_PREREGISTRATION_COMMIT",
    "ORIGIN_MAIN_REF",
    "BoundPath",
    "DependencyEnvironment",
    "IdentityError",
    "normalise_distribution_name",
    "PROVENANCE_V1",
    "ClaimMeta",
    "Finding",
    "OutcomeMeta",
    "PartitionMeta",
    "ProvenancePolicy",
    "ProvenanceReport",
    "provenance_policy_for",
    "unknown_report",
    "verify_provenance",
    "SUCCESS_STATUSES",
    "ActivationManifest",
    "CollectionStatus",
    "RecordError",
    "RunRecord",
    "RunStart",
    "RunStatus",
    "SymbolRun",
    "DEFAULT_LOCK_TIMEOUT",
    "LockMissingError",
    "ManifestCorruption",
    "ManifestExistsError",
    "NotActivatedError",
    "ProspectiveStore",
    "ProspectiveStoreError",
    "RootLockedError",
    "RunLogCorruption",
]
