"""Click subcommands + interactive REPL."""

import functools
import sys

import click
from rich.prompt import Prompt

from hermes.ai import AIClient
from hermes.config import load_config
from hermes.display import console, print_banner, print_error, print_info, spinner
from hermes.gmail import GmailClient


def _setup():
    """Initialize config, Gmail client, and AI client."""
    config = load_config()

    try:
        gmail = GmailClient(config)
        # Trigger auth eagerly so errors surface immediately
        gmail.service  # noqa: B018
    except FileNotFoundError as e:
        # The first-run message is embedded in the exception
        console.print(str(e))
        sys.exit(1)
    except Exception as e:
        print_error(f"Gmail authentication failed: {e}")
        sys.exit(1)

    ai = AIClient(config)
    return config, gmail, ai


def _handle_errors(f):
    """Decorator to catch common API/network errors in subcommands."""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except KeyboardInterrupt:
            console.print("\n[cyan]Interrupted.[/cyan]")
            sys.exit(0)
        except Exception as e:
            err = str(e)
            if "HttpError 429" in err or "rate limit" in err.lower():
                print_error("Gmail API rate limit hit. Wait a moment and try again.")
            elif "HttpError" in err:
                print_error(f"Gmail API error: {e}")
            elif "authentication" in err.lower() or "credential" in err.lower():
                print_error(f"Authentication error: {e}")
            else:
                print_error(f"Unexpected error: {e}")
            sys.exit(1)
    return wrapper


@click.group()
def main():
    """HERMES — Email Automation System."""
    pass


@main.command()
@click.option("--hours", default=12, help="Hours to look back (default: 12)")
@_handle_errors
def briefing(hours):
    """Get a morning briefing of recent emails."""
    print_banner()
    config, gmail, ai = _setup()
    from hermes.features import morning_briefing
    morning_briefing(gmail, ai, config, hours_back=hours)


@main.command()
@_handle_errors
def priority():
    """Scan unread emails by priority."""
    print_banner()
    config, gmail, ai = _setup()
    from hermes.features import priority_scan
    priority_scan(gmail, ai, config)


@main.command()
@click.option("--refresh", is_flag=True, help="Force refresh VIP list from sent mail")
@click.option("--add", "add_email", help="Manually add a VIP email address")
@click.option("--remove", "remove_email", help="Remove a VIP email address")
@click.option("--add-domain", "add_domain", help="Add a VIP domain (e.g., netflix.com)")
@click.option("--remove-domain", "remove_domain", help="Remove a VIP domain")
@click.option("--list-domains", is_flag=True, help="List all VIP domains")
@_handle_errors
def vip(refresh, add_email, remove_email, add_domain, remove_domain, list_domains):
    """Check VIP contact alerts and manage VIP domains."""
    print_banner()
    config, gmail, ai = _setup()
    from hermes.features import vip_add, vip_alert, vip_remove, vip_add_domain, vip_remove_domain
    from hermes.vip import load_vip_domains
    from hermes.display import print_vip_domains

    if add_email:
        vip_add(add_email, config)
        return
    if remove_email:
        vip_remove(remove_email, config)
        return
    if add_domain:
        # Parse domain — accept "netflix.com" or "Netflix:netflix.com" or "netflix.com:Netflix:Streaming"
        parts = add_domain.split(":")
        if len(parts) == 3:
            domain, company, category = parts
        elif len(parts) == 2:
            company, domain = parts
            category = "Entertainment"
        else:
            domain = parts[0]
            company = domain.split(".")[0].title()
            category = "Entertainment"
        vip_add_domain(domain.strip(), company.strip(), category.strip(), config)
        return
    if remove_domain:
        vip_remove_domain(remove_domain, config)
        return
    if list_domains:
        domains = load_vip_domains(config)
        print_vip_domains(domains)
        return
    vip_alert(gmail, ai, config, refresh=refresh)


@main.command()
@_handle_errors
def cleanup():
    """Clean up newsletters and promotions."""
    print_banner()
    config, gmail, ai = _setup()
    from hermes.features import newsletter_cleanup
    newsletter_cleanup(gmail, ai, config)


