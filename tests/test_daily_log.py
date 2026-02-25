"""Tests for modules/daily_log.py — L2 daily log operations."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest


class TestAppendDailyLog:
    def test_create_new_log(self):
        from mem_agent.modules.daily_log import append_daily_log

        engine = MagicMock()
        engine.read_resource.return_value = None
        engine.config = {}

        append_daily_log("test note", "note", engine)

        engine.write_resource.assert_called_once()
        call_args = engine.write_resource.call_args
        content = call_args.kwargs["content"]
        assert "priority: P2" in content
        assert "(note) test note" in content
        assert date.today().isoformat() in call_args.kwargs["filename"]

    def test_append_to_existing_log(self):
        from mem_agent.modules.daily_log import append_daily_log

        engine = MagicMock()
        existing = "---\ndate: 2026-02-23\npriority: P2\n---\n[10:00] (note) first entry"
        engine.read_resource.return_value = existing
        engine.config = {}

        append_daily_log("second entry", "clipboard", engine)

        engine.delete_resource.assert_called_once()
        engine.write_resource.assert_called_once()
        content = engine.write_resource.call_args.kwargs["content"]
        assert "first entry" in content
        assert "(clipboard) second entry" in content

    def test_log_filename_format(self):
        from mem_agent.modules.daily_log import append_daily_log

        engine = MagicMock()
        engine.read_resource.return_value = None

        append_daily_log("test", "note", engine)

        filename = engine.write_resource.call_args.kwargs["filename"]
        assert filename == f"{date.today().isoformat()}.md"


class TestGetDailyLog:
    def test_get_existing_log(self):
        from mem_agent.modules.daily_log import get_daily_log

        engine = MagicMock()
        engine.read_resource.return_value = "log content"

        result = get_daily_log(date(2026, 2, 23), engine)

        assert result == "log content"
        engine.read_resource.assert_called_with("viking://resources/logs/2026-02-23.md")

    def test_get_missing_log(self):
        from mem_agent.modules.daily_log import get_daily_log

        engine = MagicMock()
        engine.read_resource.return_value = None

        result = get_daily_log(date(2026, 2, 23), engine)
        assert result is None


class TestAppendClassifiedLog:
    def test_append_with_classification(self):
        from unittest.mock import MagicMock

        from mem_agent.modules.daily_log import append_daily_log

        engine = MagicMock()
        engine.config = {}
        engine.read_resource.return_value = None
        append_daily_log("fixed parser bug", "note", engine, category="coding", tags=["python", "bugfix"], importance=4)
        engine.write_resource.assert_called_once()
        content = engine.write_resource.call_args.kwargs.get("content", "")
        assert "[coding]" in content

    def test_append_preserves_existing_classified_entries(self):
        from unittest.mock import MagicMock

        from mem_agent.modules.daily_log import append_daily_log

        engine = MagicMock()
        engine.config = {}
        engine.read_resource.return_value = "---\npriority: P2\ndate: 2026-02-25\n---\n[10:00] (note) [coding] first entry\n"
        append_daily_log("read article about Rust", "browser", engine, category="learning", tags=["rust"], importance=2)
        engine.write_resource.assert_called_once()
        content = engine.write_resource.call_args.kwargs.get("content", "")
        assert "[coding] first entry" in content
        assert "[learning]" in content
