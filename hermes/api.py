"""Flask REST API + Web UI for HERMES."""
from __future__ import annotations

import json
import os
import secrets
import traceback
from collections import Counter
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

from flask import Flask, jsonify, request, render_template, redirect, url_for, session

from hermes.ai import AIClient, HERMES_TOOLS
from hermes.auth import check_password, require_auth, _check_api_key, _is_rate_limited, _record_failed_attempt
from hermes.config import load_config
from hermes.gmail import GmailClient
from hermes.vip import (
    get_vip_domain_emails,
    get_vip_emails,
    is_vip_domain,
    load_vip_domains,
    load_vips,
    needs_refresh,
    detect_vips,
    save_vips,
)

# -- App setup --

_pkg_dir = Path(__file__).resolve().parent
_project_dir = _pkg_dir.parent

app = Flask(
    __name__,
    template_folder=str(_project_dir / "templates"),
    static_folder=str(_project_dir / "static"),
)

# Session config -- fix secret key for production
_secret = os.environ.get("SECRET_KEY") or os.environ.get("HERMES_WEB_PASSWORD")
if not _secret and os.environ.get("RENDER"):
    raise RuntimeError("SECRET_KEY required in production")
app.secret_key = _secret or "hermes-dev-key-" + str(os.getpid())
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Request size limit (16MB)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

# Session timeout (2 hours)
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=2)

# -- Lazy-init singletons --

_config = None
_gmail = None
_ai = None


def _get_clients():
    global _config, _gmail, _ai
    if _config is None:
        _config = load_config()
        _gmail = GmailClient(_config)
        _ai = AIClient(_config)
    return _config, _gmail, _ai


# -- Security headers --

@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "font-src 'self'; "
        "img-src 'self' data:; "
        "connect-src 'self'"
    )
    return response


# -- Centralized error handlers --

@app.errorhandler(404)
def not_found_error(error):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(500)
def internal_error(error):
    app.logger.error(traceback.format_exc())
    return jsonify({"error": "Internal server error"}), 500


# -- CSRF helper --

def _check_csrf():
    """Check CSRF token for session-authenticated POST requests.
    Returns None if OK, or a JSON error response if failed."""
    # Skip CSRF if request has valid API key (programmatic access)
    provided_key = request.headers.get("X-API-Key", "")
    if provided_key and _check_api_key(provided_key):
        return None
    # For session-authenticated requests, verify CSRF token
    if session.get("authenticated"):
        csrf_token = request.headers.get("X-CSRF-Token", "")
        expected = session.get("csrf_token", "")
        if not expected or not csrf_token or csrf_token != expected:
            return jsonify({"error": "CSRF token missing or invalid"}), 403
    return None


# -- Login / Logout --

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        # Rate limiting check
        client_ip = request.remote_addr or "unknown"
        if _is_rate_limited(client_ip):
            return render_template("login.html", error="Too many failed attempts. Try again later."), 429

        password = request.form.get("password", "")
        if check_password(password):
            session["authenticated"] = True
            session.permanent = True
            # Generate CSRF token for the session
            session.setdefault("csrf_token", secrets.token_hex(32))
            return redirect(url_for("index"))
        _record_failed_attempt(client_ip)
        return render_template("login.html", error="Wrong password"), 401
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# -- Web UI --

@app.route("/")
@require_auth
def index():
    # Ensure CSRF token exists in session
    session.setdefault("csrf_token", secrets.token_hex(32))
    return render_template("index.html", csrf_token=session["csrf_token"])


# -- Health --

@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "service": "hermes"})


@app.route("/api/health/ai")
@require_auth
def health_ai():
    """Check AI backend connectivity."""
    try:
        config, gmail, ai = _get_clients()
        result = ai.health_check()
        status_code = 200 if result.get("status") == "ok" else 503
        return jsonify(result), status_code
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify({"status": "error", "error": "Internal server error"}), 500


# -- Stats (quick dashboard load) --

