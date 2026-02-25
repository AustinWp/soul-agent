"""Tests for modules/insight.py — daily insight engine."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest


class TestParseDailyLogEntries:
    def test_parse_classified_entries(self):
        from mem_agent.modules.insight import parse_daily_log_entries

        log_content = (
            "---\ndate: 2026-02-25\npriority: P2\n---\n"
            "[10:00] (terminal) [coding] git commit -m 'fix parser'\n"
            "[11:30] (browser) [learning] read article about Rust generics\n"
            "[14:00] (note) [work] reviewed PR #42 comments"
        )
        entries = parse_daily_log_entries(log_content)
        assert len(entries) == 3
        assert entries[0]["time"] == "10:00"
        assert entries[0]["source"] == "terminal"
        assert entries[0]["category"] == "coding"
        assert "git commit" in entries[0]["text"]
        assert entries[1]["category"] == "learning"
        assert entries[2]["category"] == "work"

    def test_parse_unclassified_entries(self):
        from mem_agent.modules.insight import parse_daily_log_entries

        log_content = (
            "---\ndate: 2026-02-25\npriority: P2\n---\n"
            "[09:15] (note) quick standup meeting notes"
        )
        entries = parse_daily_log_entries(log_content)
        assert len(entries) == 1
        assert entries[0]["category"] == "uncategorized"
        assert entries[0]["source"] == "note"
        assert "standup meeting" in entries[0]["text"]

    def test_parse_empty_content(self):
        from mem_agent.modules.insight import parse_daily_log_entries

        entries = parse_daily_log_entries("")
        assert entries == []

    def test_parse_mixed_entries(self):
        from mem_agent.modules.insight import parse_daily_log_entries

        log_content = (
            "---\ndate: 2026-02-25\npriority: P2\n---\n"
            "[10:00] (terminal) [coding] wrote tests\n"
            "[11:00] (note) unclassified entry"
        )
        entries = parse_daily_log_entries(log_content)
        assert len(entries) == 2
        assert entries[0]["category"] == "coding"
        assert entries[1]["category"] == "uncategorized"


class TestComputeTimeAllocation:
    def test_basic_allocation(self):
        from mem_agent.modules.insight import compute_time_allocation

        entries = [
            {"time": "10:00", "source": "terminal", "category": "coding", "text": "a", "tags": []},
            {"time": "11:00", "source": "terminal", "category": "coding", "text": "b", "tags": []},
            {"time": "12:00", "source": "browser", "category": "learning", "text": "c", "tags": []},
            {"time": "14:00", "source": "note", "category": "work", "text": "d", "tags": []},
        ]
        result = compute_time_allocation(entries)
        assert "coding" in result
        assert result["coding"]["count"] == 2
        assert result["coding"]["percent"] == 50.0
        assert result["learning"]["count"] == 1
        assert result["learning"]["percent"] == 25.0
        assert result["work"]["count"] == 1
        assert len(result["coding"]["entries"]) == 2

    def test_empty_entries(self):
        from mem_agent.modules.insight import compute_time_allocation

        result = compute_time_allocation([])
        assert result == {}


class TestGetTopTags:
    def test_top_tags(self):
        from mem_agent.modules.insight import get_top_tags

        entries = [
            {"time": "10:00", "source": "terminal", "category": "coding", "text": "a", "tags": ["python", "refactor"]},
            {"time": "11:00", "source": "terminal", "category": "coding", "text": "b", "tags": ["python", "testing"]},
            {"time": "12:00", "source": "browser", "category": "learning", "text": "c", "tags": ["rust"]},
        ]
        result = get_top_tags(entries, n=10)
        # python should be first with count 2
        assert result[0] == ("python", 2)
        assert len(result) == 4  # python, refactor, testing, rust

    def test_top_tags_limit(self):
        from mem_agent.modules.insight import get_top_tags

        entries = [
            {"time": "10:00", "source": "terminal", "category": "coding", "text": "a", "tags": ["python", "refactor"]},
            {"time": "11:00", "source": "terminal", "category": "coding", "text": "b", "tags": ["python", "testing"]},
            {"time": "12:00", "source": "browser", "category": "learning", "text": "c", "tags": ["rust"]},
        ]
        result = get_top_tags(entries, n=2)
        assert len(result) == 2
        assert result[0] == ("python", 2)

    def test_top_tags_empty(self):
        from mem_agent.modules.insight import get_top_tags

        result = get_top_tags([], n=10)
        assert result == []


class TestBuildDailyInsight:
    @patch("mem_agent.modules.insight.call_deepseek", return_value="- 建议1\n- 建议2")
    def test_build_daily_insight(self, mock_llm):
        from mem_agent.modules.insight import build_daily_insight

        engine = MagicMock()
        engine.config = {}
        log_content = (
            "---\ndate: 2026-02-25\npriority: P2\n---\n"
            "[10:00] (terminal) [coding] wrote unit tests for insight module\n"
            "[11:30] (browser) [learning] read article about design patterns\n"
            "[14:00] (terminal) [coding] refactored parser module"
        )
        engine.read_resource.side_effect = lambda uri: log_content if "logs" in uri else None
        engine.list_resources.return_value = ["2026-02-25/"]

        report = build_daily_insight(date(2026, 2, 25), engine)
        assert "coding" in report
        assert "learning" in report
        mock_llm.assert_called_once()

    def test_build_daily_insight_no_data(self):
        from mem_agent.modules.insight import build_daily_insight

        engine = MagicMock()
        engine.config = {}
        engine.read_resource.return_value = None
        engine.list_resources.return_value = []

        report = build_daily_insight(date(2026, 2, 25), engine)
        assert "无数据" in report or report == ""


class TestSaveDailyInsight:
    @patch("mem_agent.modules.insight.build_daily_insight", return_value="# Insight Report\nsome content")
    def test_save_daily_insight(self, mock_build):
        from mem_agent.modules.insight import save_daily_insight

        engine = MagicMock()
        engine.config = {}

        result = save_daily_insight(date(2026, 2, 25), engine)
        assert result == "# Insight Report\nsome content"
        engine.write_resource.assert_called_once()
        call_kwargs = engine.write_resource.call_args.kwargs
        assert "daily-2026-02-25.md" in call_kwargs["filename"]
        assert "priority: P1" in call_kwargs["content"]


class TestStartInsightThread:
    def test_starts_and_stops(self):
        from mem_agent.modules.insight import start_insight_thread

        engine = MagicMock()
        engine.config = {}
        engine.read_resource.return_value = None
        engine.list_resources.return_value = []

        thread, stop_event = start_insight_thread(engine)
        assert thread.is_alive()
        stop_event.clear()
        thread.join(timeout=3)
        assert not thread.is_alive()
