"""Configuration via dataclass + .env loading."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _project_dir() -> Path:
    """Return the project root (directory containing this package)."""
    return Path(__file__).resolve().parent.parent


@dataclass
class Config:
    project_dir: Path = field(default_factory=_project_dir)
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "mistral"
    ai_backend: str = "ollama"  # "ollama" or "groq"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    groq_url: str = "https://api.groq.com/openai/v1"
    gmail_credentials_file: str = "credentials.json"
    gmail_token_file: str = "token.json"
    gmail_scopes: list[str] = field(
        default_factory=lambda: ["https://mail.google.com/"]
    )
    vip_data_file: str = "hermes_data.json"
    vip_domains_file: str = "vip_domains.json"
    vip_refresh_days: int = 7
    vip_top_n: int = 20
    vip_min_score: float = 10.0
    max_messages_cap: int = 200
    body_preview_chars: int = 500
    batch_fetch_size: int = 50
    inbox_zero_batch: int = 10
    repl_history_limit: int = 40
    web_password: str = ""
    secret_key: str = ""

    def __post_init__(self):
        self._load_env()
        if not self.anthropic_api_key:
            self.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if os.environ.get("OLLAMA_URL"):
            self.ollama_url = os.environ["OLLAMA_URL"]
        if os.environ.get("OLLAMA_MODEL"):
            self.ollama_model = os.environ["OLLAMA_MODEL"]
        # Groq / AI backend
        if os.environ.get("AI_BACKEND"):
            self.ai_backend = os.environ["AI_BACKEND"]
        if os.environ.get("GROQ_API_KEY"):
            self.groq_api_key = os.environ["GROQ_API_KEY"]
        if os.environ.get("GROQ_MODEL"):
            self.groq_model = os.environ["GROQ_MODEL"]
        # Web auth
        if os.environ.get("HERMES_WEB_PASSWORD"):
            self.web_password = os.environ["HERMES_WEB_PASSWORD"]
        if os.environ.get("SECRET_KEY"):
            self.secret_key = os.environ["SECRET_KEY"]
        elif not self.secret_key:
            self.secret_key = self.web_password or "hermes-dev-key"
        # Gmail credentials from env vars (for cloud deploy)
        self._write_credentials_from_env()

    def _load_env(self):
        """Load .env file from project directory."""
        env_path = self.project_dir / ".env"
        if not env_path.exists():
            return
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("\"'")
                os.environ.setdefault(key, value)

    def _write_credentials_from_env(self):
        """Write Gmail credentials from env vars to temp files (for cloud)."""
        import tempfile
        creds_json = os.environ.get("GMAIL_CREDENTIALS_JSON", "")
        token_json = os.environ.get("GMAIL_TOKEN_JSON", "")
        if creds_json and not (self.project_dir / self.gmail_credentials_file).exists():
            tmp = Path(tempfile.gettempdir()) / "hermes_credentials.json"
            tmp.write_text(creds_json)
            self.gmail_credentials_file = str(tmp)
        if token_json and not (self.project_dir / self.gmail_token_file).exists():
            tmp = Path(tempfile.gettempdir()) / "hermes_token.json"
            tmp.write_text(token_json)
            self.gmail_token_file = str(tmp)

    @property
    def credentials_path(self) -> Path:
        p = Path(self.gmail_credentials_file)
        return p if p.is_absolute() else self.project_dir / p

    @property
    def token_path(self) -> Path:
        p = Path(self.gmail_token_file)
        return p if p.is_absolute() else self.project_dir / p

    @property
    def vip_data_path(self) -> Path:
        return self.project_dir / self.vip_data_file

    @property
    def vip_domains_path(self) -> Path:
        return self.project_dir / self.vip_domains_file


def load_config() -> Config:
    """Create and return the global config."""
    return Config()
