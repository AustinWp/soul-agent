#!/bin/bash
# mem-agent quick note — macOS shortcut-triggered note input
# Pops up an osascript dialog, POSTs to the daemon, and sends a notification.
#
# Usage: bash /path/to/quick_note.sh
# Bind to a global shortcut via Automator / Shortcuts / Karabiner.

MEM_AGENT_ENDPOINT="${MEM_AGENT_URL:-http://localhost:8330}"

# Show input dialog
note_text=$(osascript -e 'display dialog "Quick Note:" default answer "" buttons {"Cancel","Save"} default button "Save"' \
    -e 'text returned of result' 2>/dev/null)

# Exit if user cancelled or empty
if [ -z "$note_text" ]; then
    exit 0
fi

# JSON-escape via Python
json_body=$(python3 -c "import json,sys; print(json.dumps({'text': sys.argv[1]}))" "$note_text")

# POST to daemon
http_code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 2 \
    -X POST "$MEM_AGENT_ENDPOINT/note" \
    -H "Content-Type: application/json" \
    -d "$json_body")

# Notify result
if [ "$http_code" = "200" ]; then
    osascript -e 'display notification "Note saved to memory." with title "mem-agent"' 2>/dev/null
else
    osascript -e 'display notification "Failed to save note (is daemon running?)." with title "mem-agent"' 2>/dev/null
fi
