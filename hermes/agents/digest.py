"""Digest Agent — generates weekly email digest with stats."""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

from hermes.agents.base import AgentResult, BaseAgent

log = logging.getLogger(__name__)


class DigestAgent(BaseAgent):
    agent_id = "digest"
    display_name = "Digest Agent"

    def execute(self) -> AgentResult:
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        epoch = int(week_ago.timestamp())

        received = self.gmail.get_messages(
            query=f"after:{epoch} in:inbox", max_results=200, with_body=False
        )
        sent = self.gmail.get_messages(
            query=f"after:{epoch} in:sent", max_results=200, with_body=False
        )
        unread = self.gmail.get_unread_count()

        day_counter: Counter = Counter()
        sender_counter: Counter = Counter()

        for msg in received:
            date = self._safe_parse_date(msg.get("date", ""))
            if date:
                day_counter[date.strftime("%A")] += 1
            sender = msg.get("from", "")
            if "<" in sender:
                sender = sender.split("<")[0].strip().strip('"')
            sender_counter[sender] += 1

        busiest = day_counter.most_common(1)[0][0] if day_counter else "N/A"
        top = [s for s, _ in sender_counter.most_common(5)]

        stats_data = {
            "received": len(received),
            "sent": len(sent),
            "busiest_day": busiest,
            "top_senders": top,
            "unread": unread,
        }

        narrative = self.ai.generate_digest_narrative(stats_data)

        return AgentResult(
            success=True,
            data={**stats_data, "narrative": narrative},
            emails_processed=len(received) + len(sent),
            actions_taken=["generated_digest"],
        )

    @staticmethod
    def _safe_parse_date(date_str: str):
        if not date_str:
            return None
        try:
            return parsedate_to_datetime(date_str)
        except (ValueError, TypeError):
            return None
