"""Web authentication helpers."""
from __future__ import annotations

import hmac
import os
import time
from functools import wraps

from flask import redirect, request, session, url_for

from hermes.config import _is_production

# ── Rate limiter for failed login attempts ────────────────────
# Structure: {ip: [(timestamp, ...), ...]}
_failed_attempts: dict[str, list[float]] = {}
_RATE_LIMIT_WINDOW = 15 * 60  # 15 minutes
_RATE_LIMIT_MAX = 5  # max failures before blocking


def _clean_stale_entries():
    """Remove entries older than the rate limit window."""
    cutoff = time.time() - _RATE_LIMIT_WINDOW
    stale_ips = []
    for ip, timestamps in _failed_attempts.items():
        _failed_attempts[ip] = [t for t in timestamps if t > cutoff]
        if not _failed_attempts[ip]:
            stale_ips.append(ip)
    for ip in stale_ips:
        del _failed_attempts[ip]


def _is_rate_limited(ip: str) -> bool:
    """Check if an IP is rate-limited due to too many failed attempts."""
    _clean_stale_entries()
    attempts = _failed_attempts.get(ip, [])
    return len(attempts) >= _RATE_LIMIT_MAX


def _record_failed_attempt(ip: str):
    """Record a failed login attempt for an IP."""
    if ip not in _failed_attempts:
        _failed_attempts[ip] = []
    _failed_attempts[ip].append(time.time())


def check_password(password: str) -> bool:
    """Validate password against HERMES_WEB_PASSWORD env var."""
    expected = os.environ.get("HERMES_WEB_PASSWORD", "")
    if not expected:
        # No password set: allow in dev, deny in production
        if _is_production():
            return False
        return True
    # Use timing-safe comparison
    return hmac.compare_digest(password, expected)


def _check_api_key(provided_key: str) -> bool:
    """Validate API key using timing-safe comparison."""
    expected_key = os.environ.get("HERMES_API_KEY", "")
    if not expected_key:
        return False
    return hmac.compare_digest(provided_key, expected_key)


def require_auth(f):
    """Accept session cookie OR X-API-Key header."""
    @wraps(f)
    def decorated(*args, **kwargs):
        # No web password set = local dev, skip browser auth (not in production)
        if not os.environ.get("HERMES_WEB_PASSWORD"):
            if not _is_production():
                return f(*args, **kwargs)
        # Session auth (web)
        if session.get("authenticated"):
            return f(*args, **kwargs)
        # API key auth (n8n / programmatic)
        provided_key = request.headers.get("X-API-Key", "")
        if provided_key and _check_api_key(provided_key):
            return f(*args, **kwargs)
        # AJAX / API requests get 401
        if request.is_json or request.headers.get("X-Requested-With"):
            from flask import jsonify
            return jsonify({"error": "unauthorized"}), 401
        return redirect(url_for("login"))
    return decorated
