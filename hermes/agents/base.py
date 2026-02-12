"""Base agent abstractions — AgentConfig, AgentResult, BaseAgent ABC."""
from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class AgentConfig:
    """Versioned, self-modifiable agent configuration."""

    agent_id: str
    version: int = 1
    enabled: bool = True
    display_name: str = ""
    system_prompt: str = ""
    thresholds: dict = field(default_factory=dict)
    weights: dict = field(default_factory=dict)
    schedule: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> AgentConfig:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class AgentResult:
    """Result returned by every agent execution."""

    success: bool
    data: dict = field(default_factory=dict)
    emails_processed: int = 0
    actions_taken: list = field(default_factory=list)
    execution_time_ms: int = 0
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class BaseAgent(ABC):
    """Abstract base for all HERMES agents."""

    agent_id: str = ""
    display_name: str = ""

    def __init__(self, config, ai, gmail, agent_config: AgentConfig):
        self.config = config          # hermes.config.Config
        self.ai = ai                  # hermes.ai.AIClient
        self.gmail = gmail            # hermes.gmail.GmailClient
        self.agent_config = agent_config
        self._last_run: float | None = None
        self._last_result: AgentResult | None = None

    @abstractmethod
    def execute(self) -> AgentResult:
        """Run the agent's main task. Must be implemented by subclasses."""
        ...

    def run(self) -> AgentResult:
        """Execute with timing and error handling."""
        start = time.time()
        try:
            result = self.execute()
        except Exception as e:
            log.error("Agent %s failed: %s", self.agent_id, e, exc_info=True)
            result = AgentResult(
                success=False,
                error=str(e),
                execution_time_ms=int((time.time() - start) * 1000),
            )
        else:
            result.execution_time_ms = int((time.time() - start) * 1000)

        self._last_run = time.time()
        self._last_result = result
        return result

    def propose_config_change(self, result: AgentResult, feedback: list[dict] | None = None) -> dict | None:
        """Ask the LLM if any config should change based on result + feedback.

        Returns a dict with proposed changes, or None if no change needed.
        """
        if not feedback and result.success:
            return None

        context = {
            "agent_id": self.agent_id,
            "current_thresholds": self.agent_config.thresholds,
            "current_weights": self.agent_config.weights,
            "last_result": result.to_dict(),
            "recent_feedback": feedback or [],
        }

        try:
            proposal = self.ai.evaluate_config_change(
                agent_id=self.agent_id,
                current_config=self.agent_config.to_dict(),
                proposed_change=None,
                context=context,
            )
            if proposal and proposal.get("approve"):
                return proposal.get("modified_change")
        except Exception as e:
            log.warning("Config change proposal failed for %s: %s", self.agent_id, e)

        return None

    def load_config(self) -> AgentConfig:
        """Load config from JSON file."""
        config_dir = self.config.project_dir / "hermes" / "agents" / "configs"
        config_path = config_dir / f"{self.agent_id}.json"
        if config_path.exists():
            data = json.loads(config_path.read_text())
            self.agent_config = AgentConfig.from_dict(data)
        return self.agent_config

    def save_config(self, new_config: AgentConfig | None = None):
        """Save config atomically, auto-incrementing version."""
        cfg = new_config or self.agent_config
        cfg.version += 1
        config_dir = self.config.project_dir / "hermes" / "agents" / "configs"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / f"{cfg.agent_id}.json"
        tmp_path = config_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(cfg.to_dict(), indent=2))
        tmp_path.replace(config_path)
        self.agent_config = cfg

    def get_status(self) -> dict:
        """Return current agent status for API/UI."""
        return {
            "agent_id": self.agent_id,
            "display_name": self.display_name,
            "enabled": self.agent_config.enabled,
            "version": self.agent_config.version,
            "schedule": self.agent_config.schedule,
            "last_run": self._last_run,
            "last_success": self._last_result.success if self._last_result else None,
            "last_execution_ms": self._last_result.execution_time_ms if self._last_result else None,
        }