@app.route("/api/stats")
@require_auth
def stats():
    try:
        config, gmail, ai = _get_clients()
        unread = gmail.get_unread_count()

        vip_domains = load_vip_domains(config)
        vips = load_vips(config)

        # Accurate VIP unread count via pagination
        query_parts = []
        for addr in get_vip_emails(vips):
            query_parts.append(f"from:{addr}")
        for domain in get_vip_domain_emails(vip_domains):
            query_parts.append(f"from:@{domain}")

        vip_unread = 0
        if query_parts:
            query = f"is:unread in:inbox ({' OR '.join(query_parts)})"
            vip_unread = gmail.estimate_messages(query)

        return jsonify({
            "unread": unread,
            "vip_unread": vip_unread,
            "vip_contacts": len(vips),
            "vip_domains": len(vip_domains),
        })
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error"}), 500


# -- Emails List --

@app.route("/api/emails")
@require_auth
def emails_list():
    """Paginated list of unread emails."""
    try:
        config, gmail, ai = _get_clients()
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 20, type=int)
        # Input validation
        page = max(1, page)
        per_page = max(1, min(per_page, 50))
        q = request.args.get("q", "is:unread in:inbox")

        emails = gmail.get_messages(query=q, max_results=per_page, with_body=True)

        results = []
        for e in emails:
            results.append({
                "id": e["id"],
                "from": e.get("from", ""),
                "subject": e.get("subject", "(no subject)"),
                "date": e.get("date", ""),
                "snippet": e.get("snippet", ""),
                "body_preview": e.get("body_preview", ""),
                "labels": e.get("labels", []),
            })

        return jsonify({
            "emails": results,
            "count": len(results),
        })
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error"}), 500


# -- Email Detail --

@app.route("/api/email/<email_id>")
@require_auth
def email_detail(email_id):
    """Get full email detail by ID."""
    try:
        config, gmail, ai = _get_clients()
        email = gmail.get_message_by_id(email_id)
        return jsonify(email)
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error"}), 500


# -- Send Reply --

@app.route("/api/send-reply", methods=["POST"])
@require_auth
def send_reply():
    """Send a reply to an email."""
    # CSRF check
    csrf_err = _check_csrf()
    if csrf_err:
        return csrf_err
    try:
        config, gmail, ai = _get_clients()
        data = request.get_json(force=True)
        email_id = data.get("email_id", "")
        reply_body = data.get("body", "")

        # Input validation
        if not isinstance(email_id, str) or not email_id.strip():
            return jsonify({"error": "email_id must be a non-empty string"}), 400
        if not isinstance(reply_body, str) or not reply_body.strip():
            return jsonify({"error": "body must be a non-empty string"}), 400
        if len(reply_body) > 50000:
            return jsonify({"error": "body must be less than 50000 characters"}), 400

        # Get original email for threading
        original = gmail.get_message_by_id(email_id)
        sender = original.get("from", "")
        # Extract just the email address
        import re as _re
        match = _re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", sender)
        to_addr = match.group(0) if match else sender

        msg_id = gmail.send_reply(
            to=to_addr,
            subject=original.get("subject", ""),
            body=reply_body,
            thread_id=original.get("threadId", ""),
            message_id=original.get("message_id", ""),
        )

        # Mark original as read
        gmail.mark_read([email_id])

        return jsonify({"sent": True, "message_id": msg_id, "to": to_addr})
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error"}), 500


# -- VIP Domain People --

@app.route("/api/vip/domain-people")
@require_auth
def vip_domain_people():
    """Get actual people who emailed from VIP domains."""
    try:
        config, gmail, ai = _get_clients()
        vip_domains = load_vip_domains(config)

        if not vip_domains:
            return jsonify({"people": []})

        query_parts = [f"from:@{d['domain']}" for d in vip_domains]
        query = f"is:unread in:inbox ({' OR '.join(query_parts)})"
        emails = gmail.get_messages(query=query, max_results=100, with_body=False)

        # Group by sender
        people = {}
        for e in emails:
            sender = e.get("from", "")
            if sender not in people:
                people[sender] = {"from": sender, "count": 0, "latest_subject": "", "latest_date": ""}
            people[sender]["count"] += 1
            if not people[sender]["latest_subject"]:
                people[sender]["latest_subject"] = e.get("subject", "")
                people[sender]["latest_date"] = e.get("date", "")

        sorted_people = sorted(people.values(), key=lambda x: x["count"], reverse=True)
        return jsonify({"people": sorted_people, "total": len(emails)})
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error"}), 500


