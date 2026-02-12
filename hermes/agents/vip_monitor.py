"""VIP Monitor Agent — checks for unread emails from VIP contacts/domains."""
from __future__ import annotations

import logging

from hermes.agents.base import AgentResult, BaseAgent
from hermes.vip import get_vip_domain_emails, get_vip_emails, load_vip_domains, load_vips

log = logging.getLogger(__name__)


class VIPMonitorAgent(BaseAgent):
    agent_id = "vip_monitor"
    display_name = "VIP Monitor"

    def execute(self) -> AgentResult:
        vips = load_vips(self.config)
        vip_domains = load_vip_domains(self.config)

        query_parts = []
        for addr in get_vip_emails(vips):
            query_parts.append(f"from:{addr}")
        for domain in get_vip_domain_emails(vip_domains):
            query_parts.append(f"from:@{domain}")

        if not query_parts:
            return AgentResult(
                success=True,
                data={"message": "No VIP contacts configured"},
                emails_processed=0,
                actions_taken=["checked_vip_config"],
            )

        query = f"is:unread in:inbox ({' OR '.join(query_parts)})"
        emails = self.gmail.get_messages(query=query, max_results=50)

        alert_on_count = self.agent_config.thresholds.get("alert_on_count", 1)
        items = [
            {"from": e.get("from", ""), "subject": e.get("subject", ""), "id": e["id"]}
            for e in emails
        ]

        return AgentResult(
            success=True,
            data={
                "count": len(emails),
                "emails": items[:20],
                "alert": len(emails) >= alert_on_count,
            },
            emails_processed=len(emails),
            actions_taken=["scanned_vip_emails"],
        )
