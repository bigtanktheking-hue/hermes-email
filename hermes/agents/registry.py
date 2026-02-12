"""Agent registry — singleton that holds all agent instances."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hermes.agents.base import BaseAgent

log = logging.getLogger(__name__)


class AgentRegistry:
    """Central registry for all HERMES agents."""

    def __init__(self):
        self._agents: dict[str, BaseAgent] = {}

    def register(self, agent: BaseAgent):
        """Register an agent instance."""
        self._agents[agent.agent_id] = agent
        log.info("Registered agent: %s", agent.agent_id)

    def get(self, agent_id: str) -> BaseAgent | None:
        return self._agents.get(agent_id)

    def all(self) -> list[BaseAgent]:
        return list(self._agents.values())

    def ids(self) -> list[str]:
        return list(self._agents.keys())

    def enabled(self) -> list[BaseAgent]:
        return [a for a in self._agents.values() if a.agent_config.enabled]

    def get_status_all(self) -> list[dict]:
        return [a.get_status() for a in self._agents.values()]