# -- Draft Reply --

@app.route("/api/draft-reply", methods=["POST"])
@require_auth
def draft_reply():
    """Generate an AI draft reply for a single email."""
    # CSRF check
    csrf_err = _check_csrf()
    if csrf_err:
        return csrf_err
    try:
        config, gmail, ai = _get_clients()
        data = request.get_json(force=True)
        email_id = data.get("email_id", "")

        # Input validation
        if not isinstance(email_id, str) or not email_id.strip():
            return jsonify({"error": "email_id must be a non-empty string"}), 400

        email = gmail.get_message_by_id(email_id)
        reply = ai.draft_reply(email)
        needs_reply = reply != "NO_REPLY_NEEDED"

        return jsonify({
            "email_id": email_id,
            "from": email.get("from", ""),
            "subject": email.get("subject", ""),
            "draft": reply if needs_reply else None,
            "needs_reply": needs_reply,
        })
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/draft-replies-batch", methods=["POST"])
@require_auth
def draft_replies_batch():
    """Generate AI draft replies for recent unread emails that need responses."""
    # CSRF check
    csrf_err = _check_csrf()
    if csrf_err:
        return csrf_err
    try:
        config, gmail, ai = _get_clients()
        data = request.get_json(force=True) if request.is_json else {}
        count = data.get("count", 10)
        count = min(count, 20)

        emails = gmail.get_messages(query="is:unread in:inbox", max_results=count, with_body=True)
        if not emails:
            return jsonify({"drafts": [], "count": 0})

        results = ai.batch_draft_replies(emails)

        return jsonify({
            "drafts": results,
            "count": len(results),
            "needs_reply": sum(1 for r in results if r.get("needs_reply")),
        })
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error"}), 500


# -- Chat --

@app.route("/api/chat", methods=["POST"])
@require_auth
def chat():
    # CSRF check
    csrf_err = _check_csrf()
    if csrf_err:
        return csrf_err
    try:
        config, gmail, ai = _get_clients()
        data = request.get_json(force=True)
        messages = data.get("messages", [])
        voice_mode = bool(data.get("voice_mode", False))

        # Input validation
        if not isinstance(messages, list) or len(messages) == 0:
            return jsonify({"error": "messages must be a non-empty list"}), 400

        resp = ai.chat(messages, voice_mode=voice_mode)

        # If AI wants to call a tool, execute it server-side
        if resp.stop_reason == "tool_use":
            for block in resp.content:
                if hasattr(block, "name"):
                    tool_result = _execute_tool(block.name, block.input, config, gmail, ai)
                    # Send tool result back to AI for a natural language summary
                    messages.append({"role": "assistant", "content": f'{{"tool": "{block.name}", "args": {json.dumps(block.input)}}}'})
                    if voice_mode:
                        summary_prompt = f"Tool result:\n{tool_result}\n\nSummarize this very briefly in 2-3 short spoken sentences. No lists, no bullet points."
                    else:
                        summary_prompt = f"Tool result:\n{tool_result}\n\nPlease summarize this result for me in a conversational way."
                    messages.append({"role": "user", "content": summary_prompt})
                    summary_resp = ai.chat(messages, voice_mode=voice_mode)
                    return jsonify({"response": summary_resp.text, "tool_used": block.name})

        return jsonify({"response": resp.text})
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error"}), 500


