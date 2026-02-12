"""Agent Scheduler — APScheduler orchestrator running inside Flask."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hermes.agents.db import AgentDB
    from hermes.agents.learning import LearningManager
    from hermes.agents.registry import AgentRegistry

log = logging.getLogger(__name__)

DIRECTOR_RUN_EVERY_N = 10  # Director runs after every N agent executions


class AgentScheduler:
    """Orchestrator that manages scheduled agent execution via APScheduler."""

    def __init__(self, registry: AgentRegistry, db: AgentDB, learning: LearningManager):
        self.registry = registry
        self.db = db
        self.learning = learning
        self._scheduler = None
        self._running = False
        self._execution_count = 0

    def start(self):
        """Start the APScheduler BackgroundScheduler."""
        if self._running:
            return

        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.interval import IntervalTrigger
            from apscheduler.triggers.cron import CronTrigger
        except ImportError:
            log.warning("APScheduler not installed — agents will only run manually")
            return

        self._scheduler = BackgroundScheduler(daemon=True)

        for agent in self.registry.enabled():
            self._add_job(agent)

        self._scheduler.start()
        self._running = True
        log.info("Agent scheduler started with %d agents", len(self.registry.enabled()))

    def stop(self):
        """Shut down the scheduler."""
        if self._scheduler and self._running:
            self._scheduler.shutdown(wait=False)
            self._running = False
            log.info("Agent scheduler stopped")

    def _add_job(self, agent):
        """Create an APScheduler job from agent config."""
        from apscheduler.triggers.interval import IntervalTrigger
        from apscheduler.triggers.cron import CronTrigger

        schedule = agent.agent_config.schedule
        stype = schedule.get("type", "manual")

        if stype == "interval":
            trigger = IntervalTrigger(minutes=schedule.get("minutes", 30))
        elif stype == "cron":
            trigger = CronTrigger(
                hour=schedule.get("hour", "*"),
                minute=schedule.get("minute", 0),
                day_of_week=schedule.get("day_of_week", "*"),
            )
        elif stype in ("manual", "event"):
            return  # Don't schedule — only triggered manually
        else:
            log.warning("Unknown schedule type for %s: %s", agent.agent_id, stype)
            return

        self._scheduler.add_job(
            self._run_agent,
            trigger=trigger,
            args=[agent.agent_id],
            id=f"agent_{agent.agent_id}",
            replace_existing=True,
            misfire_grace_time=120,
        )
        log.info("Scheduled %s: %s", agent.agent_id, schedule)

    def _run_agent(self, agent_id: str) -> dict | None:
        """Execute an agent, log result, trigger learning loop."""
        agent = self.registry.get(agent_id)
        if not agent or not agent.agent_config.enabled:
            return None

        log.info("Running agent: %s", agent_id)
        result = agent.run()
        result_dict = result.to_dict()

        # Log execution
        exec_id = self.learning.record_execution(
            agent_id, result_dict, agent.agent_config.version
        )

        # Check for evolution opportunity
        self._execution_count += 1
        evolution = self.learning.propose_evolution(agent_id)
        if evolution:
            self.learning.apply_evolution(agent_id, evolution)
            log.info("Applied evolution to %s: %s", agent_id, list(evolution.keys()))

        # Director review after every N executions
        if self._execution_count % DIRECTOR_RUN_EVERY_N == 0:
            director = self.registry.get("director")
            if director and director.agent_config.enabled:
                log.info("Running Director review (after %d executions)", self._execution_count)
                director.run()

        return result_dict

    def trigger_agent(self, agent_id: str) -> dict | None:
        """Manual agent execution from API/CLI."""
        return self._run_agent(agent_id)

    def reschedule_agent(self, agent_id: str, new_schedule: dict):
        """Update an agent's schedule (called by Director or API)."""
        agent = self.registry.get(agent_id)
        if not agent:
            return

        agent.agent_config.schedule = new_schedule
        agent.save_config()

        if self._scheduler and self._running:
            job_id = f"agent_{agent_id}"
            existing = self._scheduler.get_job(job_id)
            if existing:
                self._scheduler.remove_job(job_id)
            if agent.agent_config.enabled:
                self._add_job(agent)

    def get_status(self) -> dict:
        """Return scheduler status for API."""
        jobs = []
        if self._scheduler:
            for job in self._scheduler.get_jobs():
                jobs.append({
                    "id": job.id,
                    "next_run": str(job.next_run_time) if job.next_run_time else None,
                })

        return {
            "running": self._running,
            "total_executions": self._execution_count,
            "scheduled_jobs": jobs,
            "agents_enabled": len(self.registry.enabled()),
            "agents_total": len(self.registry.all()),
        }

    @property
    def running(self) -> bool:
        return self._running
