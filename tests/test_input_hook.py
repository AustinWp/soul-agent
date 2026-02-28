"""Tests for modules/input_hook.py — input method hook adapter."""
from __future__ import annotations

from unittest.mock import MagicMock


class TestDedicatedApps:
    def test_contains_terminal(self):
        from soul_agent.modules.input_hook import DEDICATED_APPS

        assert "com.apple.Terminal" in DEDICATED_APPS

    def test_contains_iterm2(self):
        from soul_agent.modules.input_hook import DEDICATED_APPS

        assert "com.googlecode.iterm2" in DEDICATED_APPS

    def test_contains_vscode(self):
        from soul_agent.modules.input_hook import DEDICATED_APPS

        assert "com.microsoft.VSCode" in DEDICATED_APPS

    def test_contains_warp(self):
        from soul_agent.modules.input_hook import DEDICATED_APPS

        assert "dev.warp.Warp-Stable" in DEDICATED_APPS


class TestInputBuffer:
    def test_flush_with_enough_text(self):
        from soul_agent.modules.input_hook import InputBuffer

        queue = MagicMock()
        buf = InputBuffer(queue, min_length=10)

        for ch in "Hello World!":
            buf.append(ch)

        assert buf.should_flush() is True
        buf.flush()
        queue.put.assert_called_once()

        item = queue.put.call_args[0][0]
        assert item.source == "input-method"
        assert "Hello World!" in item.text

    def test_flush_too_short_discarded(self):
        from soul_agent.modules.input_hook import InputBuffer

        queue = MagicMock()
        buf = InputBuffer(queue, min_length=10)

        buf.append("Hi")
        assert buf.should_flush() is False
        buf.flush()
        queue.put.assert_not_called()

    def test_flush_exactly_min_length(self):
        from soul_agent.modules.input_hook import InputBuffer

        queue = MagicMock()
        buf = InputBuffer(queue, min_length=5)

        buf.append("12345")
        assert buf.should_flush() is True
        buf.flush()
        queue.put.assert_called_once()

    def test_flush_clears_buffer(self):
        from soul_agent.modules.input_hook import InputBuffer

        queue = MagicMock()
        buf = InputBuffer(queue, min_length=5)

        buf.append("Hello World")
        buf.flush()
        assert buf.should_flush() is False

        # Second flush should not produce anything
        buf.flush()
        assert queue.put.call_count == 1

    def test_append_accumulates(self):
        from soul_agent.modules.input_hook import InputBuffer

        queue = MagicMock()
        buf = InputBuffer(queue, min_length=10)

        buf.append("ab")
        buf.append("cd")
        buf.append("ef")
        assert buf.should_flush() is False

        buf.append("ghij")  # total now 10
        assert buf.should_flush() is True


class TestHookStatus:
    def test_initial_state_not_active(self):
        from soul_agent.modules.input_hook import hook_status

        status = hook_status()
        assert status["active"] is False

    def test_hook_status_returns_dict(self):
        from soul_agent.modules.input_hook import hook_status

        status = hook_status()
        assert isinstance(status, dict)
        assert "active" in status
        assert "keystrokes" in status
        assert "flushes" in status


class TestStopInputHook:
    def test_stop_when_not_started(self):
        from soul_agent.modules.input_hook import stop_input_hook

        # Should not raise
        stop_input_hook()
