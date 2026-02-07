"""AI LLM wrapper — Ollama (local) and Groq (cloud) backends."""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

import httpx

from hermes.config import Config

log = logging.getLogger(__name__)

# ── Tool definitions for REPL chat mode ────────────────────────

HERMES_TOOLS = [
    {
        "name": "morning_briefing",
        "description": "Get a summary of recent emails (morning briefing). Use when the user asks what they missed, wants a summary, or asks about recent/overnight emails.",
        "input_schema": {
            "type": "object",
            "properties": {
                "hours_back": {
                    "type": "integer",
                    "description": "How many hours back to look. Default 12.",
                    "default": 12,
                }
            },
            "required": [],
        },
    },
    {
        "name": "priority_scan",
        "description": "Scan unread emails and classify by priority (high/medium/low). Use when the user asks about urgent, important, or priority emails, or asks if anything needs attention.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "vip_alert",
        "description": "Check for unread emails from VIP contacts (important people the user frequently emails). Use when the user asks about emails from important people or VIPs.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "newsletter_cleanup",
        "description": "Scan and clean up newsletters, promotions, and low-priority bulk emails. Use when the user wants to clean up, declutter, or manage newsletters/promotions.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "inbox_zero",
        "description": "Process inbox emails in batches, classifying each as action-needed, read-and-archive, or junk. Use when the user wants to reach inbox zero or process their inbox.",
        "input_schema": {
            "type": "object",
            "properties": {
                "batch_size": {
                    "type": "integer",
                    "description": "Number of emails per batch. Default 10.",
                    "default": 10,
                }
            },
            "required": [],
        },
    },
    {
        "name": "weekly_digest",
        "description": "Generate a weekly email digest with stats and a narrative summary. Use when the user asks for a digest, weekly summary, or email stats.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "search_emails",
        "description": "Search for emails using a Gmail query. Use when the user wants to find specific emails by sender, subject, date, or keywords.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Gmail search query (e.g., 'from:boss@company.com', 'subject:invoice', 'after:2024/01/01').",
                }
            },
            "required": ["query"],
        },
    },
]

# Map tool names to descriptions for REPL intent parsing
_TOOL_DESCRIPTIONS = "\n".join(
    f"- {t['name']}: {t['description']}" for t in HERMES_TOOLS
)


@dataclass
class OllamaResponse:
    """Mimics the shape needed by cli.py chat loop."""
    text: str
    stop_reason: str = "end_turn"
    content: list = None
    tool_name: str = None
    tool_input: dict = None

    def __post_init__(self):
        if self.content is None:
            self.content = [_TextBlock(self.text)]


@dataclass
class _TextBlock:
    text: str
    type: str = "text"


@dataclass
class _ToolBlock:
    name: str
    input: dict
    id: str = "tool_001"
    type: str = "tool_use"


