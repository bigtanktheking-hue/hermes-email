"""Director meta-agent — reviews other agents, adjusts schedules."""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from hermes.agents.base import AgentResult, BaseAgent
from hermes.agents.guardrails import Guardrails

if TYPE_CHECKING:
    from hermes.agents.db import AgentDB
    from hermes.agents.registry import AgentRegistry

log = logging.getLogger(__name__)


class DirectorAgent(BaseAgent):
    agent_id = "director"
    display_name = "Director"

    def __init__(self, config, ai, gmail, agent_config, db: AgentDB, registry: AgentRegistry):
        super().__init__(config, ai, gmail, agent_config)
        self.db = db
        self.registry = registry

    def execute(self) -> AgentResult:
        """Review execution logs across all agents and propose adjustments."""
        all_agents = self.registry.all()
        agent_reports = []

        for agent in all_agents:
            if agent.agent_id == "director":
                continue
            executions = self.db.get_executions(agent.agent_id, limit=10)
            metrics = self.db.get_metrics(agent.agent_id, days=7)
            agent_reports.append({
                "agent_id": agent.agent_id,
                "enabled": agent.agent_config.enabled,
                "schedule": agent.agent_config.schedule,
                "recent_executions": len(executions),
                "recent_success_rate": (
                    sum(1 for e in executions if e.get("success"))
                    / max(len(executions), 1)
                ),
                "weekly_metrics": metrics,
            })

        if not agent_reports:
            return AgentResult(
                success=True,
                data={"message": "No agents to review"},
                actions_taken=["reviewed_department"],
            )

        # Ask LLM for schedule adjustment recommendations
        prompt = f"""You are the Director of the HERMES email agent department.
Review these agent performance reports and suggest schedule adjustments.

{json.dumps(agent_reports, indent=2, default=str)}

Respond with a JSON object:
{{"adjustments": [{{"agent_id": "...", "action": "reschedule|enable|disable", "new_schedule": {{...}}, "reason": "..."}}], "summary": "Brief overview of department health"}}

Only suggest changes if clearly beneficial. Respond ONLY with JSON."""

        try:
            text = self.ai._generate(prompt, system="You are the HERMES Director agent. Respond ONLY with valid JSON.")
            recommendations = self.ai._parse_json_response(text, {"adjustments": [], "summary": "No changes needed"})
        except Exception as e:
            log.warning("Director LLM call failed: %s", e)
            return AgentResult(
                success=False,
                error=str(e),
                actions_taken=["review_failed"],
            )

        adjustments = recommendations.get("adjustments", [])
        applied = []

        for adj in adjustments:
            aid = adj.get("agent_id", "")
            action = adj.get("action", "")

            if aid == "director":
                continue  # Cannot modify self

            agent = self.registry.get(aid)
            if not agent:
                continue

            if action == "reschedule" and adj.get("new_schedule"):
                new_sched = adj["new_schedule"]
                ok, reason = Guardrails.validate_config_change(aid, "schedule", None, new_sched)
                if ok:
                    old_version = agent.agent_config.version
                    agent.agent_config.schedule = new_sched
                    agent.save_config()
                    self.db.record_config_change(
                        agent_id=aid,
                        version_before=old_version,
                        version_after=agent.agent_config.version,
                        field_changed="schedule",
                        old_value=agent.agent_config.schedule,
                        new_value=new_sched,
                        reason=adj.get("reason", ""),
                        proposed_by="director",
                        approved=True,
                        reasoning=recommendations.get("summary", ""),
                    )
                    applied.append({"agent_id": aid, "action": "rescheduled"})
                else:
                    log.warning("Director schedule change rejected for %s: %s", aid, reason)

            elif action == "disable":
                agent.agent_config.enabled = False
                agent.save_config()
                applied.append({"agent_id": aid, "action": "disabled"})

            elif action == "enable":
                agent.agent_config.enabled = True
                agent.save_config()
                applied.append({"agent_id": aid, "action": "enabled"})

        return AgentResult(
            success=True,
            data={
                "summary": recommendations.get("summary", ""),
                "adjustments_proposed": len(adjustments),
                "adjustments_applied": len(applied),
                "applied": applied,
            },
            actions_taken=["reviewed_department", f"applied_{len(applied)}_changes"],
        )
