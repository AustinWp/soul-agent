#!/bin/bash
# mem-agent zsh hook — terminal command capture
# Source this file in your .zshrc to enable terminal command capture.
#
# Usage: source /path/to/zsh_hook.sh

MEM_AGENT_ENDPOINT="${MEM_AGENT_URL:-http://localhost:8330}"
MEM_AGENT_ENABLED=true

mem_agent_preexec() {
    if [ "$MEM_AGENT_ENABLED" = true ]; then
        MEM_AGENT_LAST_CMD="$1"
        MEM_AGENT_CMD_START=$(date +%s)
    fi
}

mem_agent_precmd() {
    local exit_code=$?
    if [ "$MEM_AGENT_ENABLED" = true ] && [ -n "$MEM_AGENT_LAST_CMD" ]; then
        local duration=$(( $(date +%s) - MEM_AGENT_CMD_START ))
        # JSON-escape the command string (handle backslashes and double quotes)
        local escaped_cmd
        escaped_cmd=$(printf '%s' "$MEM_AGENT_LAST_CMD" | sed 's/\\/\\\\/g; s/"/\\"/g')
        (curl -s --connect-timeout 1 -X POST "$MEM_AGENT_ENDPOINT/terminal/cmd" \
            -H "Content-Type: application/json" \
            -d "{\"command\": \"$escaped_cmd\", \"exit_code\": $exit_code, \"duration\": $duration}" \
            > /dev/null &) 2>/dev/null
        MEM_AGENT_LAST_CMD=""
    fi
}

# Register hooks
autoload -Uz add-zsh-hook
add-zsh-hook preexec mem_agent_preexec
add-zsh-hook precmd mem_agent_precmd
