"""Basic tests for mem-agent."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── Config tests ────────────────────────────────────────────────────────────

class TestConfig:
    def test_expand_env_vars(self):
        from mem_agent.core.config import _expand_env_vars

        os.environ["TEST_KEY_123"] = "hello"
        result = _expand_env_vars({"key": "${TEST_KEY_123}"})
        assert result == {"key": "hello"}
        del os.environ["TEST_KEY_123"]

    def test_expand_nested(self):
        from mem_agent.core.config import _expand_env_vars

        os.environ["TEST_NESTED"] = "value"
        result = _expand_env_vars({"a": {"b": "${TEST_NESTED}"}})
        assert result == {"a": {"b": "value"}}
        del os.environ["TEST_NESTED"]

    def test_load_config(self):
        from mem_agent.core.config import load_config

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"vlm": {"provider": "test"}}, f)
            tmp = f.name

        try:
            config = load_config(tmp)
            assert config["vlm"]["provider"] == "test"
        finally:
            os.unlink(tmp)

    def test_load_config_missing(self):
        from mem_agent.core.config import load_config

        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/path/config.json")

    def test_get_data_dir(self):
        from mem_agent.core.config import get_data_dir

        d = get_data_dir()
        assert d.exists()
        assert d.is_dir()

    def test_get_deepseek_api_key_from_config(self):
        from mem_agent.core.config import get_deepseek_api_key

        config = {"vlm": {"api_key": "sk-test-key"}}
        assert get_deepseek_api_key(config) == "sk-test-key"

    def test_get_deepseek_api_key_env_fallback(self):
        from mem_agent.core.config import get_deepseek_api_key

        os.environ["DEEPSEEK_API_KEY"] = "env-key"
        assert get_deepseek_api_key({"vlm": {"api_key": "${DEEPSEEK_API_KEY}"}}) == "env-key"
        del os.environ["DEEPSEEK_API_KEY"]


# ── Todo helpers ────────────────────────────────────────────────────────────

class TestTodoHelpers:
    def test_build_todo_md(self):
        from mem_agent.modules.todo import _build_todo_md

        md = _build_todo_md("abc123", "Write tests", due="2026-02-24", priority="high")
        assert "id: abc123" in md
        assert "priority_label: high" in md
        assert "priority: P1" in md
        assert "due: 2026-02-24" in md
        assert "Write tests" in md

    def test_parse_due_today(self):
        from mem_agent.modules.todo import _parse_due

        result = _parse_due("today")
        assert result == date.today().isoformat()

    def test_parse_due_tomorrow(self):
        from mem_agent.modules.todo import _parse_due

        result = _parse_due("tomorrow")
        assert result == (date.today() + timedelta(days=1)).isoformat()

    def test_parse_due_iso(self):
        from mem_agent.modules.todo import _parse_due

        result = _parse_due("2026-03-01")
        assert result == "2026-03-01"

    def test_parse_due_none(self):
        from mem_agent.modules.todo import _parse_due

        assert _parse_due(None) is None

    def test_parse_frontmatter(self):
        from mem_agent.modules.todo import _parse_frontmatter

        content = "---\nid: abc\npriority: high\n---\nsome body"
        meta = _parse_frontmatter(content)
        assert meta["id"] == "abc"
        assert meta["priority"] == "high"

    def test_parse_frontmatter_empty(self):
        from mem_agent.modules.todo import _parse_frontmatter

        assert _parse_frontmatter("no frontmatter here") == {}


# ── Clipboard helpers ──────────────────────────────────────────────────────

class TestClipboard:
    def test_hash_text(self):
        from mem_agent.modules.clipboard import _hash_text

        h1 = _hash_text("hello")
        h2 = _hash_text("hello")
        h3 = _hash_text("world")
        assert h1 == h2
        assert h1 != h3
        assert len(h1) == 64  # sha256 hex digest

    def test_get_clipboard_text(self):
        from mem_agent.modules.clipboard import _get_clipboard_text

        # pbpaste should return a string (may be empty)
        result = _get_clipboard_text()
        assert isinstance(result, str)

    def test_clip_stats_initial(self):
        from mem_agent.modules.clipboard import clip_stats

        assert "active" in clip_stats
        assert "count" in clip_stats
        assert "last_hash" in clip_stats


# ── Service tests ──────────────────────────────────────────────────────────

class TestService:
    def test_app_importable(self):
        from mem_agent.service import app

        assert app is not None

    def test_app_has_routes(self):
        from mem_agent.service import app

        paths = [route.path for route in app.routes]
        assert "/health" in paths
        assert "/note" in paths
        assert "/search" in paths
        assert "/clipboard/status" in paths
        assert "/terminal/cmd" in paths
        # Phase 3 endpoints
        assert "/compact" in paths
        assert "/abstract/{path:path}" in paths
        assert "/lifecycle/tag" in paths
        assert "/janitor/status" in paths
        assert "/daily-log" in paths

    def test_pid_helpers(self):
        from mem_agent.service import _read_pid, PID_FILE

        # With no PID file, should return None
        if PID_FILE.exists():
            PID_FILE.unlink()
        assert _read_pid() is None


# ── Terminal tests ─────────────────────────────────────────────────────────

class TestTerminal:
    def test_hook_script_exists(self):
        from mem_agent.modules.terminal import HOOK_SCRIPT

        assert HOOK_SCRIPT.exists()

    def test_hook_marker_defined(self):
        from mem_agent.modules.terminal import HOOK_MARKER

        assert HOOK_MARKER
        assert "mem-agent" in HOOK_MARKER


# ── CLI import test ─────────────────────────────────────────────────────────

class TestCLI:
    def test_app_importable(self):
        from mem_agent.cli import app

        assert app is not None

    def test_app_has_commands(self):
        from mem_agent.cli import app

        # Typer stores registered commands/groups
        assert app.registered_groups or app.registered_commands

        # Check Phase 3 subcommand groups are registered
        group_names = [g.name for g in app.registered_groups]
        assert "core" in group_names
        assert "abstract" in group_names
        assert "janitor" in group_names

        # Check compact command is registered
        cmd_names = [c.callback.__name__ if c.callback else "" for c in app.registered_commands]
        assert "compact" in cmd_names
