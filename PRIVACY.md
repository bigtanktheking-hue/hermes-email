# Privacy Policy

**MailTank — AI Email Command Center**
Last updated: February 2026

## What Data MailTank Accesses

MailTank accesses your Gmail inbox via the Gmail API using OAuth 2.0 authorization. Specifically:

- **Email metadata**: Subject, sender, date, labels
- **Email body content**: Plain text body for AI analysis and draft replies
- **Sent mail history**: Used to auto-detect VIP contacts based on your communication patterns

## How Data Is Processed

- **AI Analysis**: Email content is sent to your configured AI backend (Ollama locally or Groq cloud) for classification, summarization, and draft reply generation
- **Local Processing**: When using Ollama, all AI processing happens on your local machine. No email data leaves your network
- **Cloud Processing**: When using Groq, email content is sent to Groq's API servers for processing. Groq's privacy policy applies to data processed on their servers

## What Data Is Stored

- **VIP contact list**: Email addresses and scores stored locally in `hermes_data.json`
- **VIP domains**: Domain list stored locally in `vip_domains.json`
- **OAuth tokens**: Gmail API access tokens stored locally in `token.json`
- **No email content is permanently stored** by MailTank

## Data Sharing

MailTank does **not**:
- Sell or share your email data with third parties
- Store email content permanently
- Track usage analytics
- Use your data for advertising

## Your Control

- You can revoke Gmail access at any time via [Google Account Permissions](https://myaccount.google.com/permissions)
- Delete local data files (`hermes_data.json`, `vip_domains.json`, `token.json`) to remove all stored data
- Switch to Ollama (local AI) to keep all processing on your machine

## Security

- OAuth 2.0 for Gmail authentication (no password storage)
- Timing-safe password and API key comparison
- Rate limiting on login attempts
- CSRF protection on all state-changing operations
- Session timeout after 2 hours of inactivity

## Contact

For privacy concerns, open an issue on the project repository.
