"""Safety guardrails — hard-coded bounds that agents cannot weaken."""
from __future__ import annotations

import re
import logging

log = logging.getLogger(__name__)

# ── Hard-coded bounds (immutable by design) ──────────────────

THRESHOLD_BOUNDS = {
    "max_emails_per_scan": (5, 200),
    "max_emails": (5, 200),
    "batch_size": (1, 50),
    "hours_back": (1, 168),
    "confidence": (0.5, 1.0),
    "alert_on_count": (1, 100),
}

SCHEDULE_MIN_INTERVAL_MINUTES = 5

PROMPT_MAX_LENGTH = 5000

# Patterns that should never appear in agent prompts
_INJECTION_PATTERNS = [
    r"(?i)ignore\s+(all\s+)?(previous|above|prior)\s+(instructions?|prompts?|rules?)",
    r"(?i)disregard\s+(all\s+)?(previous|above|prior)\s+(instructions?|prompts?|rules?)",
    r"(?i)forget\s+(all\s+)?(previous|above|prior)",
    r"(?i)new\s+system\s+prompt",
    r"(?i)you\s+are\s+now\s+(?!hermes)",
    r"(?i)override\s+(safety|security|guardrail)",
]

# Director config is immutable to self-modification
IMMUTABLE_AGENTS = {"director"}


class Guardrails:
    """Validates proposed config changes against hard-coded safety bounds."""

    @staticmethod
    def validate_config_change(agent_id: str, field: str, old_value, new_value) -> tuple[bool, str]:
        """Check if a proposed config change is within bounds.

        Returns (approved, reason).
        """
        # Director cannot modify itself
        if agent_id in IMMUTABLE_AGENTS:
            return False, f"Agent '{agent_id}' config is immutable to self-modification"

        # Threshold bounds
        if field in THRESHOLD_BOUNDS:
            lo, hi = THRESHOLD_BOUNDS[field]
            if isinstance(new_value, (int, float)):
                if new_value < lo or new_value > hi:
                    return False, f"{field} must be between {lo} and {hi}, got {new_value}"

        # System prompt validation
        if field == "system_prompt":
            if not isinstance(new_value, str):
                return False, "system_prompt must be a string"
            if len(new_value) > PROMPT_MAX_LENGTH:
                return False, f"system_prompt exceeds {PROMPT_MAX_LENGTH} chars"
            for pattern in _INJECTION_PATTERNS:
                if re.search(pattern, new_value):
                    return False, f"system_prompt contains forbidden pattern"

        # Schedule bounds
        if field == "schedule":
            if isinstance(new_value, dict):
                ok, reason = Guardrails._validate_schedule(new_value)
                if not ok:
                    return False, reason

        return True, "ok"

    @staticmethod
    def _validate_schedule(schedule: dict) -> tuple[bool, str]:
        """Validate schedule constraints."""
        stype = schedule.get("type", "")

        if stype == "interval":
            minutes = schedule.get("minutes", 0)
            if minutes < SCHEDULE_MIN_INTERVAL_MINUTES:
                return False, f"Interval must be >= {SCHEDULE_MIN_INTERVAL_MINUTES} minutes"

        elif stype == "cron":
            # Basic sanity — ensure required fields present
            pass

        elif stype == "manual":
            pass  # Always OK

        elif stype == "event":
            pass  # Always OK

        else:
            return False, f"Unknown schedule type: {stype}"

        return True, "ok"

    @staticmethod
    def validate_full_config(agent_id: str, config: dict) -> tuple[bool, list[str]]:
        """Validate an entire config dict. Returns (ok, list_of_errors)."""
        errors = []

        # Check thresholds
        for key, value in config.get("thresholds", {}).items():
            ok, reason = Guardrails.validate_config_change(agent_id, key, None, value)
            if not ok:
                errors.append(reason)

        # Check prompt
        prompt = config.get("system_prompt", "")
        if prompt:
            ok, reason = Guardrails.validate_config_change(agent_id, "system_prompt", None, prompt)
            if not ok:
                errors.append(reason)

        # Check schedule
        schedule = config.get("schedule", {})
        if schedule:
            ok, reason = Guardrails.validate_config_change(agent_id, "schedule", None, schedule)
            if not ok:
                errors.append(reason)

        return len(errors) == 0, errors
