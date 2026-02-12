"""Triage Agent — scans unread emails and classifies by priority."""
from __future__ import annotations

import json
import logging

from hermes.agents.base import AgentResult, BaseAgent

log = logging.getLogger(__name__)


class TriageAgent(BaseAgent):
    agent_id = "triage"
    display_name = "Triage Agent"

    def execute(self) -> AgentResult:
        max_emails = self.agent_config.thresholds.get("max_emails", 50)
        emails = self.gmail.get_messages(
            query="is:unread in:inbox", max_results=max_emails
        )
        if not emails:
            return AgentResult(
                success=True,
                data={"message": "No unread emails"},
                emails_processed=0,
                actions_taken=["checked_inbox"],
            )

        classifications = self.ai.classify_priority(emails)
        email_map = {e["id"]: e for e in emails}
        for c in classifications:
            e = email_map.get(c.get("id"), {})
            c["from"] = e.get("from", "")
            c["subject"] = e.get("subject", "")

        high = [c for c in classifications if c.get("priority") == "high"]
        medium = [c for c in classifications if c.get("priority") == "medium"]
        low = [c for c in classifications if c.get("priority") == "low"]

        return AgentResult(
            success=True,
            data={
                "total": len(emails),
                "high": len(high),
                "medium": len(medium),
                "low": len(low),
                "high_items": high[:10],
            },
            emails_processed=len(emails),
            actions_taken=["classified_priority"],
        )
