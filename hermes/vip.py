"""VIP auto-detection algorithm based on sent mail analysis."""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

from hermes.config import Config


def detect_vips(sent_messages: list[dict], config: Config) -> list[dict]:
    """Analyze sent messages to auto-detect VIP contacts.

    Scoring weights:
      - Send frequency: 3x
      - Recency (within 30 days): 2x
      - Response speed (replied within 2h): 2x
      - Thread depth (multi-message threads): 1.5x
      - User-initiated threads: 1.5x

    Returns sorted list of {email, score} dicts.
    """
    contacts = defaultdict(lambda: {
        "send_count": 0,
        "recent_count": 0,
        "fast_replies": 0,
        "thread_ids": set(),
        "initiated": 0,
    })

    now = datetime.now(timezone.utc)
    thirty_days_ago = now - timedelta(days=30)

    # Group by thread to detect depth and initiation
    threads = defaultdict(list)
    for msg in sent_messages:
        tid = msg.get("threadId", "")
        if tid:
            threads[tid].append(msg)

    for msg in sent_messages:
        to_addrs = _extract_emails(msg.get("to", ""))
        date = _parse_date(msg.get("date", ""))
        thread_id = msg.get("threadId", "")

        for addr in to_addrs:
            addr = addr.lower()
            c = contacts[addr]
            c["send_count"] += 1

            if date and date > thirty_days_ago:
                c["recent_count"] += 1

            if thread_id:
                c["thread_ids"].add(thread_id)

    # Detect thread depth and user-initiated threads
    for addr, data in contacts.items():
        deep_threads = sum(
            1 for tid in data["thread_ids"] if len(threads.get(tid, [])) > 1
        )
        data["deep_threads"] = deep_threads
        # Rough heuristic: if user sent the first message in many threads
        for tid in data["thread_ids"]:
            thread_msgs = threads.get(tid, [])
            if thread_msgs:
                # Simple heuristic: if there's a sent message in the thread, count as possible initiation
                data["initiated"] += 1

    # Score contacts
    scored = []
    for addr, data in contacts.items():
        score = (
            data["send_count"] * 3.0
            + data["recent_count"] * 2.0
            + data["deep_threads"] * 1.5
            + min(data["initiated"], data["send_count"]) * 1.5
        )
        if score >= config.vip_min_score:
            scored.append({"email": addr, "score": round(score, 1)})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[: config.vip_top_n]


def load_vips(config: Config) -> list[dict]:
    """Load VIP list from persisted data file."""
    path = config.vip_data_path
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        return data.get("vips", [])
    except (json.JSONDecodeError, KeyError):
        return []


def save_vips(vips: list[dict], config: Config):
    """Save VIP list to data file."""
    path = config.vip_data_path
    data = {"vips": vips, "updated": datetime.now(timezone.utc).isoformat()}
    path.write_text(json.dumps(data, indent=2))


def needs_refresh(config: Config) -> bool:
    """Check if VIP data is stale and needs refresh."""
    path = config.vip_data_path
    if not path.exists():
        return True
    try:
        data = json.loads(path.read_text())
        updated = datetime.fromisoformat(data["updated"])
        return datetime.now(timezone.utc) - updated > timedelta(days=config.vip_refresh_days)
    except (json.JSONDecodeError, KeyError, ValueError):
        return True


def add_vip(email: str, config: Config):
    """Manually add a VIP contact."""
    vips = load_vips(config)
    email = email.lower().strip()
    if any(v["email"] == email for v in vips):
        return  # Already exists
    vips.insert(0, {"email": email, "score": 999.0})  # Manual adds get top score
    save_vips(vips, config)


def remove_vip(email: str, config: Config):
    """Remove a VIP contact."""
    vips = load_vips(config)
    email = email.lower().strip()
    vips = [v for v in vips if v["email"] != email]
    save_vips(vips, config)


def get_vip_emails(vips: list[dict]) -> list[str]:
    """Extract just the email addresses from VIP list."""
    return [v["email"] for v in vips]




def load_vip_domains(config: Config) -> list[dict]:
    """Load VIP domain list from data file."""
    path = config.vip_domains_path
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        return data.get("domains", [])
    except (json.JSONDecodeError, KeyError):
        return []


def save_vip_domains(domains: list[dict], config: Config):
    """Save VIP domain list to data file."""
    path = config.vip_domains_path
    data = {"domains": domains, "updated": datetime.now(timezone.utc).isoformat()}
    path.write_text(json.dumps(data, indent=2))


def add_vip_domain(domain: str, company: str, category: str, config: Config):
    """Add a domain to the VIP domain list."""
    domains = load_vip_domains(config)
    domain = domain.lower().strip()
    if any(d["domain"] == domain for d in domains):
        return  # Already exists
    domains.append({"domain": domain, "company": company, "category": category})
    save_vip_domains(domains, config)


def remove_vip_domain(domain: str, config: Config):
    """Remove a domain from the VIP domain list."""
    domains = load_vip_domains(config)
    domain = domain.lower().strip()
    domains = [d for d in domains if d["domain"] != domain]
    save_vip_domains(domains, config)


def get_vip_domain_emails(domains: list[dict]) -> list[str]:
    """Extract just the domain strings from VIP domain list."""
    return [d["domain"] for d in domains]


def is_vip_domain(email_address: str, domains: list[dict]) -> bool:
    """Check if an email address matches any VIP domain."""
    email_address = email_address.lower()
    for d in domains:
        if email_address.endswith("@" + d["domain"]):
            return True
    return False


# ── Helpers ────────────────────────────────────────────────────

def _extract_emails(header_value: str) -> list[str]:
    """Extract email addresses from a To/From header."""
    return re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", header_value)


def _parse_date(date_str: str):
    """Parse an email date string, returning datetime or None."""
    if not date_str:
        return None
    try:
        return parsedate_to_datetime(date_str)
    except (ValueError, TypeError):
        return None