def _execute_tool(name: str, args: dict, config, gmail, ai) -> str:
    """Execute a HERMES tool and return text result."""
    try:
        if name == "morning_briefing":
            hours = args.get("hours_back", 12)
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
            epoch = int(cutoff.timestamp())
            emails = gmail.get_messages(query=f"after:{epoch} in:inbox", max_results=100)
            if not emails:
                return f"No emails in the last {hours} hours."
            summary = ai.summarize_emails(emails)
            return json.dumps({"email_count": len(emails), **summary})

        elif name == "priority_scan":
            emails = gmail.get_messages(query="is:unread in:inbox", max_results=50)
            if not emails:
                return "No unread emails in your inbox."
            classifications = ai.classify_priority(emails)
            email_map = {e["id"]: e for e in emails}
            for c in classifications:
                e = email_map.get(c.get("id"), {})
                c["from"] = e.get("from", "")
                c["subject"] = e.get("subject", "")
            high = [c for c in classifications if c.get("priority") == "high"]
            med = [c for c in classifications if c.get("priority") == "medium"]
            low = [c for c in classifications if c.get("priority") == "low"]
            return json.dumps({"total": len(emails), "high": len(high), "medium": len(med), "low": len(low), "high_items": high})

        elif name == "vip_alert":
            vips = load_vips(config)
            vip_domains = load_vip_domains(config)
            query_parts = []
            for addr in get_vip_emails(vips):
                query_parts.append(f"from:{addr}")
            for domain in get_vip_domain_emails(vip_domains):
                query_parts.append(f"from:@{domain}")
            if not query_parts:
                return "No VIP contacts configured."
            query = f"is:unread in:inbox ({' OR '.join(query_parts)})"
            emails = gmail.get_messages(query=query, max_results=50)
            if not emails:
                return "No unread emails from VIP contacts."
            items = [{"from": e.get("from", ""), "subject": e.get("subject", "")} for e in emails]
            return json.dumps({"count": len(emails), "emails": items})

        elif name == "newsletter_cleanup":
            emails = gmail.get_messages(query="in:inbox category:promotions OR category:updates", max_results=50)
            if not emails:
                return "No newsletters or promotions to clean up."
            classifications = ai.classify_junk(emails)
            valid_ids = {e["id"] for e in emails}
            classifications = [c for c in classifications if c.get("id") in valid_ids]
            to_archive = [c for c in classifications if c.get("action") == "archive"]
            to_delete = [c for c in classifications if c.get("action") == "delete"]
            if to_archive:
                gmail.archive_messages([c["id"] for c in to_archive])
            if to_delete:
                gmail.trash_messages([c["id"] for c in to_delete])
            return json.dumps({"scanned": len(emails), "archived": len(to_archive), "deleted": len(to_delete)})

        elif name == "inbox_zero":
            batch_size = args.get("batch_size", 10)
            emails = gmail.get_messages(query="is:unread in:inbox", max_results=batch_size)
            if not emails:
                return "Inbox zero achieved! No unread emails."
            classifications = ai.classify_inbox(emails)
            valid_ids = {e["id"] for e in emails}
            classifications = [c for c in classifications if c.get("id") in valid_ids]
            read_archive = [c for c in classifications if c.get("action") == "read_archive"]
            junk_items = [c for c in classifications if c.get("action") == "junk"]
            action_needed = [c for c in classifications if c.get("action") == "action_needed"]
            if read_archive:
                ids = [c["id"] for c in read_archive]
                gmail.archive_messages(ids)
                gmail.mark_read(ids)
            if junk_items:
                gmail.trash_messages([c["id"] for c in junk_items])
            remaining = gmail.get_unread_count()
            return json.dumps({"processed": len(emails), "archived": len(read_archive), "trashed": len(junk_items), "kept": len(action_needed), "remaining": remaining})

        elif name == "weekly_digest":
            week_ago = datetime.now(timezone.utc) - timedelta(days=7)
            epoch = int(week_ago.timestamp())
            received = gmail.get_messages(query=f"after:{epoch} in:inbox", max_results=200, with_body=False)
            sent = gmail.get_messages(query=f"after:{epoch} in:sent", max_results=200, with_body=False)
            unread = gmail.get_unread_count()
            day_counter = Counter()
            sender_counter = Counter()
            for msg in received:
                date = _safe_parse_date(msg.get("date", ""))
                if date:
                    day_counter[date.strftime("%A")] += 1
                sender = msg.get("from", "")
                if "<" in sender:
                    sender = sender.split("<")[0].strip().strip('"')
                sender_counter[sender] += 1
            busiest = day_counter.most_common(1)[0][0] if day_counter else "N/A"
            top = [s for s, _ in sender_counter.most_common(5)]
            stats_data = {"received": len(received), "sent": len(sent), "busiest_day": busiest, "top_senders": top, "unread": unread}
            narrative = ai.generate_digest_narrative(stats_data)
            return json.dumps({**stats_data, "narrative": narrative})

        elif name == "search_emails":
            query = args.get("query", "")
            if not query:
                return "No search query provided."
            emails = gmail.search(query, max_results=20)
            if not emails:
                return "No emails found."
            items = [{"from": e.get("from", ""), "subject": e.get("subject", ""), "date": e.get("date", "")} for e in emails]
            return json.dumps({"count": len(emails), "results": items})

        return f"Unknown tool: {name}"
    except Exception as e:
        return f"Error executing {name}: {str(e)}"


