"""Shared test fixtures for HERMES."""
import os
import pytest


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Ensure tests don't accidentally use production env vars."""
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("FLASK_ENV", raising=False)
    monkeypatch.delenv("HERMES_WEB_PASSWORD", raising=False)
    monkeypatch.delenv("HERMES_API_KEY", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)


@pytest.fixture
def config(tmp_path, monkeypatch):
    """Create a test Config pointing at a temp directory."""
    from hermes.config import Config
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("FLASK_ENV", raising=False)
    return Config(project_dir=tmp_path)


@pytest.fixture
def app(monkeypatch):
    """Create a test Flask app."""
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("FLASK_ENV", raising=False)
    from hermes.api import app as flask_app
    flask_app.config["TESTING"] = True
    flask_app.config["SECRET_KEY"] = "test-secret"
    return flask_app


@pytest.fixture
def client(app):
    """Create a test client with authenticated session."""
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["authenticated"] = True
            sess["csrf_token"] = "test-csrf-token"
        yield c
