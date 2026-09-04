"""Tests for the Alpaca architectural stub.

These lock in the *contract* of the placeholder: it is discoverable, it fails
loudly instead of silently returning nothing, it never carries credentials in
code, and it points at Alpaca's paper environment.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from src.data.provider import MarketDataProvider, ProviderConfigurationError
from src.data.providers.alpaca import (
    ALPACA_KEY_ENV,
    ALPACA_SECRET_ENV,
    AlpacaProvider,
    credentials_present,
)
from tests.conftest import UTC

START = datetime(2024, 1, 1, tzinfo=UTC)
END = datetime(2024, 1, 31, tzinfo=UTC)


def test_it_implements_the_provider_interface():
    provider = AlpacaProvider()
    assert isinstance(provider, MarketDataProvider)
    assert provider.name == "alpaca"


def test_requesting_bars_fails_loudly_rather_than_returning_nothing():
    with pytest.raises(NotImplementedError, match="architectural stub"):
        AlpacaProvider().get_bars("AAPL", START, END, "1d")


def test_it_targets_the_paper_endpoint_only():
    assert "paper-api.alpaca.markets" in AlpacaProvider.base_url
    assert "paper" in AlpacaProvider.base_url


def test_credentials_are_read_from_the_environment_not_from_code(monkeypatch):
    monkeypatch.delenv(ALPACA_KEY_ENV, raising=False)
    monkeypatch.delenv(ALPACA_SECRET_ENV, raising=False)
    assert credentials_present() is False

    monkeypatch.setenv(ALPACA_KEY_ENV, "placeholder-key")
    monkeypatch.setenv(ALPACA_SECRET_ENV, "placeholder-secret")
    assert credentials_present() is True


def test_configuration_check_reports_missing_credentials_without_revealing_them(monkeypatch):
    monkeypatch.setenv(ALPACA_KEY_ENV, "super-secret-value")
    monkeypatch.delenv(ALPACA_SECRET_ENV, raising=False)
    with pytest.raises(ProviderConfigurationError) as excinfo:
        AlpacaProvider().check_configuration()
    message = str(excinfo.value)
    assert ALPACA_SECRET_ENV in message
    assert "super-secret-value" not in message
