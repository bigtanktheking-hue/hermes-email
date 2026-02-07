#!/bin/bash
# HERMES + n8n launcher
# Usage: ./start.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Starting HERMES API on port 5055 ==="
./venv/bin/hermes serve --port 5055 &
HERMES_PID=$!

echo "=== Starting n8n on port 5678 (Node 22) ==="
PATH="/opt/homebrew/opt/node@22/bin:$PATH" n8n start &
N8N_PID=$!

echo ""
echo "HERMES API: http://127.0.0.1:5055/api/health"
echo "n8n UI:     http://127.0.0.1:5678"
echo ""
echo "Press Ctrl+C to stop both services."

trap "echo 'Shutting down...'; kill $HERMES_PID $N8N_PID 2>/dev/null; exit 0" INT TERM

wait
