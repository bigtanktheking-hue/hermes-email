"""Cleanup Agent — archives/deletes newsletters and promotions."""
from __future__ import annotations

import logging

from hermes.agents.base import AgentResult, BaseAgent

log = logging.getLogger(__name__)


class CleanupAgent(BaseAgent):
    agent_id = "cleanup"
    display_name = "Cleanup Agent"

    def execute(self) -> AgentResult:
        auto_archive = self.agent_config.thresholds.get("auto_archive", True)
        auto_delete = self.agent_config.thresholds.get("auto_delete", False)
        max_emails = self.agent_config.thresholds.get("max_emails", 50)

        emails = self.gmail.get_messages(
            query="in:inbox category:promotions OR category:updates",
            max_results=max_emails,
        )
        if not emails:
            return AgentResult(
                success=True,
                data={"message": "No newsletters or promotions to clean up"},
                emails_processed=0,
                actions_taken=["checked_promotions"],
            )

        classifications = self.ai.classify_junk(emails)
        valid_ids = {e["id"] for e in emails}
        classifications = [c for c in classifications if c.get("id") in valid_ids]

        to_archive = [c for c in classifications if c.get("action") == "archive"]
        to_delete = [c for c in classifications if c.get("action") == "delete"]

        actions = ["classified_junk"]

        if auto_archive and to_archive:
            self.gmail.archive_messages([c["id"] for c in to_archive])
            actions.append(f"archived_{len(to_archive)}")

        if auto_delete and to_delete:
            self.gmail.trash_messages([c["id"] for c in to_delete])
            actions.append(f"deleted_{len(to_delete)}")

        return AgentResult(
            success=True,
            data={
                "scanned": len(emails),
                "archived": len(to_archive) if auto_archive else 0,
                "deleted": len(to_delete) if auto_delete else 0,
                "would_archive": len(to_archive),
                "would_delete": len(to_delete),
            },
            emails_processed=len(emails),
            actions_taken=actions,
        )
