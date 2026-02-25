#!/bin/bash
# mem-agent Claude Code hook — sends post-tool-use summaries to the daemon.
# This script is invoked by Claude Code's postToolUse hook.
# It reads stdin (the tool use summary) and POSTs it to the daemon.

DAEMON_URL="http://127.0.0.1:8330/ingest/claudecode"
SUMMARY=$(cat)
if [ -n "$SUMMARY" ]; then
    curl -s -X POST "$DAEMON_URL" -H "Content-Type: application/json" \
        -d "{\"text\": $(echo "$SUMMARY" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')}" \
        > /dev/null 2>&1 || true
fi
