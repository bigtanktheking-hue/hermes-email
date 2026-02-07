"""Rich console output + confirmation flow."""
from __future__ import annotations

from contextlib import contextmanager

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.prompt import Prompt

console = Console()


@contextmanager
def spinner(message: str = "Working..."):
    """Context manager that shows a spinner while work is in progress."""
    with console.status(f"[bold cyan]{message}"):
        yield


def print_banner():
    """Print the HERMES welcome banner."""
    console.print(
        Panel(
            "[bold cyan]HERMES[/bold cyan] — Email Automation System",
            border_style="cyan",
        )
    )


def print_briefing(summary: dict, email_count: int):
    """Display a morning briefing summary."""
    console.print()
    console.print(
        Panel(
            f"[bold]{summary.get('summary', 'No summary available.')}[/bold]\n\n"
            f"[dim]{email_count} emails analyzed[/dim]",
            title="[bold cyan]Morning Briefing[/bold cyan]",
            border_style="cyan",
        )
    )

    action_items = summary.get("action_items", [])
    if action_items:
        console.print("\n[bold red]Action Items:[/bold red]")
        for item in action_items:
            console.print(f"  [red]>[/red] {item}")

    fyi = summary.get("fyi", [])
    if fyi:
        console.print("\n[bold yellow]FYI:[/bold yellow]")
        for item in fyi:
            console.print(f"  [yellow]-[/yellow] {item}")

    highlights = summary.get("highlights", [])
    if highlights:
        console.print("\n[bold green]Highlights:[/bold green]")
        for item in highlights:
            console.print(f"  [green]*[/green] {item}")

    console.print()


def print_priority_table(emails: list[dict], classifications: list[dict]):
    """Display a priority-sorted table of emails."""
    # Build lookup
    class_map = {c["id"]: c for c in classifications}

    # Sort by priority
    priority_order = {"high": 0, "medium": 1, "low": 2}
    sorted_emails = sorted(
        emails,
        key=lambda e: priority_order.get(
            class_map.get(e["id"], {}).get("priority", "low"), 2
        ),
    )

    table = Table(title="Priority Scan", border_style="cyan")
    table.add_column("Priority", style="bold", width=8)
    table.add_column("From", width=25, no_wrap=True)
    table.add_column("Subject", width=40)
    table.add_column("Reason", width=30)

    priority_colors = {"high": "red", "medium": "yellow", "low": "dim"}

    for e in sorted_emails:
        c = class_map.get(e["id"], {"priority": "low", "reason": ""})
        color = priority_colors.get(c["priority"], "dim")
        table.add_row(
            Text(c["priority"].upper(), style=color),
            _truncate(e.get("from", ""), 25),
            _truncate(e.get("subject", ""), 40),
            _truncate(c.get("reason", ""), 30),
        )

    console.print()
    console.print(table)
    console.print()


def print_vip_emails(emails: list[dict]):
    """Display VIP alert emails."""
    if not emails:
        console.print("\n[green]No unread VIP emails.[/green]\n")
        return

    console.print(
        Panel(
            f"[bold]{len(emails)} unread email(s) from VIP contacts[/bold]",
            title="[bold cyan]VIP Alert[/bold cyan]",
            border_style="cyan",
        )
    )

    for e in emails:
        console.print(
            f"  [bold]{e.get('from', '')}[/bold]: {e.get('subject', '')}"
        )
    console.print()


def print_vip_list(vips: list[dict]):
    """Display the current VIP contact list."""
    if not vips:
        console.print("\n[yellow]No VIP contacts detected yet. Run 'hermes vip --refresh' to scan.[/yellow]\n")
        return

    table = Table(title="VIP Contacts", border_style="cyan")
    table.add_column("#", width=4)
    table.add_column("Contact", width=35)
    table.add_column("Score", width=8, justify="right")

    for i, vip in enumerate(vips, 1):
        table.add_row(str(i), vip.get("email", ""), f"{vip.get('score', 0):.1f}")

    console.print()
    console.print(table)
    console.print()



def print_vip_domains(domains: list[dict]):
    """Display the VIP domain list."""
    if not domains:
        console.print("\n[yellow]No VIP domains configured. Use 'hermes vip --add-domain' to add.[/yellow]\n")
        return

    table = Table(title="VIP Domains", border_style="cyan")
    table.add_column("#", width=4)
    table.add_column("Domain", width=25)
    table.add_column("Company", width=25)
    table.add_column("Category", width=20)

    for i, d in enumerate(domains, 1):
        table.add_row(
            str(i),
            f"@{d.get('domain', '')}",
            d.get("company", ""),
            d.get("category", ""),
        )

    console.print()
    console.print(table)
    console.print()