# -- Briefing --

@app.route("/api/briefing")
@require_auth
def briefing():
    try:
        config, gmail, ai = _get_clients()
        hours = request.args.get("hours", 12, type=int)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        epoch = int(cutoff.timestamp())

        emails = gmail.get_messages(query=f"after:{epoch} in:inbox", max_results=100)
        if not emails:
            return jsonify({"email_count": 0, "summary": f"No emails in the last {hours} hours."})

        summary = ai.summarize_emails(emails)
        return jsonify({
            "email_count": len(emails),
            "hours_back": hours,
            **summary,
        })
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error"}), 500


# -- Priority --

@app.route("/api/priority")
@require_auth
def priority():
    try:
        config, gmail, ai = _get_clients()
        emails = gmail.get_messages(query="is:unread in:inbox", max_results=50)
        if not emails:
            return jsonify({"email_count": 0, "classifications": []})

        classifications = ai.classify_priority(emails)
        # Enrich with email metadata
        email_map = {e["id"]: e for e in emails}
        for c in classifications:
            e = email_map.get(c.get("id"), {})
            c["from"] = e.get("from", "")
            c["subject"] = e.get("subject", "")

        high = [c for c in classifications if c.get("priority") == "high"]
        return jsonify({
            "email_count": len(emails),
            "high_count": len(high),
            "classifications": classifications,
        })
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error"}), 500


# -- VIP --

@app.route("/api/vip")
@require_auth
def vip():
    try:
        config, gmail, ai = _get_clients()

        # Refresh if stale
        if needs_refresh(config):
            sent = gmail.get_sent_messages(max_results=200)
            vips = detect_vips(sent, config)
            save_vips(vips, config)
        else:
            vips = load_vips(config)

        vip_domains = load_vip_domains(config)

        # Build query
        query_parts = []
        for addr in get_vip_emails(vips):
            query_parts.append(f"from:{addr}")
        for domain in get_vip_domain_emails(vip_domains):
            query_parts.append(f"from:@{domain}")

        if not query_parts:
            return jsonify({"email_count": 0, "emails": [], "message": "No VIP contacts configured."})

        query = f"is:unread in:inbox ({' OR '.join(query_parts)})"
        emails = gmail.get_messages(query=query, max_results=50)

        results = []
        for e in emails:
            results.append({
                "id": e["id"],
                "from": e.get("from", ""),
                "subject": e.get("subject", ""),
                "date": e.get("date", ""),
                "snippet": e.get("snippet", ""),
            })

        return jsonify({
            "email_count": len(results),
            "vip_contacts": len(vips),
            "vip_domains": len(vip_domains),
            "emails": results,
        })
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error"}), 500


# -- Cleanup --

@app.route("/api/cleanup", methods=["POST"])
@require_auth
def cleanup():
    """Auto-cleanup newsletters/promotions -- no confirmation prompt."""
    # CSRF check
    csrf_err = _check_csrf()
    if csrf_err:
        return csrf_err
    try:
        config, gmail, ai = _get_clients()
        emails = gmail.get_messages(
            query="in:inbox category:promotions OR category:updates",
            max_results=50,
        )
        if not emails:
            return jsonify({"email_count": 0, "archived": 0, "deleted": 0, "kept": 0})

        classifications = ai.classify_junk(emails)
        valid_ids = {e["id"] for e in emails}
        classifications = [c for c in classifications if c.get("id") in valid_ids]
        to_archive = [c for c in classifications if c.get("action") == "archive"]
        to_delete = [c for c in classifications if c.get("action") == "delete"]
        to_keep = [c for c in classifications if c.get("action") == "keep"]

        if to_archive:
            gmail.archive_messages([c["id"] for c in to_archive])
        if to_delete:
            gmail.trash_messages([c["id"] for c in to_delete])

        return jsonify({
            "email_count": len(emails),
            "archived": len(to_archive),
            "deleted": len(to_delete),
            "kept": len(to_keep),
        })
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error"}), 500


