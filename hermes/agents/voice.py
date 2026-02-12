"""Voice Agent — event-driven chat agent for voice interactions."""
from __future__ import annotations

import logging

from hermes.agents.base import AgentResult, BaseAgent

log = logging.getLogger(__name__)


class VoiceAgent(BaseAgent):
    agent_id = "voice"
    display_name = "Voice Agent"

    def execute(self) -> AgentResult:
        """Voice agent is event-driven — execute is a no-op for scheduled runs."""
        return AgentResult(
            success=True,
            data={"message": "Voice agent is event-driven, no scheduled action"},
            emails_processed=0,
            actions_taken=["noop"],
        )

    def handle_message(self, messages: list[dict]) -> str:
        """Process a voice chat message and return the response text."""
        resp = self.ai.chat(messages, voice_mode=True)
        if resp.text:
            return resp.text
        return "I didn't catch that."
