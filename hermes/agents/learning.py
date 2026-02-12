"""Learning Manager — feedback ingestion, evolution proposals, audit trail."""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from hermes.agents.guardrails import Guardrails

if TYPE_CHECKING:
    from hermes.agents.db import AgentDB
    from hermes.agents.registry import AgentRegistry
    from hermes.ai import AIClient

log = logging.getLogger(__name__)

EVOLUTION_MIN_FEEDBACK = 5


class LearningManager:
    """Ingests feedback, proposes agent evolution, and tracks audit history."""

    def __init__(self, db: AgentDB, registry: AgentRegistry, ai: AIClient):
        self.db = db
        self.registry = registry
        self.ai = ai

    def record_feedback(
        self,
        agent_id: str,
        execution_id: int | None,
        feedback_type: str,
        data: dict | None = None,
    ):
        """Store user feedback for an agent execution."""
        self.db.record_feedback(agent_id, execution_id, feedback_type, data)
        log.info("Feedback recorded: %s %s (exec=%s)", agent_id, feedback_type, execution_id)

    def record_execution(self, agent_id: str, result: dict, config_version: int = 1) -> int:
        """Log every agent run and update daily metrics."""
        exec_id = self.db.record_execution(agent_id, result, config_version)
        self.db.update_daily_metrics(agent_id, result)
        return exec_id

    def propose_evolution(self, agent_id: str) -> dict | None:
        """After enough feedback, aggregate patterns and propose config changes via LLM.

        Returns proposed change dict or None.
        """
        feedback = self.db.get_unprocessed_feedback(agent_id)
        if len(feedback) < EVOLUTION_MIN_FEEDBACK:
            return None

        agent = self.registry.get(agent_id)
        if not agent:
            return None

        # Build context for LLM
        recent_executions = self.db.get_executions(agent_id, limit=10)
        metrics = self.db.get_metrics(agent_id, days=7)

        positive = sum(1 for f in feedback if f["feedback_type"] == "thumbs_up")
        negative = sum(1 for f in feedback if f["feedback_type"] == "thumbs_down")

        context = {
            "agent_id": agent_id,
            "current_config": agent.agent_config.to_dict(),
            "feedback_summary": {
                "total": len(feedback),
                "positive": positive,
                "negative": negative,
            },
            "recent_performance": {
                "executions": len(recent_executions),
                "success_rate": (
                    sum(1 for e in recent_executions if e.get("success"))
                    / max(len(recent_executions), 1)
                ),
            },
            "weekly_metrics": metrics,
        }

        try:
            proposal = self.ai.evaluate_config_change(
                agent_id=agent_id,
                current_config=agent.agent_config.to_dict(),
                proposed_change=None,
                context=context,
            )
        except Exception as e:
            log.warning("Evolution proposal failed for %s: %s", agent_id, e)
            return None

        # Mark feedback as processed
        self.db.mark_feedback_processed([f["id"] for f in feedback])

        if not proposal or not proposal.get("approve"):
            return None

        change = proposal.get("modified_change", {})
        if not change:
            return None

        # Validate through guardrails
        for field, new_val in change.items():
            ok, reason = Guardrails.validate_config_change(
                agent_id, field, None, new_val
            )
            if not ok:
                log.warning("Evolution rejected by guardrails for %s.%s: %s", agent_id, field, reason)
                return None

        return change

    def apply_evolution(self, agent_id: str, change: dict, reason: str = "learning_manager"):
        """Apply a validated config change to an agent."""
        agent = self.registry.get(agent_id)
        if not agent:
            return

        old_version = agent.agent_config.version
        cfg = agent.agent_config

        for field, value in change.items():
            if field == "thresholds" and isinstance(value, dict):
                cfg.thresholds.update(value)
            elif field == "weights" and isinstance(value, dict):
                cfg.weights.update(value)
            elif field == "system_prompt":
                cfg.system_prompt = value
            elif field == "schedule" and isinstance(value, dict):
                cfg.schedule = value

        agent.save_config(cfg)

        # Audit trail
        self.db.record_config_change(
            agent_id=agent_id,
            version_before=old_version,
            version_after=cfg.version,
            field_changed=",".join(change.keys()),
            old_value="(see previous version)",
            new_value=change,
            reason=reason,
            proposed_by="learning_manager",
            approved=True,
            reasoning=f"Automatic evolution after {EVOLUTION_MIN_FEEDBACK}+ feedback points",
        )

    def get_evolution_history(self, agent_id: str) -> list[dict]:
        """Return versioned change timeline for an agent."""
        return self.db.get_audit_log(agent_id)

    def get_audit_log(self) -> list[dict]:
        """Full change audit trail across all agents."""
        return self.db.get_audit_log()
