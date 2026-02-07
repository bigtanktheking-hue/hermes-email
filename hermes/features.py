"""All 6 HERMES feature functions.

Each function:
  - Takes gmail, ai, config as params
  - Handles display when called from CLI
  - Returns a plain text summary string (for REPL mode)
"""

from collections import Counter
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

from hermes.ai import AIClient
from hermes.config import Config
from hermes.display import (
    confirm_action,
    console,
    print_briefing,
    print_cleanup_plan,
    print_digest,
    print_error,
    print_inbox_zero_batch,
    print_info,
    print_priority_table,
    print_search_results,
    print_success,
    print_vip_emails,
    print_vip_domains,
    print_vip_list,
    spinner,
)
from hermes.gmail import GmailClient
from hermes.vip import (
    add_vip,
    add_vip_domain,
    detect_vips,
    get_vip_domain_emails,
    get_vip_emails,
    load_vip_domains,
    load_vips,
    needs_refresh,
    remove_vip,
    remove_vip_domain,
    save_vips,
)


# ── 1. Morning Briefing ───────────────────────────────────────

def morning_briefing(gmail: GmailClient, ai: AIClient, config: Config, hours_back: int = 12) -> str:
    """Fetch recent emails and generate a summary briefing."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    epoch = int(cutoff.timestamp())
    query = f"after:{epoch} in:inbox"

    with spinner("Fetching recent emails..."):
        emails = gmail.get_messages(query=query, max_results=100)

    if not emails:
        print_info(f"No emails in the last {hours_back} hours.")
        return f"No emails received in the last {hours_back} hours."

    with spinner(f"Analyzing {len(emails)} emails..."):
        summary = ai.summarize_emails(emails)

    print_briefing(summary, len(emails))

    # Build text summary for REPL
    lines = [summary.get("summary", "")]
    for item in summary.get("action_items", []):
        lines.append(f"  ACTION: {item}")
    for item in summary.get("fyi", []):
        lines.append(f"  FYI: {item}")
    return "\n".join(lines)


# ── 2. Priority Scan ──────────────────────────────────────────

def priority_scan(gmail: GmailClient, ai: AIClient, config: Config) -> str:
    """Scan unread emails and classify by priority."""
    with spinner("Fetching unread emails..."):
        emails = gmail.get_messages(query="is:unread in:inbox", max_results=50)

    if not emails:
        print_info("No unread emails!")
        return "No unread emails in your inbox."

    with spinner(f"Classifying {len(emails)} emails..."):
        classifications = ai.classify_priority(emails)

    print_priority_table(emails, classifications)

    # Build text summary
    high = [c for c in classifications if c.get("priority") == "high"]
    med = [c for c in classifications if c.get("priority") == "medium"]
    low = [c for c in classifications if c.get("priority") == "low"]
    lines = [
        f"Scanned {len(emails)} unread emails:",
        f"  {len(high)} high priority",
        f"  {len(med)} medium priority",
        f"  {len(low)} low priority",
    ]
    email_map = {e["id"]: e for e in emails}
    for c in high:
        e = email_map.get(c["id"], {})
        lines.append(f"  HIGH: {e.get('from', '')} — {e.get('subject', '')} ({c.get('reason', '')})")
    return "\n".join(lines)


# ── 3. VIP Alert ──────────────────────────────────────────────

def vip_alert(gmail: GmailClient, ai: AIClient, config: Config, refresh: bool = False) -> str:
    """Check for unread emails from VIP contacts and VIP domains."""
    # Refresh individual VIP list if needed
    if refresh or needs_refresh(config):
        with spinner("Analyzing sent mail for VIP contacts..."):
            sent = gmail.get_sent_messages(max_results=200)
            vips = detect_vips(sent, config)
            save_vips(vips, config)
        print_success(f"VIP list updated: {len(vips)} contacts detected.")
    else:
        vips = load_vips(config)

    # Load VIP domains
    vip_domains = load_vip_domains(config)

    if not vips and not vip_domains:
        print_info("No VIP contacts or domains configured. Use --add or --add-domain to set up.")
        return "No VIP contacts or domains configured."

    if vips:
        print_vip_list(vips)
    if vip_domains:
        print_vip_domains(vip_domains)

    # Build combined query
    query_parts = []

    # Individual VIP email addresses
    vip_addrs = get_vip_emails(vips)
    for addr in vip_addrs:
        query_parts.append(f"from:{addr}")

    # VIP domains
    domain_strs = get_vip_domain_emails(vip_domains)
    for domain in domain_strs:
        query_parts.append(f"from:@{domain}")

    if not query_parts:
        return "No VIP contacts or domains to check."

    query = f"is:unread in:inbox ({' OR '.join(query_parts)})"

    with spinner("Checking for VIP emails..."):
        emails = gmail.get_messages(query=query, max_results=50)

    print_vip_emails(emails)

    if not emails:
        return "No unread emails from VIP contacts or domains."
    lines = [f"{len(emails)} unread email(s) from VIP contacts/domains:"]
    for e in emails:
        lines.append(f"  {e.get('from', '')} — {e.get('subject', '')}")
    return "\n".join(lines)


def vip_add(email: str, config: Config):
    """Add a VIP contact manually."""
    add_vip(email, config)
    print_success(f"Added {email} to VIP list.")


def vip_remove(email: str, config: Config):
    """Remove a VIP contact."""
    remove_vip(email, config)
    print_success(f"Removed {email} from VIP list.")


def vip_add_domain(domain: str, company: str, category: str, config: Config):
    """Add a VIP domain."""
    add_vip_domain(domain, company, category, config)
    print_success(f"Added domain @{domain} ({company}) to VIP list.")


def vip_remove_domain(domain: str, config: Config):
    """Remove a VIP domain."""
    remove_vip_domain(domain, config)
    print_success(f"Removed domain @{domain} from VIP list.")


# ── 4. Newsletter Cleanup ────────────────────────────────────

def newsletter_cleanup(gmail: GmailClient, ai: AIClient, config: Config) -> str:
    """Scan promotions/updates and classify for cleanup."""
    with spinner("Fetching promotional and update emails..."):
        emails = gmail.get_messages(
            query="in:inbox category:promotions OR category:updates",
            max_results=50,
        )

    if not emails:
        print_info("No newsletters or promotions to clean up.")
        return "No newsletters or promotions found in inbox."

    with spinner(f"Classifying {len(emails)} emails..."):
        classifications = ai.classify_junk(emails)

    print_cleanup_plan(classifications, emails)

    # Separate by action
    to_archive = [c for c in classifications if c["action"] == "archive"]
    to_delete = [c for c in classifications if c["action"] == "delete"]
    to_keep = [c for c in classifications if c["action"] == "keep"]

    summary_parts = [
        f"Found {len(emails)} promotional/update emails:",
        f"  {len(to_archive)} to archive, {len(to_delete)} to delete, {len(to_keep)} to keep",
    ]

    email_map = {e["id"]: e for e in emails}

    def format_item(c):
        e = email_map.get(c["id"], {})
        return f"[{c['action'].upper()}] {e.get('from', '')} — {e.get('subject', '')} ({c.get('reason', '')})"

    # Archive
    if to_archive:
        archive_ids = [c["id"] for c in to_archive]
        archive_items = [{"id": c["id"], **email_map.get(c["id"], {}), "action": c["action"], "reason": c["reason"]} for c in to_archive]
        result = confirm_action(
            f"Archive {len(to_archive)} emails",
            archive_items,
            item_formatter=lambda x: f"{x.get('from', '')} — {x.get('subject', '')}",
        )
        if result == "yes":
            with spinner("Archiving..."):
                final_ids = [x["id"] for x in archive_items]
                gmail.archive_messages(final_ids)
            print_success(f"Archived {len(final_ids)} emails.")
            summary_parts.append(f"Archived {len(final_ids)} emails.")

    # Delete
    if to_delete:
        delete_items = [{"id": c["id"], **email_map.get(c["id"], {}), "action": c["action"], "reason": c["reason"]} for c in to_delete]
        result = confirm_action(
            f"Delete {len(to_delete)} emails",
            delete_items,
            item_formatter=lambda x: f"{x.get('from', '')} — {x.get('subject', '')}",
        )
        if result == "yes":
            with spinner("Deleting..."):
                final_ids = [x["id"] for x in delete_items]
                gmail.trash_messages(final_ids)
            print_success(f"Deleted {len(final_ids)} emails.")
            summary_parts.append(f"Deleted {len(final_ids)} emails.")

    return "\n".join(summary_parts)


# ── 5. Inbox Zero ────────────────────────────────────────────

def inbox_zero(gmail: GmailClient, ai: AIClient, config: Config, batch_size: int = 10) -> str:
    """Process inbox in batches toward inbox zero."""
    total_archived = 0
    total_trashed = 0
    total_kept = 0

    while True:
        with spinner("Fetching inbox emails..."):
            emails = gmail.get_messages(
                query="is:unread in:inbox", max_results=batch_size
            )

        if not emails:
            print_success("Inbox zero achieved!")
            break

        remaining = gmail.get_unread_count()
        print_info(f"Processing batch of {len(emails)} (approx. {remaining} unread remaining)")

        with spinner(f"Classifying {len(emails)} emails..."):
            classifications = ai.classify_inbox(emails)

        print_inbox_zero_batch(classifications, emails)

        email_map = {e["id"]: e for e in emails}

        # Separate by action
        action_needed = [c for c in classifications if c["action"] == "action_needed"]
        read_archive = [c for c in classifications if c["action"] == "read_archive"]
        junk = [c for c in classifications if c["action"] == "junk"]

        # Process read_archive
        if read_archive:
            archive_items = [{"id": c["id"], **email_map.get(c["id"], {})} for c in read_archive]
            result = confirm_action(
                f"Archive {len(read_archive)} read/FYI emails",
                archive_items,
                item_formatter=lambda x: f"{x.get('from', '')} — {x.get('subject', '')}",
            )
            if result == "yes":
                final_ids = [x["id"] for x in archive_items]
                gmail.archive_messages(final_ids)
                gmail.mark_read(final_ids)
                total_archived += len(final_ids)
                print_success(f"Archived {len(final_ids)} emails.")

        # Process junk
        if junk:
            junk_items = [{"id": c["id"], **email_map.get(c["id"], {})} for c in junk]
            result = confirm_action(
                f"Trash {len(junk)} junk emails",
                junk_items,
                item_formatter=lambda x: f"{x.get('from', '')} — {x.get('subject', '')}",
            )
            if result == "yes":
                final_ids = [x["id"] for x in junk_items]
                gmail.trash_messages(final_ids)
                total_trashed += len(final_ids)
                print_success(f"Trashed {len(final_ids)} emails.")

        total_kept += len(action_needed)
        if action_needed:
            console.print(f"\n[bold]Kept {len(action_needed)} emails that need your action.[/bold]")

        # Ask to continue
        from rich.prompt import Prompt
        cont = Prompt.ask("\nContinue processing?", choices=["y", "n"], default="y")
        if cont != "y":
            break

    summary = (
        f"Inbox zero session: archived {total_archived}, "
        f"trashed {total_trashed}, kept {total_kept} for action."
    )
    print_info(summary)
    return summary


# ── 6. Weekly Digest ──────────────────────────────────────────

def weekly_digest(gmail: GmailClient, ai: AIClient, config: Config) -> str:
    """Generate a weekly email digest with stats and narrative."""
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    epoch = int(week_ago.timestamp())

    with spinner("Gathering weekly stats..."):
        received = gmail.get_messages(query=f"after:{epoch} in:inbox", max_results=200, with_body=False)
        sent = gmail.get_messages(query=f"after:{epoch} in:sent", max_results=200, with_body=False)
        unread_count = gmail.get_unread_count()

    # Compute stats
    day_counter = Counter()
    sender_counter = Counter()

    for msg in received:
        date = _safe_parse_date(msg.get("date", ""))
        if date:
            day_counter[date.strftime("%A")] += 1
        sender = msg.get("from", "")
        # Extract just the name/email
        if "<" in sender:
            sender = sender.split("<")[0].strip().strip('"')
        sender_counter[sender] += 1

    busiest_day = day_counter.most_common(1)[0][0] if day_counter else "N/A"
    top_senders = [s for s, _ in sender_counter.most_common(5)]

    stats = {
        "received": len(received),
        "sent": len(sent),
        "busiest_day": busiest_day,
        "top_senders": top_senders,
        "unread_count": unread_count,
        "days_analyzed": 7,
    }

    with spinner("Generating narrative summary..."):
        narrative = ai.generate_digest_narrative(stats)

    print_digest(stats, narrative)

    lines = [
        f"Weekly digest: {stats['received']} received, {stats['sent']} sent.",
        f"Busiest day: {busiest_day}. Unread: {unread_count}.",
        narrative,
    ]
    return "\n".join(lines)


# ── 7. Search (for REPL) ─────────────────────────────────────

def search_emails(gmail: GmailClient, query: str) -> str:
    """Search emails and display results."""
    with spinner(f"Searching: {query}"):
        emails = gmail.search(query, max_results=20)

    print_search_results(emails)

    if not emails:
        return "No emails found."
    lines = [f"Found {len(emails)} emails:"]
    for e in emails:
        lines.append(f"  {e.get('from', '')} — {e.get('subject', '')} ({e.get('date', '')})")
    return "\n".join(lines)


# ── Helpers ────────────────────────────────────────────────────

def _safe_parse_date(date_str: str):
    """Safely parse a date string."""
    if not date_str:
        return None
    try:
        return parsedate_to_datetime(date_str)
    except (ValueError, TypeError):
        return None
