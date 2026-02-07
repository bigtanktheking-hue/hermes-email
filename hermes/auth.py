"""Web authentication helpers."""
from __future__ import annotations

import os
from functools import wraps

from flask import redirect, request, session, url_for


def check_password(password: str) -> bool:
    """Validate password against HERMES_WEB_PASSWORD env var."""
    expected = os.environ.get("HERMES_WEB_PASSWORD", "")
    if not expected:
        return True  # No password set = local dev mode
    return password == expected


def require_auth(f):
    """Accept session cookie OR X-API-Key header."""
    @wraps(f)
    def decorated(*args, **kwargs):
        # No web password set = local dev, skip browser auth
        if not os.environ.get("HERMES_WEB_PASSWORD"):
            return f(*args, **kwargs)
        # Session auth (web)
        if session.get("authenticated"):
            return f(*args, **kwargs)
        # API key auth (n8n / programmatic)
        expected_key = os.environ.get("HERMES_API_KEY", "")
        if expected_key and request.headers.get("X-API-Key") == expected_key:
            return f(*args, **kwargs)
        # AJAX / API requests get 401
        if request.is_json or request.headers.get("X-Requested-With"):
            from flask import jsonify
            return jsonify({"error": "unauthorized"}), 401
        return redirect(url_for("login"))
    return decorated