# -- Inbox Zero --

@app.route("/api/inbox-zero", methods=["POST"])
@require_auth
def inbox_zero():
    """Process one batch of inbox emails -- no confirmation prompt."""
    # CSRF check
    csrf_err = _check_csrf()
    if csrf_err:
        return csrf_err
    try:
        config, gmail, ai = _get_clients()
        batch_size = request.args.get("batch", 10, type=int)
        # Input validation
        batch_size = max(1, min(batch_size, 50))

        emails = gmail.get_messages(query="is:unread in:inbox", max_results=batch_size)
        if not emails:
            return jsonify({
                "email_count": 0, "archived": 0, "trashed": 0,
                "kept_for_action": 0, "inbox_zero": True,
            })

        classifications = ai.classify_inbox(emails)
        valid_ids = {e["id"] for e in emails}
        classifications = [c for c in classifications if c.get("id") in valid_ids]
        action_needed = [c for c in classifications if c.get("action") == "action_needed"]
        read_archive = [c for c in classifications if c.get("action") == "read_archive"]
        junk = [c for c in classifications if c.get("action") == "junk"]

        if read_archive:
            ids = [c["id"] for c in read_archive]
            gmail.archive_messages(ids)
            gmail.mark_read(ids)
        if junk:
            gmail.trash_messages([c["id"] for c in junk])

        unread_remaining = gmail.get_unread_count()

        return jsonify({
            "email_count": len(emails),
            "archived": len(read_archive),
            "trashed": len(junk),
            "kept_for_action": len(action_needed),
            "unread_remaining": unread_remaining,
            "inbox_zero": unread_remaining == 0,
        })
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error"}), 500


# -- Digest --

@app.route("/api/digest")
@require_auth
def digest():
    try:
        config, gmail, ai = _get_clients()
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        epoch = int(week_ago.timestamp())

        received = gmail.get_messages(query=f"after:{epoch} in:inbox", max_results=200, with_body=False)
        sent = gmail.get_messages(query=f"after:{epoch} in:sent", max_results=200, with_body=False)
        unread_count = gmail.get_unread_count()

        day_counter = Counter()
        sender_counter = Counter()
        for msg in received:
            date = _safe_parse_date(msg.get("date", ""))
            if date:
                day_counter[date.strftime("%A")] += 1
            sender = msg.get("from", "")
            if "<" in sender:
                sender = sender.split("<")[0].strip().strip('"')
            sender_counter[sender] += 1

        busiest_day = day_counter.most_common(1)[0][0] if day_counter else "N/A"
        top_senders = [s for s, _ in sender_counter.most_common(5)]

        stats_data = {
            "received": len(received),
            "sent": len(sent),
            "busiest_day": busiest_day,
            "top_senders": top_senders,
            "unread_count": unread_count,
            "days_analyzed": 7,
        }

        narrative = ai.generate_digest_narrative(stats_data)
        return jsonify({**stats_data, "narrative": narrative})
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error"}), 500


# -- Domains --

@app.route("/api/domains")
@require_auth
def domains():
    try:
        config, gmail, ai = _get_clients()
        vip_domains = load_vip_domains(config)
        return jsonify({
            "count": len(vip_domains),
            "domains": vip_domains,
        })
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error"}), 500


# -- VIP Contacts List --

@app.route("/api/vip/contacts")
@require_auth
def vip_contacts():
    try:
        config, gmail, ai = _get_clients()
        vips = load_vips(config)
        return jsonify({
            "count": len(vips),
            "contacts": vips,
        })
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error"}), 500


# -- VIP Check --

