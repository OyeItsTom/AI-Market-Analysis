"""Market-data foundation: models, provider abstraction, validation, storage.

Public surface for the rest of the application.  Downstream layers (features,
strategies, backtesting, risk, signals) should import from here and never
from a vendor SDK.
"""

from .models import Interval, MarketBar
from .normalization import NormalizationError, bars_from_records, coerce_timestamp
from .provider import (
    MarketDataProvider,
    ProviderConfigurationError,
    ProviderError,
    ProviderUnavailableError,
)
from .storage import CsvBarStore, SeriesKey, StorageError
from .validation import (
    IssueCode,
    ValidationError,
    ValidationIssue,
    check_bar,
    check_bars,
    is_valid_bar,
    validate_bar,
    validate_bars,
)

__all__ = [
    "Interval",
    "MarketBar",
    "MarketDataProvider",
    "ProviderError",
    "ProviderUnavailableError",
    "ProviderConfigurationError",
    "IssueCode",
    "ValidationIssue",
    "ValidationError",
    "check_bar",
    "check_bars",
    "is_valid_bar",
    "validate_bar",
    "validate_bars",
    "bars_from_records",
    "coerce_timestamp",
    "NormalizationError",
    "CsvBarStore",
    "SeriesKey",
    "StorageError",
]
