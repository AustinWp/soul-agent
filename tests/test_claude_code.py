"""Tests for modules/claude_code.py — Claude Code hook adapter."""
from __future__ import annotations

import json
import os
import tempfile


class TestBuildHookConfig:
    def test_returns_dict_with_hooks_key(self):
        from mem_agent.modules.claude_code import build_hook_config

        config = build_hook_config()
        assert isinstance(config, dict)
        assert "hooks" in config

    def test_has_post_tool_use(self):
        from mem_agent.modules.claude_code import build_hook_config

        config = build_hook_config()
        assert "postToolUse" in config["hooks"]

    def test_hook_references_daemon_port(self):
        from mem_agent.modules.claude_code import build_hook_config

        config = build_hook_config()
        # The hook command should reference the shell script which uses port 8330
        hooks = config["hooks"]["postToolUse"]
        assert len(hooks) >= 1
        command = hooks[0]["hooks"][0]["command"]
        assert "claude_code_hook.sh" in command

    def test_hook_has_description_marker(self):
        from mem_agent.modules.claude_code import HOOK_MARKER, build_hook_config

        config = build_hook_config()
        hooks = config["hooks"]["postToolUse"]
        desc = hooks[0]["hooks"][0]["description"]
        assert desc == HOOK_MARKER

    def test_hook_config_references_port_8330(self):
        from mem_agent.modules.claude_code import DAEMON_PORT

        assert DAEMON_PORT == 8330


class TestInstallHook:
    def test_install_creates_settings_file(self):
        from unittest.mock import patch

        from mem_agent.modules.claude_code import install_hook

        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = os.path.join(tmpdir, ".claude", "settings.json")
            with patch("mem_agent.modules.claude_code.CLAUDE_SETTINGS", type(os.path)(settings_path)):
                from pathlib import Path

                with patch("mem_agent.modules.claude_code.CLAUDE_SETTINGS", Path(settings_path)):
                    install_hook()

                    assert os.path.exists(settings_path)
                    with open(settings_path) as f:
                        settings = json.load(f)
                    assert "hooks" in settings
                    assert "postToolUse" in settings["hooks"]

    def test_install_is_idempotent(self):
        from pathlib import Path
        from unittest.mock import patch

        from mem_agent.modules.claude_code import install_hook

        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / ".claude" / "settings.json"
            with patch("mem_agent.modules.claude_code.CLAUDE_SETTINGS", settings_path):
                install_hook()
                install_hook()  # second call should be no-op

                with open(settings_path) as f:
                    settings = json.load(f)

                # Should only have one hook group, not duplicates
                assert len(settings["hooks"]["postToolUse"]) == 1


class TestUninstallHook:
    def test_uninstall_removes_hook(self):
        from pathlib import Path
        from unittest.mock import patch

        from mem_agent.modules.claude_code import install_hook, uninstall_hook

        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / ".claude" / "settings.json"
            with patch("mem_agent.modules.claude_code.CLAUDE_SETTINGS", settings_path):
                install_hook()
                uninstall_hook()

                with open(settings_path) as f:
                    settings = json.load(f)

                assert settings["hooks"]["postToolUse"] == []

    def test_uninstall_no_settings_file(self):
        from pathlib import Path
        from unittest.mock import patch

        from mem_agent.modules.claude_code import uninstall_hook

        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / ".claude" / "settings.json"
            with patch("mem_agent.modules.claude_code.CLAUDE_SETTINGS", settings_path):
                # Should not raise
                uninstall_hook()


class TestHookScript:
    def test_hook_script_exists(self):
        from mem_agent.modules.claude_code import HOOK_SCRIPT

        assert HOOK_SCRIPT.exists()

    def test_hook_script_references_port(self):
        from mem_agent.modules.claude_code import HOOK_SCRIPT

        content = HOOK_SCRIPT.read_text()
        assert "8330" in content
        assert "127.0.0.1" in content

    def test_hook_script_is_bash(self):
        from mem_agent.modules.claude_code import HOOK_SCRIPT

        content = HOOK_SCRIPT.read_text()
        assert content.startswith("#!/bin/bash")