@app.route("/api/vip/check", methods=["POST"])
@require_auth
def vip_check():
    # CSRF check
    csrf_err = _check_csrf()
    if csrf_err:
        return csrf_err
    try:
        config, gmail, ai = _get_clients()
        data = request.get_json(force=True)
        email_address = data.get("email", "")
        if not email_address:
            return jsonify({"error": "email field required"}), 400

        vip_domains = load_vip_domains(config)
        vips = load_vips(config)
        vip_emails = [v["email"] for v in vips]

        is_vip = (
            email_address.lower() in vip_emails
            or is_vip_domain(email_address, vip_domains)
        )

        return jsonify({"email": email_address, "is_vip": is_vip})
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error"}), 500


# -- Agent Framework (lazy-init) --

_agent_registry = None
_agent_db = None
_agent_scheduler = None
_agent_learning = None


def _get_agents():
    """Lazy-init the agent framework on first access."""
    global _agent_registry, _agent_db, _agent_scheduler, _agent_learning

    if _agent_registry is not None:
        return _agent_registry, _agent_db, _agent_scheduler, _agent_learning

    config, gmail, ai = _get_clients()

    from hermes.agents.base import AgentConfig
    from hermes.agents.db import AgentDB
    from hermes.agents.registry import AgentRegistry
    from hermes.agents.learning import LearningManager
    from hermes.agents.scheduler import AgentScheduler
    from hermes.agents.director import DirectorAgent
    from hermes.agents.triage import TriageAgent
    from hermes.agents.vip_monitor import VIPMonitorAgent
    from hermes.agents.briefing import BriefingAgent
    from hermes.agents.cleanup import CleanupAgent
    from hermes.agents.inbox_zero import InboxZeroAgent
    from hermes.agents.digest import DigestAgent
    from hermes.agents.voice import VoiceAgent

    _agent_db = AgentDB(config.agent_db_path)
    _agent_registry = AgentRegistry()

    # Load configs and create agent instances
    configs_dir = config.agent_configs_path
    agent_classes = {
        "triage": TriageAgent,
        "vip_monitor": VIPMonitorAgent,
        "briefing": BriefingAgent,
        "cleanup": CleanupAgent,
        "inbox_zero": InboxZeroAgent,
        "digest": DigestAgent,
        "voice": VoiceAgent,
    }

    for agent_id, cls in agent_classes.items():
        config_path = configs_dir / f"{agent_id}.json"
        if config_path.exists():
            agent_cfg = AgentConfig.from_dict(json.loads(config_path.read_text()))
        else:
            agent_cfg = AgentConfig(agent_id=agent_id, display_name=cls.display_name)
        agent = cls(config=config, ai=ai, gmail=gmail, agent_config=agent_cfg)
        _agent_registry.register(agent)

    # Director (needs db + registry)
    director_config_path = configs_dir / "director.json"
    if director_config_path.exists():
        director_cfg = AgentConfig.from_dict(json.loads(director_config_path.read_text()))
    else:
        director_cfg = AgentConfig(agent_id="director", display_name="Director")
    director = DirectorAgent(
        config=config, ai=ai, gmail=gmail, agent_config=director_cfg,
        db=_agent_db, registry=_agent_registry,
    )
    _agent_registry.register(director)

    _agent_learning = LearningManager(_agent_db, _agent_registry, ai)
    _agent_scheduler = AgentScheduler(_agent_registry, _agent_db, _agent_learning)

    # Start scheduler if agents are enabled
    if config.agents_enabled:
        _agent_scheduler.start()

    return _agent_registry, _agent_db, _agent_scheduler, _agent_learning


# -- Agent API Endpoints --