class AIClient:
    """Wraps Ollama (local) or Groq (cloud) LLM for email intelligence."""

    def __init__(self, config: Config):
        self.config = config
        self.backend = config.ai_backend  # "ollama" or "groq"
        self.base_url = config.ollama_url.rstrip("/")
        self.model = config.ollama_model
        self._client = httpx.Client(timeout=120.0)

        if self.backend == "groq":
            self.model = config.groq_model
            self.base_url = config.groq_url.rstrip("/")
            self._groq_key = config.groq_api_key
            log.info("AI backend: Groq (%s)", self.model)
        else:
            log.info("AI backend: Ollama (%s)", self.model)

    # ── Backend-specific generate/chat ─────────────────────────

    def _generate(self, prompt: str, system: str = "") -> str:
        """Send a prompt and return the response text."""
        if self.backend == "groq":
            return self._generate_groq(prompt, system)
        return self._generate_ollama(prompt, system)

    def _chat(self, messages: list[dict], system: str = "") -> str:
        """Send a chat completion and return the response text."""
        if self.backend == "groq":
            return self._chat_groq(messages, system)
        return self._chat_ollama(messages, system)

    # ── Ollama ─────────────────────────────────────────────────

    def _generate_ollama(self, prompt: str, system: str = "") -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 2000},
        }
        resp = self._client.post(f"{self.base_url}/api/generate", json=payload)
        resp.raise_for_status()
        return resp.json().get("response", "")

    def _chat_ollama(self, messages: list[dict], system: str = "") -> str:
        ollama_msgs = []
        if system:
            ollama_msgs.append({"role": "system", "content": system})
        for m in messages:
            if isinstance(m.get("content"), str):
                ollama_msgs.append({"role": m["role"], "content": m["content"]})
            elif isinstance(m.get("content"), list):
                parts = []
                for item in m["content"]:
                    if isinstance(item, dict) and "content" in item:
                        parts.append(str(item["content"]))
                    elif hasattr(item, "text"):
                        parts.append(item.text)
                if parts:
                    ollama_msgs.append({"role": m["role"], "content": "\n".join(parts)})

        payload = {
            "model": self.model,
            "messages": ollama_msgs,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 2000},
        }
        resp = self._client.post(f"{self.base_url}/api/chat", json=payload)
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "")

    # ── Groq (OpenAI-compatible) ───────────────────────────────

    def _groq_request(self, messages: list[dict]) -> str:
        """Send a request to Groq with retry on 429."""
        headers = {
            "Authorization": f"Bearer {self._groq_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 2000,
        }
        for attempt in range(4):
            resp = self._client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
            if resp.status_code == 429:
                wait = min(2 ** attempt, 15)
                log.warning("Groq rate limited, retrying in %ds...", wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        resp.raise_for_status()
        return ""

    def _generate_groq(self, prompt: str, system: str = "") -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self._groq_request(messages)

    def _chat_groq(self, messages: list[dict], system: str = "") -> str:
        groq_msgs = []
        if system:
            groq_msgs.append({"role": "system", "content": system})
        for m in messages:
            if isinstance(m.get("content"), str):
                groq_msgs.append({"role": m["role"], "content": m["content"]})
            elif isinstance(m.get("content"), list):
                parts = []
                for item in m["content"]:
                    if isinstance(item, dict) and "content" in item:
                        parts.append(str(item["content"]))
                    elif hasattr(item, "text"):
                        parts.append(item.text)
                if parts:
                    groq_msgs.append({"role": m["role"], "content": "\n".join(parts)})
        return self._groq_request(groq_msgs)

    # ── Public methods (unchanged interface) ───────────────────

    def summarize_emails(self, emails: list[dict]) -> dict:
        """Summarize a batch of emails into action items, FYI, and highlights."""
        email_text = self._format_emails_for_prompt(emails)

        text = self._generate(
            prompt=f"""Analyze these emails and provide a morning briefing summary.

{email_text}

Respond in this exact JSON format (no extra text, no markdown fences):
{{"summary": "Brief 1-2 sentence overview of the inbox state", "action_items": ["List of emails that need a response or action, with sender and subject"], "fyi": ["List of informational emails worth knowing about"], "highlights": ["Any notable or interesting items"]}}

Be concise. Only include genuinely important items in action_items.""",
            system="You are HERMES, an email assistant. Respond ONLY with valid JSON. No markdown fences. No explanation.",
        )
        return self._parse_json_response(text, {
            "summary": "No emails to summarize.",
            "action_items": [],
            "fyi": [],
            "highlights": [],
        })

    def classify_priority(self, emails: list[dict]) -> list[dict]:
        """Classify emails by priority: high, medium, low."""
        email_text = self._format_emails_for_prompt(emails)

        text = self._generate(
            prompt=f"""Classify each email by priority level.

{email_text}

Respond with a JSON array. For each email:
{{"id": "<email id>", "priority": "high" | "medium" | "low", "reason": "Brief reason for classification"}}

Classification guidelines:
- HIGH: Direct request requiring your action, time-sensitive, from a person (not automated), mentions deadlines or urgent language
- MEDIUM: Informational but relevant to your work, may need action eventually
- LOW: Newsletters, automated notifications, marketing, social media alerts

Be conservative — most emails are medium or low. Only mark as high if it truly requires prompt attention.
Respond ONLY with a JSON array. No other text.""",
            system="You are HERMES, an email assistant. Respond ONLY with valid JSON. No markdown fences. Be conservative with high priority.",
        )
        return self._parse_json_response(text, [])

    def classify_junk(self, emails: list[dict]) -> list[dict]:
        """Classify emails as archive, delete, or keep."""
        email_text = self._format_emails_for_prompt(emails)

        text = self._generate(
            prompt=f"""Classify each email for cleanup. These are from promotional/update categories.

{email_text}

Respond with a JSON array. For each email:
{{"id": "<email id>", "action": "archive" | "delete" | "keep", "reason": "Brief reason"}}

Guidelines:
- ARCHIVE: Newsletters you might want later, order confirmations, routine notifications
- DELETE: Pure spam, expired promotions, duplicate notifications
- KEEP: Anything that might need action or contains important information

Respond ONLY with a JSON array. No other text.""",
            system="You are HERMES, an email assistant. Respond ONLY with valid JSON. No markdown fences.",
        )
        return self._parse_json_response(text, [])

    def classify_inbox(self, emails: list[dict]) -> list[dict]:
        """Classify inbox emails for inbox-zero processing."""
        email_text = self._format_emails_for_prompt(emails)

        text = self._generate(
            prompt=f"""Help me reach inbox zero. Classify each email.

{email_text}

Respond with a JSON array. For each email:
{{"id": "<email id>", "action": "action_needed" | "read_archive" | "junk", "reason": "Brief reason"}}

Guidelines:
- ACTION_NEEDED: Requires a reply, decision, or task from the user. Keep in inbox.
- READ_ARCHIVE: Informational, already read, or FYI only. Safe to archive.
- JUNK: Spam, expired promos, irrelevant notifications. Safe to trash.

Respond ONLY with a JSON array. No other text.""",
            system="You are HERMES, an email assistant. Respond ONLY with valid JSON. No markdown fences.",
        )
        return self._parse_json_response(text, [])

    def generate_digest_narrative(self, stats: dict) -> str:
        """Generate a narrative summary for a weekly digest."""
        text = self._generate(
            prompt=f"""Write a brief, friendly weekly email digest narrative based on these stats:

{json.dumps(stats, indent=2)}

Keep it to 3-4 sentences. Mention notable patterns, busiest day, and any suggestions. Be conversational.""",
            system="You are HERMES, a friendly email assistant. Be concise and conversational.",
        )
        return text.strip()

    def draft_reply(self, email: dict) -> str:
        """Generate a professional draft reply for an email."""
        text = self._generate(
            prompt=f"""Draft a professional reply to this email.

From: {email.get('from', 'unknown')}
Subject: {email.get('subject', '(no subject)')}
Date: {email.get('date', '')}
Body: {email.get('body_preview', email.get('snippet', ''))}

Write a concise, professional reply. Match the tone of the original email.
If the email is a notification/newsletter/automated message that doesn't need a reply, respond with exactly: NO_REPLY_NEEDED
Otherwise, write just the reply body text (no subject line, no greeting headers like "Dear X" unless appropriate). Keep it brief and actionable.""",
            system="You are HERMES, drafting email replies on behalf of the user. Be professional, concise, and match the sender's tone. The user works in the entertainment/music industry.",
        )
        return text.strip()

    def batch_draft_replies(self, emails: list[dict]) -> list[dict]:
        """Generate draft replies for a batch of emails."""
        results = []
        for email in emails:
            try:
                reply = self.draft_reply(email)
                needs_reply = reply != "NO_REPLY_NEEDED"
                results.append({
                    "id": email["id"],
                    "from": email.get("from", ""),
                    "subject": email.get("subject", ""),
                    "draft": reply if needs_reply else None,
                    "needs_reply": needs_reply,
                })
            except Exception as e:
                results.append({
                    "id": email["id"],
                    "from": email.get("from", ""),
                    "subject": email.get("subject", ""),
                    "draft": None,
                    "needs_reply": False,
                    "error": str(e),
                })
        return results

    def chat(self, messages: list[dict]) -> OllamaResponse:
        """Chat mode with tool dispatch via intent parsing.

        Returns an OllamaResponse that mimics the shape cli.py expects.
        """
        system = f"""You are HERMES, a helpful email assistant. You help users manage their Gmail inbox.

When the user asks about their email, you should call one of these tools by responding with EXACTLY this JSON format:
{{"tool": "tool_name", "args": {{}}}}

Available tools:
{_TOOL_DESCRIPTIONS}

If the user is just chatting or the request doesn't match a tool, respond normally with text.
If a tool matches, respond ONLY with the JSON tool call. No other text."""

        text = self._chat(messages, system=system)

        # Check if the response is a tool call
        parsed = self._try_parse_tool_call(text)
        if parsed:
            tool_name, tool_args = parsed
            block = _ToolBlock(name=tool_name, input=tool_args)
            resp = OllamaResponse(text="", stop_reason="tool_use")
            resp.content = [block]
            return resp

        return OllamaResponse(text=text, stop_reason="end_turn")

    # ── Helpers ────────────────────────────────────────────────────

    def _try_parse_tool_call(self, text: str) -> tuple | None:
        """Try to parse a tool call from LLM response."""
        text = text.strip()
        # Strip markdown fences
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        try:
            data = json.loads(text)
            if isinstance(data, dict) and "tool" in data:
                tool_name = data["tool"]
                tool_args = data.get("args", {})
                valid_tools = {t["name"] for t in HERMES_TOOLS}
                if tool_name in valid_tools:
                    return tool_name, tool_args
        except (json.JSONDecodeError, KeyError):
            pass
        return None

    def _format_emails_for_prompt(self, emails: list[dict]) -> str:
        """Format emails into a compact text block for prompts."""
        parts = []
        for i, e in enumerate(emails, 1):
            lines = [
                f"--- Email {i} (id: {e['id']}) ---",
                f"From: {e.get('from', 'unknown')}",
                f"Subject: {e.get('subject', '(no subject)')}",
                f"Date: {e.get('date', '')}",
            ]
            preview = e.get("body_preview") or e.get("snippet", "")
            if preview:
                lines.append(f"Preview: {preview[:300]}")
            parts.append("\n".join(lines))
        return "\n\n".join(parts)

    def _parse_json_response(self, text: str, default):
        """Parse JSON from LLM response, with fallback."""
        text = text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        # Try to extract JSON from mixed text
        for start_char, end_char in [("[", "]"), ("{", "}")]:
            idx_start = text.find(start_char)
            idx_end = text.rfind(end_char)
            if idx_start != -1 and idx_end > idx_start:
                candidate = text[idx_start:idx_end + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    continue

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return default
