"""Briefing Agent — generates morning email briefing."""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from hermes.agents.base import AgentResult, BaseAgent

log = logging.getLogger(__name__)


class BriefingAgent(BaseAgent):
    agent_id = "briefing"
    display_name = "Briefing Agent"

    def execute(self) -> AgentResult:
        hours_back = self.agent_config.thresholds.get("hours_back", 12)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
        epoch = int(cutoff.timestamp())

        emails = self.gmail.get_messages(
            query=f"after:{epoch} in:inbox", max_results=100
        )
        if not emails:
            return AgentResult(
                success=True,
                data={"message": f"No emails in the last {hours_back} hours"},
                emails_processed=0,
                actions_taken=["checked_inbox"],
            )

        summary = self.ai.summarize_emails(emails)

        return AgentResult(
            success=True,
            data={"email_count": len(emails), **summary},
            emails_processed=len(emails),
            actions_taken=["generated_briefing"],
        )
