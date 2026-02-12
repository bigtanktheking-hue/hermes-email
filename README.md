# MailTank — AI Email Command Center

AI-powered email management with Gmail integration. MailTank helps you triage, prioritize, and respond to emails using local (Ollama) or cloud (Groq) AI.

## Features

- **Morning Briefing** — Summarize recent emails with action items
- **Priority Scan** — Classify unread emails by urgency (high/medium/low)
- **VIP Alerts** — Track emails from important contacts and domains
- **Newsletter Cleanup** — Auto-archive or trash promotional emails
- **Inbox Zero** — Batch-process your inbox with AI classification
- **Weekly Digest** — Email stats and narrative summary
- **AI Chat** — Natural language interface to manage your inbox
- **Draft Replies** — AI-generated reply drafts matching sender tone
- **Autonomous Agents** — 8 self-managing agents with scheduling, learning, and self-modification
- **PWA Web UI** — Mobile-first interface with offline support and voice input

## Quick Start

### Prerequisites

- Python 3.9+
- Gmail API credentials ([setup guide](https://console.cloud.google.com/))
- Ollama (local AI) or Groq API key (cloud AI)

### Installation

```bash
git clone <repo-url> && cd hermes
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

### Gmail Setup

1. Create a project at [Google Cloud Console](https://console.cloud.google.com/)
2. Enable the Gmail API
3. Create OAuth 2.0 credentials (Desktop app)
4. Download as `credentials.json` in the project root
5. Run `hermes briefing` — a browser window opens for Gmail consent

### Configuration

Create a `.env` file:

```env
# AI Backend (ollama or groq)
AI_BACKEND=ollama
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=mistral

# Or use Groq cloud
# AI_BACKEND=groq
# GROQ_API_KEY=your-key-here

# Web UI password (required in production)
HERMES_WEB_PASSWORD=your-password

# API key for programmatic access
HERMES_API_KEY=your-api-key
```

### Usage

**CLI:**
```bash
hermes briefing          # Morning briefing
hermes priority          # Priority scan
hermes vip               # VIP alerts
hermes cleanup           # Newsletter cleanup
hermes inbox-zero        # Batch inbox processing
hermes digest            # Weekly digest
hermes chat              # Interactive AI chat
hermes agents status     # Show agent status
hermes agents run <id>   # Trigger an agent manually
hermes serve             # Start web UI + API
```

The `mailtank` command is also available as an alias for `hermes`.

**Web UI:**
```bash
hermes serve --port 5055
# Open http://localhost:5055
```

**API:**
```bash
curl -H "X-API-Key: your-key" http://localhost:5055/api/stats
```

## Agents

MailTank includes 8 autonomous agents that can run on schedules and learn from feedback:

| Agent | Description |
|-------|-------------|
| Triage | Classify incoming emails by priority |
| VIP Monitor | Watch for emails from VIP contacts |
| Briefing | Generate morning briefing summaries |
| Cleanup | Archive/delete newsletters and promotions |
| Inbox Zero | Batch-process inbox toward zero |
| Digest | Generate weekly email statistics |
| Voice | Process voice commands |
| Director | Oversee other agents, propose config changes |

Agents support self-modification — they can propose config changes via the AI, validated by hard-coded guardrails that prevent weakening constraints.

## Deployment (Render)

1. Push to GitHub
2. Connect to [Render](https://render.com) — the `render.yaml` blueprint auto-configures the service
3. Set environment variables in Render dashboard:
   - `HERMES_WEB_PASSWORD` — Web login password
   - `SECRET_KEY` — Session encryption key (auto-generated)
   - `HERMES_API_KEY` — API key for n8n/programmatic access
   - `AI_BACKEND` — `groq`
   - `GROQ_API_KEY` — Your Groq API key
   - `GMAIL_CREDENTIALS_JSON` — Contents of credentials.json
   - `GMAIL_TOKEN_JSON` — Contents of token.json
4. Custom domain: `tankmail.ai` (configured in `render.yaml`)

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/health` | GET | Health check |
| `/api/health/ai` | GET | AI backend health |
| `/api/stats` | GET | Dashboard stats |
| `/api/emails` | GET | Paginated email list |
| `/api/email/<id>` | GET | Email detail |
| `/api/briefing` | GET | Morning briefing |
| `/api/priority` | GET | Priority scan |
| `/api/vip` | GET | VIP alerts |
| `/api/cleanup` | POST | Newsletter cleanup |
| `/api/inbox-zero` | POST | Inbox zero batch |
| `/api/digest` | GET | Weekly digest |
| `/api/chat` | POST | AI chat |
| `/api/send-reply` | POST | Send reply |
| `/api/draft-reply` | POST | Generate draft reply |
| `/api/agents` | GET | List all agents |
| `/api/agents/<id>` | GET | Agent detail |
| `/api/agents/<id>/trigger` | POST | Trigger agent |
| `/api/agents/<id>/enable` | POST | Enable/disable agent |
| `/api/agents/<id>/feedback` | POST | Submit feedback |
| `/api/agents/logs` | GET | Agent execution logs |
| `/api/agents/audit` | GET | Config change audit trail |
| `/api/agents/scheduler` | GET | Scheduler status |

## Security

- OAuth 2.0 Gmail authentication
- Timing-safe password/API key comparison
- CSRF protection on all POST endpoints
- Rate limiting on login (5 attempts / 15 min)
- Security headers (CSP, X-Frame-Options, etc.)
- Session timeout (2 hours)
- No stack traces exposed to clients
- Agent guardrails prevent self-weakening modifications

## License

MIT License. See [LICENSE](LICENSE).

## Privacy

See [PRIVACY.md](PRIVACY.md) for data handling details.
