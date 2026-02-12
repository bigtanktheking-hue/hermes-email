"""Inbox Zero Agent — processes inbox emails in batches."""
from __future__ import annotations

import logging

from hermes.agents.base import AgentResult, BaseAgent

log = logging.getLogger(__name__)


class InboxZeroAgent(BaseAgent):
    agent_id = "inbox_zero"
    display_name = "Inbox Zero Agent"

    def execute(self) -> AgentResult:
        batch_size = self.agent_config.thresholds.get("batch_size", 10)

        emails = self.gmail.get_messages(
            query="is:unread in:inbox", max_results=batch_size
        )
        if not emails:
            return AgentResult(
                success=True,
                data={"message": "Inbox zero achieved!", "inbox_zero": True},
                emails_processed=0,
                actions_taken=["checked_inbox"],
            )

        classifications = self.ai.classify_inbox(emails)
        valid_ids = {e["id"] for e in emails}
        classifications = [c for c in classifications if c.get("id") in valid_ids]

        read_archive = [c for c in classifications if c.get("action") == "read_archive"]
        junk = [c for c in classifications if c.get("action") == "junk"]
        action_needed = [c for c in classifications if c.get("action") == "action_needed"]

        actions = ["classified_inbox"]

        if read_archive:
            ids = [c["id"] for c in read_archive]
            self.gmail.archive_messages(ids)
            self.gmail.mark_read(ids)
            actions.append(f"archived_{len(read_archive)}")

        if junk:
            self.gmail.trash_messages([c["id"] for c in junk])
            actions.append(f"trashed_{len(junk)}")

        remaining = self.gmail.get_unread_count()

        return AgentResult(
            success=True,
            data={
                "processed": len(emails),
                "archived": len(read_archive),
                "trashed": len(junk),
                "kept": len(action_needed),
                "remaining": remaining,
                "inbox_zero": remaining == 0,
            },
            emails_processed=len(emails),
            actions_taken=actions,
        )