@main.command("inbox-zero")
@click.option("--batch", default=10, help="Emails per batch (default: 10)")
@_handle_errors
def inbox_zero_cmd(batch):
    """Process inbox toward inbox zero."""
    print_banner()
    config, gmail, ai = _setup()
    from hermes.features import inbox_zero
    inbox_zero(gmail, ai, config, batch_size=batch)


@main.command()
@_handle_errors
def digest():
    """Generate a weekly email digest."""
    print_banner()
    config, gmail, ai = _setup()
    from hermes.features import weekly_digest
    weekly_digest(gmail, ai, config)


@main.command()
@_handle_errors
def chat():
    """Interactive chat mode — talk to HERMES in natural language."""
    print_banner()
    config, gmail, ai = _setup()

    from hermes.features import (
        morning_briefing,
        newsletter_cleanup,
        priority_scan,
        search_emails,
        vip_alert,
        inbox_zero,
        weekly_digest,
    )

    console.print(
        "[bold cyan]Chat mode[/bold cyan] — Ask me anything about your email. "
        'Type [bold]quit[/bold] or [bold]exit[/bold] to leave.\n'
    )

    conversation = []

    # Tool dispatch mapping
    tool_dispatch = {
        "morning_briefing": lambda args: morning_briefing(
            gmail, ai, config, hours_back=args.get("hours_back", 12)
        ),
        "priority_scan": lambda args: priority_scan(gmail, ai, config),
        "vip_alert": lambda args: vip_alert(gmail, ai, config),
        "newsletter_cleanup": lambda args: newsletter_cleanup(gmail, ai, config),
        "inbox_zero": lambda args: inbox_zero(
            gmail, ai, config, batch_size=args.get("batch_size", 10)
        ),
        "weekly_digest": lambda args: weekly_digest(gmail, ai, config),
        "search_emails": lambda args: search_emails(gmail, args.get("query", "")),
    }

    while True:
        try:
            user_input = Prompt.ask("[bold green]You[/bold green]")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[cyan]Goodbye![/cyan]")
            break

        if user_input.strip().lower() in ("quit", "exit", "q"):
            console.print("[cyan]Goodbye![/cyan]")
            break

        if not user_input.strip():
            continue

        conversation.append({"role": "user", "content": user_input})

        # Trim conversation history
        if len(conversation) > config.repl_history_limit:
            conversation = conversation[-config.repl_history_limit:]

        try:
            response = ai.chat(conversation)

            # Handle tool use loop
            while response.stop_reason == "tool_use":
                # Collect all tool calls
                tool_results = []
                assistant_content = response.content

                for block in assistant_content:
                    if block.type == "tool_use":
                        tool_name = block.name
                        tool_input = block.input
                        tool_id = block.id

                        console.print(f"\n[dim]Running {tool_name}...[/dim]")

                        dispatch = tool_dispatch.get(tool_name)
                        if dispatch:
                            try:
                                result_text = dispatch(tool_input)
                            except Exception as e:
                                result_text = f"Error running {tool_name}: {e}"
                        else:
                            result_text = f"Unknown tool: {tool_name}"

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "content": result_text or "Done.",
                        })

                # Add assistant message and tool results to conversation
                conversation.append({"role": "assistant", "content": assistant_content})
                conversation.append({"role": "user", "content": tool_results})

                # Continue the conversation
                response = ai.chat(conversation)

            # Display text response
            text_parts = [
                block.text for block in response.content if hasattr(block, "text")
            ]
            if text_parts:
                reply = "\n".join(text_parts)
                console.print(f"\n[bold cyan]HERMES:[/bold cyan] {reply}\n")
                conversation.append({"role": "assistant", "content": reply})

        except Exception as e:
            print_error(f"Chat error: {e}")
            # Remove the failed user message
            if conversation and conversation[-1]["role"] == "user":
                conversation.pop()


@main.command()
@click.option("--port", default=5055, help="Port to run the API server on (default: 5055)")
@click.option("--host", default="127.0.0.1", help="Host to bind to (default: 127.0.0.1)")
def serve(port, host):
    """Start the HERMES REST API server (for n8n automation)."""
    from hermes.api import app
    console.print(f"[bold cyan]HERMES API[/bold cyan] starting on http://{host}:{port}")
    app.run(host=host, port=port, debug=False)
