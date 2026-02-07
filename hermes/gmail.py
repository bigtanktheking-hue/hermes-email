"""Gmail API client — OAuth, fetch, modify."""
from __future__ import annotations

import base64
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from hermes.config import Config

_FIRST_RUN_MSG = """\
[bold yellow]First-time setup required![/bold yellow]

HERMES needs Gmail API credentials to work. Here's how:

1. Go to [link]https://console.cloud.google.com/[/link]
2. Create a new project (or select an existing one)
3. Enable the [bold]Gmail API[/bold]:
   APIs & Services → Library → search "Gmail API" → Enable
4. Create OAuth 2.0 credentials:
   APIs & Services → Credentials → Create Credentials → OAuth client ID
   - Application type: [bold]Desktop app[/bold]
   - Download the JSON file
5. Save it as [bold]credentials.json[/bold] in: {path}
6. Run HERMES again — a browser window will open for Gmail consent.
"""


class GmailClient:
    """Wraps the Gmail API with convenient methods."""

    def __init__(self, config: Config):
        self.config = config
        self._service = None

    @property
    def service(self):
        if self._service is None:
            self._service = self._authenticate()
        return self._service

    def _authenticate(self):
        """Authenticate via OAuth2, returning a Gmail API service."""
        creds = None
        token_path = self.config.token_path
        creds_path = self.config.credentials_path

        if not creds_path.exists():
            raise FileNotFoundError(
                _FIRST_RUN_MSG.format(path=self.config.project_dir)
            )

        if token_path.exists():
            creds = Credentials.from_authorized_user_file(
                str(token_path), self.config.gmail_scopes
            )

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                token_path.write_text(creds.to_json())
            elif os.environ.get("RENDER"):
                raise RuntimeError(
                    "Gmail token expired and cannot re-authenticate on cloud. "
                    "Re-generate token.json locally and update GMAIL_TOKEN_JSON env var."
                )
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(creds_path), self.config.gmail_scopes
                )
                creds = flow.run_local_server(port=0)
                token_path.write_text(creds.to_json())

        return build("gmail", "v1", credentials=creds)

    # ── Fetch methods ──────────────────────────────────────────────

    def get_messages(
        self, query: str = "", max_results: int = 50, with_body: bool = True
    ) -> list[dict]:
        """Fetch messages matching a Gmail query string.

        Returns list of dicts with keys: id, threadId, subject, from, to, date,
        snippet, labels, body_preview.
        """
        capped = min(max_results, self.config.max_messages_cap)
        if max_results > self.config.max_messages_cap:
            import logging
            logging.getLogger(__name__).info(
                "Capping fetch at %d messages (requested %d)", capped, max_results
            )

        results = (
            self.service.users()
            .messages()
            .list(userId="me", q=query, maxResults=capped)
            .execute()
        )
        message_ids = results.get("messages", [])
        if not message_ids:
            return []

        # Batch fetch for efficiency
        messages = []
        for i in range(0, len(message_ids), self.config.batch_fetch_size):
            batch_ids = message_ids[i : i + self.config.batch_fetch_size]
            batch_msgs = self._batch_get(batch_ids, with_body)
            messages.extend(batch_msgs)

        return messages

    def _batch_get(self, message_ids: list[dict], with_body: bool) -> list[dict]:
        """Batch-fetch message details."""
        messages = []
        fmt = "full" if with_body else "metadata"

        batch = self.service.new_batch_http_request()

        def callback(request_id, response, exception):
            if exception is None:
                messages.append(self._parse_message(response, with_body))

        for msg in message_ids:
            batch.add(
                self.service.users()
                .messages()
                .get(userId="me", id=msg["id"], format=fmt),
                callback=callback,
            )
        batch.execute()
        return messages

    def _parse_message(self, msg: dict, with_body: bool) -> dict:
        """Parse a raw Gmail message into a clean dict."""
        headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
        parsed = {
            "id": msg["id"],
            "threadId": msg.get("threadId", ""),
            "subject": headers.get("subject", "(no subject)"),
            "from": headers.get("from", ""),
            "to": headers.get("to", ""),
            "date": headers.get("date", ""),
            "snippet": msg.get("snippet", ""),
            "labels": msg.get("labelIds", []),
            "body_preview": "",
        }

        if with_body:
            parsed["body_preview"] = self._extract_body(
                msg.get("payload", {}), self.config.body_preview_chars
            )

        return parsed

    def _extract_body(self, payload: dict, max_chars: int) -> str:
        """Extract plain text body preview from message payload."""
        # Try to find text/plain part
        text = self._find_text_part(payload)
        if text:
            text = re.sub(r"<[^>]+>", "", text)  # strip any HTML tags
            text = re.sub(r"\s+", " ", text).strip()
            return text[:max_chars]
        return ""

    def _find_text_part(self, payload: dict) -> str:
        """Recursively find text/plain content in MIME parts."""
        mime = payload.get("mimeType", "")
        if mime == "text/plain":
            data = payload.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

        for part in payload.get("parts", []):
            text = self._find_text_part(part)
            if text:
                return text
        return ""

    def get_sent_messages(self, max_results: int = 200) -> list[dict]:
        """Fetch sent messages for VIP analysis."""
        return self.get_messages(
            query="in:sent", max_results=max_results, with_body=False
        )

    def get_unread_count(self) -> int:
        """Return the number of unread messages in inbox."""
        label = self.service.users().labels().get(userId="me", id="INBOX").execute()
        return label.get("messagesUnread", 0)

    def count_messages(self, query: str) -> int:
        """Count messages matching a query using pagination."""
        count = 0
        page_token = None
        while True:
            kwargs = {"userId": "me", "q": query, "maxResults": 500}
            if page_token:
                kwargs["pageToken"] = page_token
            results = self.service.users().messages().list(**kwargs).execute()
            count += len(results.get("messages", []))
            page_token = results.get("nextPageToken")
            if not page_token:
                break
        return count

    def estimate_messages(self, query: str) -> int:
        """Fast approximate count using Gmail's resultSizeEstimate."""
        results = (
            self.service.users()
            .messages()
            .list(userId="me", q=query, maxResults=1)
            .execute()
        )
        return results.get("resultSizeEstimate", 0)

    def get_message_by_id(self, msg_id: str) -> dict:
        """Fetch a single message by ID with full body."""
        msg = self.service.users().messages().get(
            userId="me", id=msg_id, format="full"
        ).execute()
        return self._parse_message_full(msg)

    def _parse_message_full(self, msg: dict) -> dict:
        """Parse a message with full body text (no truncation)."""
        headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
        body = self._find_text_part(msg.get("payload", {})) or ""
        body = re.sub(r"<[^>]+>", "", body)
        body = re.sub(r"\n{3,}", "\n\n", body).strip()
        return {
            "id": msg["id"],
            "threadId": msg.get("threadId", ""),
            "subject": headers.get("subject", "(no subject)"),
            "from": headers.get("from", ""),
            "to": headers.get("to", ""),
            "date": headers.get("date", ""),
            "message_id": headers.get("message-id", ""),
            "snippet": msg.get("snippet", ""),
            "labels": msg.get("labelIds", []),
            "body": body,
            "body_preview": body[:500],
        }

    # ── Write methods ──────────────────────────────────────────────

    def send_reply(self, to: str, subject: str, body: str, thread_id: str = "", message_id: str = ""):
        """Send a reply email."""
        import email.mime.text
        msg = email.mime.text.MIMEText(body)
        msg["to"] = to
        msg["subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
        if message_id:
            msg["In-Reply-To"] = message_id
            msg["References"] = message_id
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        send_body = {"raw": raw}
        if thread_id:
            send_body["threadId"] = thread_id
        result = self.service.users().messages().send(userId="me", body=send_body).execute()
        return result.get("id", "")

    def archive_messages(self, message_ids: list[str]):
        """Archive messages (remove INBOX label)."""
        self._batch_modify(message_ids, remove_labels=["INBOX"])

    def trash_messages(self, message_ids: list[str]):
        """Move messages to trash."""
        for msg_id in message_ids:
            self.service.users().messages().trash(userId="me", id=msg_id).execute()

    def mark_read(self, message_ids: list[str]):
        """Mark messages as read (remove UNREAD label)."""
        self._batch_modify(message_ids, remove_labels=["UNREAD"])

    def add_label(self, message_ids: list[str], label: str):
        """Add a label to messages. Creates the label if it doesn't exist."""
        label_id = self._get_or_create_label(label)
        self._batch_modify(message_ids, add_labels=[label_id])

    def batch_modify(self, message_ids: list[str], add_labels=None, remove_labels=None):
        """Public batch modify for flexible label changes."""
        self._batch_modify(message_ids, add_labels=add_labels or [], remove_labels=remove_labels or [])

    def _batch_modify(self, message_ids: list[str], add_labels=None, remove_labels=None):
        """Batch modify messages (add/remove labels)."""
        if not message_ids:
            return
        body = {}
        if add_labels:
            body["addLabelIds"] = add_labels
        if remove_labels:
            body["removeLabelIds"] = remove_labels
        body["ids"] = message_ids

        self.service.users().messages().batchModify(userId="me", body=body).execute()

    def _get_or_create_label(self, name: str) -> str:
        """Get label ID by name, creating it if needed."""
        labels = self.service.users().labels().list(userId="me").execute()
        for label in labels.get("labels", []):
            if label["name"].lower() == name.lower():
                return label["id"]
        created = (
            self.service.users()
            .labels()
            .create(
                userId="me",
                body={
                    "name": name,
                    "labelListVisibility": "labelShow",
                    "messageListVisibility": "show",
                },
            )
            .execute()
        )
        return created["id"]

    def search(self, query: str, max_results: int = 20) -> list[dict]:
        """Search for messages — convenience alias for REPL."""
        return self.get_messages(query=query, max_results=max_results)
