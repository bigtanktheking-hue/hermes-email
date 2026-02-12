"""Tests for hermes.api routes."""
import pytest


class TestHealthEndpoint:
    def test_health_returns_ok(self, app):
        with app.test_client() as c:
            resp = c.get("/api/health")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["status"] == "ok"
            assert data["service"] == "hermes"


class TestLoginFlow:
    def test_login_page_renders(self, app):
        with app.test_client() as c:
            resp = c.get("/login")
            assert resp.status_code == 200

    def test_login_wrong_password(self, app, monkeypatch):
        monkeypatch.setenv("HERMES_WEB_PASSWORD", "correct")
        with app.test_client() as c:
            resp = c.post("/login", data={"password": "wrong"})
            assert resp.status_code == 401

    def test_login_correct_password(self, app, monkeypatch):
        monkeypatch.setenv("HERMES_WEB_PASSWORD", "correct")
        with app.test_client() as c:
            resp = c.post("/login", data={"password": "correct"}, follow_redirects=False)
            assert resp.status_code == 302

    def test_logout_clears_session(self, client):
        resp = client.get("/logout", follow_redirects=False)
        assert resp.status_code == 302


class TestAuthRequired:
    def test_unauthenticated_redirect(self, app, monkeypatch):
        monkeypatch.setenv("HERMES_WEB_PASSWORD", "pw")
        with app.test_client() as c:
            resp = c.get("/")
            assert resp.status_code == 302
            assert "/login" in resp.headers.get("Location", "")

    def test_unauthenticated_api_returns_401(self, app, monkeypatch):
        monkeypatch.setenv("HERMES_WEB_PASSWORD", "pw")
        with app.test_client() as c:
            resp = c.get("/api/stats", headers={"X-Requested-With": "XMLHttpRequest"})
            assert resp.status_code == 401

    def test_api_key_auth(self, app, monkeypatch):
        monkeypatch.setenv("HERMES_WEB_PASSWORD", "pw")
        monkeypatch.setenv("HERMES_API_KEY", "test-key")
        with app.test_client() as c:
            resp = c.get("/api/health")
            assert resp.status_code == 200


class TestSecurityHeaders:
    def test_security_headers_present(self, client):
        resp = client.get("/api/health")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"
        assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        assert "Content-Security-Policy" in resp.headers


class TestCSRF:
    def test_post_without_csrf_rejected(self, app, monkeypatch):
        monkeypatch.setenv("HERMES_WEB_PASSWORD", "pw")
        with app.test_client() as c:
            with c.session_transaction() as sess:
                sess["authenticated"] = True
                sess["csrf_token"] = "valid-token"
            resp = c.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "hi"}]},
            )
            assert resp.status_code == 403

    def test_post_with_valid_csrf_accepted(self, app, monkeypatch):
        """CSRF should pass with valid token (may fail on downstream logic, but not 403)."""
        monkeypatch.setenv("HERMES_WEB_PASSWORD", "pw")
        with app.test_client() as c:
            with c.session_transaction() as sess:
                sess["authenticated"] = True
                sess["csrf_token"] = "valid-token"
            resp = c.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "hi"}]},
                headers={"X-CSRF-Token": "valid-token"},
            )
            # Should not be 403 (CSRF passed); may be 500 due to no AI backend
            assert resp.status_code != 403


class TestErrorHandlers:
    def test_404_returns_json(self, client):
        resp = client.get("/api/nonexistent")
        assert resp.status_code == 404
        data = resp.get_json()
        assert data["error"] == "Not found"
