"""SQLite persistence for agent executions, feedback, config changes, and metrics."""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


class AgentDB:
    """SQLite database for agent runtime data."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
        return self._conn

    def _init_db(self):
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                config_version INTEGER DEFAULT 1,
                success INTEGER NOT NULL,
                execution_time_ms INTEGER DEFAULT 0,
                emails_processed INTEGER DEFAULT 0,
                actions_taken TEXT DEFAULT '[]',
                result_data TEXT DEFAULT '{}',
                error TEXT
            );

            CREATE TABLE IF NOT EXISTS config_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                version_before INTEGER,
                version_after INTEGER,
                field_changed TEXT,
                old_value TEXT,
                new_value TEXT,
                reason TEXT,
                proposed_by TEXT DEFAULT 'user',
                approved INTEGER DEFAULT 1,
                reasoning TEXT
            );

            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                execution_id INTEGER,
                timestamp TEXT NOT NULL,
                feedback_type TEXT NOT NULL,
                feedback_data TEXT DEFAULT '{}',
                processed INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                date TEXT NOT NULL,
                total_executions INTEGER DEFAULT 0,
                successful INTEGER DEFAULT 0,
                failed INTEGER DEFAULT 0,
                avg_time_ms REAL DEFAULT 0,
                emails_processed INTEGER DEFAULT 0,
                positive_feedback INTEGER DEFAULT 0,
                negative_feedback INTEGER DEFAULT 0,
                UNIQUE(agent_id, date)
            );

            CREATE INDEX IF NOT EXISTS idx_exec_agent ON executions(agent_id);
            CREATE INDEX IF NOT EXISTS idx_exec_ts ON executions(timestamp);
            CREATE INDEX IF NOT EXISTS idx_feedback_agent ON feedback(agent_id);
            CREATE INDEX IF NOT EXISTS idx_config_agent ON config_changes(agent_id);
        """)
        conn.commit()

    # ── Executions ────────────────────────────────────────────

    def record_execution(self, agent_id: str, result: dict, config_version: int = 1) -> int:
        """Log an agent execution. Returns the execution ID."""
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            """INSERT INTO executions
               (agent_id, timestamp, config_version, success, execution_time_ms,
                emails_processed, actions_taken, result_data, error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                agent_id,
                now,
                config_version,
                1 if result.get("success") else 0,
                result.get("execution_time_ms", 0),
                result.get("emails_processed", 0),
                json.dumps(result.get("actions_taken", [])),
                json.dumps(result.get("data", {})),
                result.get("error"),
            ),
        )
        conn.commit()
        return cur.lastrowid

    def get_executions(self, agent_id: str | None = None, limit: int = 50) -> list[dict]:
        """Get recent executions, optionally filtered by agent."""
        conn = self._get_conn()
        if agent_id:
            rows = conn.execute(
                "SELECT * FROM executions WHERE agent_id = ? ORDER BY id DESC LIMIT ?",
                (agent_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM executions ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_execution_count(self) -> int:
        """Total execution count across all agents."""
        conn = self._get_conn()
        row = conn.execute("SELECT COUNT(*) FROM executions").fetchone()
        return row[0] if row else 0

    # ── Config Changes ────────────────────────────────────────

    def record_config_change(
        self,
        agent_id: str,
        version_before: int,
        version_after: int,
        field_changed: str,
        old_value,
        new_value,
        reason: str = "",
        proposed_by: str = "user",
        approved: bool = True,
        reasoning: str = "",
    ):
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT INTO config_changes
               (agent_id, timestamp, version_before, version_after,
                field_changed, old_value, new_value, reason, proposed_by, approved, reasoning)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                agent_id,
                now,
                version_before,
                version_after,
                field_changed,
                json.dumps(old_value),
                json.dumps(new_value),
                reason,
                proposed_by,
                1 if approved else 0,
                reasoning,
            ),
        )
        conn.commit()

    def get_audit_log(self, agent_id: str | None = None, limit: int = 50) -> list[dict]:
        """Get config change audit trail."""
        conn = self._get_conn()
        if agent_id:
            rows = conn.execute(
                "SELECT * FROM config_changes WHERE agent_id = ? ORDER BY id DESC LIMIT ?",
                (agent_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM config_changes ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Feedback ──────────────────────────────────────────────

    def record_feedback(
        self,
        agent_id: str,
        execution_id: int | None,
        feedback_type: str,
        feedback_data: dict | None = None,
    ):
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT INTO feedback
               (agent_id, execution_id, timestamp, feedback_type, feedback_data, processed)
               VALUES (?, ?, ?, ?, ?, 0)""",
            (agent_id, execution_id, now, feedback_type, json.dumps(feedback_data or {})),
        )
        conn.commit()

    def get_unprocessed_feedback(self, agent_id: str) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM feedback WHERE agent_id = ? AND processed = 0 ORDER BY id",
            (agent_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_feedback_processed(self, feedback_ids: list[int]):
        if not feedback_ids:
            return
        conn = self._get_conn()
        placeholders = ",".join("?" for _ in feedback_ids)
        conn.execute(
            f"UPDATE feedback SET processed = 1 WHERE id IN ({placeholders})",
            feedback_ids,
        )
        conn.commit()

    # ── Metrics ───────────────────────────────────────────────

    def update_daily_metrics(self, agent_id: str, result: dict):
        """Upsert daily aggregated metrics."""
        conn = self._get_conn()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        row = conn.execute(
            "SELECT * FROM metrics WHERE agent_id = ? AND date = ?",
            (agent_id, today),
        ).fetchone()

        success = 1 if result.get("success") else 0
        exec_time = result.get("execution_time_ms", 0)
        emails = result.get("emails_processed", 0)

        if row:
            total = row["total_executions"] + 1
            new_avg = ((row["avg_time_ms"] * row["total_executions"]) + exec_time) / total
            conn.execute(
                """UPDATE metrics SET
                   total_executions = ?, successful = successful + ?, failed = failed + ?,
                   avg_time_ms = ?, emails_processed = emails_processed + ?
                   WHERE agent_id = ? AND date = ?""",
                (total, success, 1 - success, new_avg, emails, agent_id, today),
            )
        else:
            conn.execute(
                """INSERT INTO metrics
                   (agent_id, date, total_executions, successful, failed, avg_time_ms, emails_processed)
                   VALUES (?, ?, 1, ?, ?, ?, ?)""",
                (agent_id, today, success, 1 - success, exec_time, emails),
            )
        conn.commit()

    def get_metrics(self, agent_id: str, days: int = 7) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM metrics WHERE agent_id = ? ORDER BY date DESC LIMIT ?",
            (agent_id, days),
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