def print_cleanup_plan(classifications: list[dict], emails: list[dict]):
    """Display the newsletter cleanup plan."""
    email_map = {e["id"]: e for e in emails}

    table = Table(title="Newsletter Cleanup Plan", border_style="cyan")
    table.add_column("Action", style="bold", width=8)
    table.add_column("From", width=25, no_wrap=True)
    table.add_column("Subject", width=40)
    table.add_column("Reason", width=30)

    action_colors = {"archive": "yellow", "delete": "red", "keep": "green"}

    for c in classifications:
        e = email_map.get(c["id"], {})
        color = action_colors.get(c["action"], "dim")
        table.add_row(
            Text(c["action"].upper(), style=color),
            _truncate(e.get("from", ""), 25),
            _truncate(e.get("subject", ""), 40),
            _truncate(c.get("reason", ""), 30),
        )

    console.print()
    console.print(table)
    console.print()


def print_inbox_zero_batch(classifications: list[dict], emails: list[dict]):
    """Display an inbox-zero batch classification."""
    email_map = {e["id"]: e for e in emails}

    table = Table(title="Inbox Zero — Batch Classification", border_style="cyan")
    table.add_column("Action", style="bold", width=15)
    table.add_column("From", width=25, no_wrap=True)
    table.add_column("Subject", width=40)
    table.add_column("Reason", width=30)

    action_colors = {"action_needed": "red", "read_archive": "yellow", "junk": "dim"}

    for c in classifications:
        e = email_map.get(c["id"], {})
        color = action_colors.get(c["action"], "dim")
        table.add_row(
            Text(c["action"].upper().replace("_", " "), style=color),
            _truncate(e.get("from", ""), 25),
            _truncate(e.get("subject", ""), 40),
            _truncate(c.get("reason", ""), 30),
        )

    console.print()
    console.print(table)
    console.print()


def print_digest(stats: dict, narrative: str):
    """Display weekly digest with stats and narrative."""
    console.print()
    console.print(
        Panel(narrative, title="[bold cyan]Weekly Digest[/bold cyan]", border_style="cyan")
    )

    table = Table(border_style="cyan")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    table.add_row("Emails received", str(stats.get("received", 0)))
    table.add_row("Emails sent", str(stats.get("sent", 0)))
    table.add_row("Busiest day", stats.get("busiest_day", "N/A"))
    table.add_row("Unread now", str(stats.get("unread_count", 0)))

    top_senders = stats.get("top_senders", [])
    if top_senders:
        table.add_row("Top senders", ", ".join(top_senders[:5]))

    console.print(table)
    console.print()


def print_search_results(emails: list[dict]):
    """Display search results."""
    if not emails:
        console.print("\n[yellow]No emails found.[/yellow]\n")
        return

    table = Table(title=f"Search Results ({len(emails)} found)", border_style="cyan")
    table.add_column("From", width=25, no_wrap=True)
    table.add_column("Subject", width=45)
    table.add_column("Date", width=20)

    for e in emails:
        table.add_row(
            _truncate(e.get("from", ""), 25),
            _truncate(e.get("subject", ""), 45),
            _truncate(e.get("date", ""), 20),
        )

    console.print()
    console.print(table)
    console.print()


# ── Confirmation flow ──────────────────────────────────────────

def confirm_action(action_description: str, items: list[dict], item_formatter=None) -> str:
    """Single chokepoint for all destructive operations.

    Returns: 'yes', 'no', or 'review' (review each individually).
    """
    count = len(items)
    console.print(
        f"\n[bold yellow]Confirm:[/bold yellow] {action_description} "
        f"({count} email{'s' if count != 1 else ''})"
    )

    choice = Prompt.ask(
        "[Y]es / [N]o / [R]eview each",
        choices=["y", "n", "r"],
        default="n",
    )

    if choice == "r" and item_formatter:
        approved = []
        for item in items:
            console.print(f"\n  {item_formatter(item)}")
            sub_choice = Prompt.ask("  Apply? [y/n]", choices=["y", "n"], default="n")
            if sub_choice == "y":
                approved.append(item)
        items.clear()
        items.extend(approved)
        return "yes" if approved else "no"

    return {"y": "yes", "n": "no", "r": "review"}.get(choice, "no")


def print_error(message: str):
    """Display an error message."""
    console.print(f"\n[bold red]Error:[/bold red] {message}\n")


def print_success(message: str):
    """Display a success message."""
    console.print(f"\n[bold green]{message}[/bold green]\n")


def print_info(message: str):
    """Display an info message."""
    console.print(f"\n[cyan]{message}[/cyan]\n")


# ── Helpers ────────────────────────────────────────────────────

def _truncate(text: str, max_len: int) -> str:
    """Truncate text with ellipsis."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "\u2026"
