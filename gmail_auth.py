#!/usr/bin/env python3
"""One-time Gmail OAuth — handles the full flow manually."""
import sys
import subprocess
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, "/Users/bigtankmusic/hermes")

from hermes.config import load_config
from google_auth_oauthlib.flow import Flow

config = load_config()
PORT = 8080
AUTH_RESULT = {"code": None, "done": False}


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        code = query.get("code", [None])[0]
        if code:
            AUTH_RESULT["code"] = code
            AUTH_RESULT["done"] = True
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><body style='font-family:sans-serif;text-align:center;padding:60px'>"
                b"<h1>HERMES Gmail Connected!</h1>"
                b"<p>You can close this tab and return to your terminal.</p>"
                b"</body></html>"
            )
        else:
            # Not the auth callback (favicon, etc.) — ignore
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"waiting...")

    def log_message(self, fmt, *args):
        pass


# Create flow with explicit redirect
flow = Flow.from_client_secrets_file(
    str(config.credentials_path),
    scopes=config.gmail_scopes,
    redirect_uri=f"http://localhost:{PORT}/"
)
auth_url, state = flow.authorization_url(prompt="consent", access_type="offline")

# Start server
server = HTTPServer(("localhost", PORT), CallbackHandler)
server.timeout = 1  # Check every second

sys.stdout.write(f"Waiting for Google sign-in on port {PORT}...\n")
sys.stdout.flush()

# Open browser
subprocess.run(["open", auth_url])

# Serve until we get the auth code (up to 5 min)
deadline = time.time() + 300
while not AUTH_RESULT["done"] and time.time() < deadline:
    server.handle_request()

server.server_close()

if AUTH_RESULT["code"]:
    flow.fetch_token(code=AUTH_RESULT["code"])
    creds = flow.credentials
    config.token_path.write_text(creds.to_json())
    sys.stdout.write("GMAIL_AUTH_SUCCESS\n")
    sys.stdout.flush()
else:
    sys.stdout.write("AUTH_TIMEOUT\n")
    sys.stdout.flush()
    sys.exit(1)
