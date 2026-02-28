"""Claude Code hook adapter — installs/uninstalls hook in Claude settings."""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"
HOOK_SCRIPT = Path(__file__).parent.parent / "hooks" / "claude_code_hook.sh"
DAEMON_PORT = 8330
HOOK_MARKER = "soul-agent-claude-code-hook"


# ---------------------------------------------------------------------------
# Hook configuration
# ---------------------------------------------------------------------------

def build_hook_config() -> dict:
    """Return the hooks configuration dict for Claude Code settings.

    The returned dict has a ``"hooks"`` key with the configuration that
    pipes post-tool-use summaries to the soul-agent daemon.
    """
    return {
        "hooks": {
            "postToolUse": [
                {
                    "matcher": ".*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f'bash "{HOOK_SCRIPT}"',
                            "description": HOOK_MARKER,
                        }
                    ],
                }
            ]
        }
    }


def install_hook() -> None:
    """Merge the soul-agent hook config into Claude Code settings.json.

    If the settings file does not exist it will be created.  If the hook
    is already present the operation is a no-op.
    """
    settings: dict = {}
    if CLAUDE_SETTINGS.exists():
        try:
            settings = json.loads(CLAUDE_SETTINGS.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Could not parse %s, starting fresh.", CLAUDE_SETTINGS)

    # Check if already installed
    existing_hooks = settings.get("hooks", {}).get("postToolUse", [])
    for group in existing_hooks:
        for hook in group.get("hooks", []):
            if hook.get("description") == HOOK_MARKER:
                logger.info("Claude Code hook already installed.")
                return

    # Merge
    hook_config = build_hook_config()
    if "hooks" not in settings:
        settings["hooks"] = {}
    if "postToolUse" not in settings["hooks"]:
        settings["hooks"]["postToolUse"] = []

    settings["hooks"]["postToolUse"].extend(hook_config["hooks"]["postToolUse"])

    CLAUDE_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    CLAUDE_SETTINGS.write_text(
        json.dumps(settings, indent=2) + "\n",
        encoding="utf-8",
    )
    logger.info("Claude Code hook installed in %s", CLAUDE_SETTINGS)


def uninstall_hook() -> None:
    """Remove the soul-agent hook from Claude Code settings.json."""
    if not CLAUDE_SETTINGS.exists():
        logger.info("No Claude settings file found, nothing to remove.")
        return

    try:
        settings = json.loads(CLAUDE_SETTINGS.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Could not parse %s, nothing to remove.", CLAUDE_SETTINGS)
        return

    existing_hooks = settings.get("hooks", {}).get("postToolUse", [])
    if not existing_hooks:
        logger.info("No hooks found in settings.")
        return

    # Filter out our hook groups
    filtered = []
    for group in existing_hooks:
        filtered_hooks = [
            h for h in group.get("hooks", [])
            if h.get("description") != HOOK_MARKER
        ]
        if filtered_hooks:
            group["hooks"] = filtered_hooks
            filtered.append(group)

    settings["hooks"]["postToolUse"] = filtered

    CLAUDE_SETTINGS.write_text(
        json.dumps(settings, indent=2) + "\n",
        encoding="utf-8",
    )
    logger.info("Claude Code hook removed from %s", CLAUDE_SETTINGS)
