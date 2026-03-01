#!/bin/bash
# soul-agent zsh hook — terminal command capture
# Source this file in your .zshrc to enable terminal command capture.
#
# Usage: source /path/to/zsh_hook.sh

SOUL_AGENT_ENDPOINT="${SOUL_AGENT_URL:-http://localhost:8330}"
SOUL_AGENT_ENABLED=true

soul_agent_preexec() {
    if [ "$SOUL_AGENT_ENABLED" = true ]; then
        SOUL_AGENT_LAST_CMD="$1"
        SOUL_AGENT_CMD_START=$(date +%s)
    fi
}

soul_agent_precmd() {
    local exit_code=$?
    if [ "$SOUL_AGENT_ENABLED" = true ] && [ -n "$SOUL_AGENT_LAST_CMD" ]; then
        local duration=$(( $(date +%s) - SOUL_AGENT_CMD_START ))
        # JSON-escape the command string (handle backslashes and double quotes)
        local escaped_cmd
        escaped_cmd=$(printf '%s' "$SOUL_AGENT_LAST_CMD" | sed 's/\\/\\\\/g; s/"/\\"/g')
        (curl -s --connect-timeout 1 -X POST "$SOUL_AGENT_ENDPOINT/terminal/cmd" \
            -H "Content-Type: application/json" \
            -d "{\"command\": \"$escaped_cmd\", \"exit_code\": $exit_code, \"duration\": $duration}" \
            > /dev/null &) 2>/dev/null
        SOUL_AGENT_LAST_CMD=""
    fi
}

# Register hooks
autoload -Uz add-zsh-hook
add-zsh-hook preexec soul_agent_preexec
add-zsh-hook precmd soul_agent_precmd