@app.route("/api/agents")
@require_auth
def agents_list():
    """List all agents with status."""
    try:
        registry, db, scheduler, learning = _get_agents()
        agents = registry.get_status_all()
        return jsonify({"agents": agents})
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/agents/<agent_id>")
@require_auth
def agent_detail(agent_id):
    """Agent detail + config + recent history."""
    try:
        registry, db, scheduler, learning = _get_agents()
        agent = registry.get(agent_id)
        if not agent:
            return jsonify({"error": "Agent not found"}), 404
        status = agent.get_status()
        status["config"] = agent.agent_config.to_dict()
        status["recent_executions"] = db.get_executions(agent_id, limit=10)
        status["audit_log"] = db.get_audit_log(agent_id, limit=10)
        return jsonify(status)
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/agents/<agent_id>/trigger", methods=["POST"])
@require_auth
def agent_trigger(agent_id):
    """Manual agent execution."""
    csrf_err = _check_csrf()
    if csrf_err:
        return csrf_err
    try:
        registry, db, scheduler, learning = _get_agents()
        agent = registry.get(agent_id)
        if not agent:
            return jsonify({"error": "Agent not found"}), 404
        result = scheduler.trigger_agent(agent_id)
        return jsonify({"result": result})
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/agents/<agent_id>/enable", methods=["POST"])
@require_auth
def agent_enable(agent_id):
    """Enable or disable an agent."""
    csrf_err = _check_csrf()
    if csrf_err:
        return csrf_err
    try:
        registry, db, scheduler, learning = _get_agents()
        agent = registry.get(agent_id)
        if not agent:
            return jsonify({"error": "Agent not found"}), 404
        data = request.get_json(force=True) if request.is_json else {}
        enabled = data.get("enabled", not agent.agent_config.enabled)
        agent.agent_config.enabled = bool(enabled)
        agent.save_config()
        return jsonify({"agent_id": agent_id, "enabled": agent.agent_config.enabled})
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/agents/<agent_id>/schedule", methods=["POST"])
@require_auth
def agent_schedule(agent_id):
    """Update agent schedule."""
    csrf_err = _check_csrf()
    if csrf_err:
        return csrf_err
    try:
        registry, db, scheduler, learning = _get_agents()
        agent = registry.get(agent_id)
        if not agent:
            return jsonify({"error": "Agent not found"}), 404
        data = request.get_json(force=True)
        new_schedule = data.get("schedule", {})
        if not new_schedule:
            return jsonify({"error": "schedule field required"}), 400

        from hermes.agents.guardrails import Guardrails
        ok, reason = Guardrails.validate_config_change(agent_id, "schedule", None, new_schedule)
        if not ok:
            return jsonify({"error": reason}), 400

        scheduler.reschedule_agent(agent_id, new_schedule)
        return jsonify({"agent_id": agent_id, "schedule": new_schedule})
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/agents/<agent_id>/feedback", methods=["POST"])
@require_auth
def agent_feedback(agent_id):
    """Submit user feedback for an agent execution."""
    csrf_err = _check_csrf()
    if csrf_err:
        return csrf_err
    try:
        registry, db, scheduler, learning = _get_agents()
        data = request.get_json(force=True)
        feedback_type = data.get("type", "")
        if feedback_type not in ("thumbs_up", "thumbs_down", "correction"):
            return jsonify({"error": "type must be thumbs_up, thumbs_down, or correction"}), 400
        execution_id = data.get("execution_id")
        feedback_data = data.get("data", {})
        learning.record_feedback(agent_id, execution_id, feedback_type, feedback_data)
        return jsonify({"recorded": True})
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/agents/logs")
@require_auth
def agent_logs():
    """Execution log (filterable by agent_id query param)."""
    try:
        registry, db, scheduler, learning = _get_agents()
        agent_id = request.args.get("agent_id")
        limit = request.args.get("limit", 50, type=int)
        limit = max(1, min(limit, 200))
        logs = db.get_executions(agent_id, limit=limit)
        return jsonify({"logs": logs})
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/agents/audit")
@require_auth
def agent_audit():
    """Config change audit trail."""
    try:
        registry, db, scheduler, learning = _get_agents()
        agent_id = request.args.get("agent_id")
        limit = request.args.get("limit", 50, type=int)
        limit = max(1, min(limit, 200))
        audit = db.get_audit_log(agent_id, limit=limit)
        return jsonify({"audit": audit})
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/agents/scheduler")
@require_auth
def agent_scheduler_status():
    """Scheduler status."""
    try:
        registry, db, scheduler, learning = _get_agents()
        return jsonify(scheduler.get_status())
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify({"error": "Internal server error"}), 500


# -- Helpers --

def _safe_parse_date(date_str: str):
    if not date_str:
        return None
    try:
        return parsedate_to_datetime(date_str)
    except (ValueError, TypeError):
        return None
