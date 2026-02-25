"""Tests for modules/compact.py — L2-to-L1 compression."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest


class TestWeekLabel:
    def test_week_label_format(self):
        from mem_agent.modules.compact import _week_label

        result = _week_label(date(2026, 2, 23))
        assert result.startswith("2026-W")
        # Feb 23, 2026 is a Monday (week 9)
        assert result == "2026-W09"

    def test_month_label_format(self):
        from mem_agent.modules.compact import _month_label

        result = _month_label(date(2026, 2, 23))
        assert result == "2026-02"


def _make_list_resources_with_dates(dates):
    """Create a list_resources mock that returns date dirs for logs, empty for others."""
    dirs = [f"{d}/" for d in dates]
    def _list(uri):
        if "logs" in uri:
            return dirs
        return []
    return _list


class TestCompactWeek:
    @patch("mem_agent.modules.compact.call_deepseek", return_value="# Weekly Report\n- Did things")
    def test_compact_with_logs(self, mock_llm):
        from mem_agent.modules.compact import compact_week

        engine = MagicMock()
        engine.config = {}

        # Mock daily log reads (7 days)
        def mock_read(uri):
            if "logs/" in uri:
                return "---\ndate: 2026-02-23\n---\n[10:00] (note) test entry"
            return None
        engine.read_resource.side_effect = mock_read
        engine.list_resources.side_effect = _make_list_resources_with_dates(
            [(date(2026, 2, 23) + timedelta(days=i)).isoformat() for i in range(7)]
        )

        # Mock search results
        mock_results = MagicMock()
        mock_results.memories = []
        mock_results.resources = []
        engine.search.return_value = mock_results

        result = compact_week(date(2026, 2, 23), engine)

        assert "Weekly Report" in result
        mock_llm.assert_called_once()
        engine.write_resource.assert_called_once()
        assert engine.write_resource.call_args.kwargs["target_uri"] == "viking://resources/insights/"

    def test_compact_no_data(self):
        from mem_agent.modules.compact import compact_week

        engine = MagicMock()
        engine.read_resource.return_value = None
        engine.list_resources.return_value = []
        engine.config = {}

        mock_results = MagicMock()
        mock_results.memories = []
        mock_results.resources = []
        engine.search.return_value = mock_results

        result = compact_week(date(2026, 2, 23), engine)
        assert result == ""

    @patch("mem_agent.modules.compact.call_deepseek", return_value="")
    def test_compact_llm_failure_fallback(self, mock_llm):
        from mem_agent.modules.compact import compact_week

        engine = MagicMock()
        engine.config = {}

        def mock_read(uri):
            if "logs/" in uri:
                return "---\ndate: 2026-02-23\n---\n[10:00] (note) test"
            return None
        engine.read_resource.side_effect = mock_read
        engine.list_resources.side_effect = _make_list_resources_with_dates(
            [(date(2026, 2, 23) + timedelta(days=i)).isoformat() for i in range(7)]
        )

        mock_results = MagicMock()
        mock_results.memories = []
        mock_results.resources = []
        engine.search.return_value = mock_results

        result = compact_week(date(2026, 2, 23), engine)

        # Should still produce output (fallback)
        assert "Week" in result or "test" in result


class TestCompactMonth:
    @patch("mem_agent.modules.compact.call_deepseek", return_value="# Monthly Report\n- Overview")
    def test_compact_with_weekly_reports(self, mock_llm):
        from mem_agent.modules.compact import compact_month

        engine = MagicMock()
        engine.config = {}
        engine.list_resources.return_value = ["2026-W08.md", "2026-W09.md"]
        engine.read_resource.side_effect = lambda uri: (
            "---\ntype: weekly-report\n---\nWeek content"
            if "insights/" in uri else None
        )

        result = compact_month(date(2026, 2, 23), engine)

        assert "Monthly Report" in result
        engine.write_resource.assert_called_once()

    @patch("mem_agent.modules.compact.call_deepseek", return_value="# Monthly Report")
    def test_compact_month_fallback_to_daily(self, mock_llm):
        from mem_agent.modules.compact import compact_month

        engine = MagicMock()
        engine.config = {}

        # list_resources returns daily log dirs for logs, empty for insights
        def mock_list(uri):
            if "logs" in uri:
                return [f"2026-02-{d:02d}/" for d in range(1, 29)]
            return []
        engine.list_resources.side_effect = mock_list

        def mock_read(uri):
            if "logs/" in uri:
                return "---\ndate: 2026-02-01\n---\n[10:00] (note) entry"
            return None
        engine.read_resource.side_effect = mock_read

        result = compact_month(date(2026, 2, 15), engine)
        assert result != ""
