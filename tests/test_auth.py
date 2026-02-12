"""Tests for hermes.auth module."""
import time
import pytest

from hermes.auth import (
    check_password,
    _check_api_key,
    _is_rate_limited,
    _record_failed_attempt,
    _failed_attempts,
    _clean_stale_entries,
)


class TestCheckPassword:
    def test_no_password_set_dev_mode_allows(self, monkeypatch):
        monkeypatch.delenv("HERMES_WEB_PASSWORD", raising=False)
        monkeypatch.delenv("RENDER", raising=False)
        monkeypatch.delenv("FLASK_ENV", raising=False)
        assert check_password("anything") is True

    def test_no_password_set_production_denies(self, monkeypatch):
        monkeypatch.delenv("HERMES_WEB_PASSWORD", raising=False)
        monkeypatch.setenv("RENDER", "true")
        assert check_password("anything") is False

    def test_correct_password(self, monkeypatch):
        monkeypatch.setenv("HERMES_WEB_PASSWORD", "secret123")
        assert check_password("secret123") is True

    def test_wrong_password(self, monkeypatch):
        monkeypatch.setenv("HERMES_WEB_PASSWORD", "secret123")
        assert check_password("wrongpass") is False

    def test_empty_password_rejected(self, monkeypatch):
        monkeypatch.setenv("HERMES_WEB_PASSWORD", "secret123")
        assert check_password("") is False


class TestCheckApiKey:
    def test_valid_api_key(self, monkeypatch):
        monkeypatch.setenv("HERMES_API_KEY", "my-api-key")
        assert _check_api_key("my-api-key") is True

    def test_invalid_api_key(self, monkeypatch):
        monkeypatch.setenv("HERMES_API_KEY", "my-api-key")
        assert _check_api_key("wrong-key") is False

    def test_no_api_key_configured(self, monkeypatch):
        monkeypatch.delenv("HERMES_API_KEY", raising=False)
        assert _check_api_key("any-key") is False

    def test_empty_key_rejected(self, monkeypatch):
        monkeypatch.setenv("HERMES_API_KEY", "my-api-key")
        assert _check_api_key("") is False


class TestRateLimiting:
    def setup_method(self):
        _failed_attempts.clear()

    def test_not_rate_limited_initially(self):
        assert _is_rate_limited("192.168.1.1") is False

    def test_rate_limited_after_max_attempts(self):
        ip = "192.168.1.1"
        for _ in range(5):
            _record_failed_attempt(ip)
        assert _is_rate_limited(ip) is True

    def test_below_limit_not_blocked(self):
        ip = "192.168.1.1"
        for _ in range(4):
            _record_failed_attempt(ip)
        assert _is_rate_limited(ip) is False

    def test_different_ips_independent(self):
        for _ in range(5):
            _record_failed_attempt("10.0.0.1")
        assert _is_rate_limited("10.0.0.1") is True
        assert _is_rate_limited("10.0.0.2") is False

    def test_stale_entries_cleaned(self, monkeypatch):
        ip = "192.168.1.1"
        # Add old timestamps (beyond the 15-minute window)
        _failed_attempts[ip] = [time.time() - 1000]
        _clean_stale_entries()
        assert ip not in _failed_attempts
