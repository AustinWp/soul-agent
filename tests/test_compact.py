"""Tests for modules/compact.py — weekly and monthly report generation."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _clear_log_cache():
    from soul_agent.modules.daily_log import clear_daily_log_cache
    clear_daily_log_cache()
    yield
    clear_daily_log_cache()

class TestWeekLabel:
    def test_week_label_format(self):
        from soul_agent.modules.compact import _week_label

        result = _week_label(date(2026, 2, 23))
        assert result.startswith("2026-W")
        # Feb 23, 2026 is a Monday (week 9)
        assert result == "2026-W09"

    def test_month_label_format(self):
        from soul_agent.modules.compact import _month_label

        result = _month_label(date(2026, 2, 23))
        assert result == "2026-02"


class TestCompactWeek:
    @patch("soul_agent.modules.compact.call_deepseek", return_value="# Weekly Report\n- Did things")
    def test_compact_with_logs(self, mock_llm):
        from soul_agent.modules.compact import compact_week

        engine = MagicMock()
        engine.config = {}

        # Mock daily log reads
        def mock_read(rel_path):
            if "logs/" in rel_path:
                return "---\ndate: 2026-02-23\n---\n[10:00] (note) test entry"
            return None
        engine.read_resource.side_effect = mock_read
        engine.list_resources.return_value = []

        result = compact_week(date(2026, 2, 23), engine)

        assert "Weekly Report" in result
        mock_llm.assert_called_once()
        engine.write_resource.assert_called_once()
        assert engine.write_resource.call_args.kwargs["directory"] == "insights"

    def test_compact_no_data(self):
        from soul_agent.modules.compact import compact_week

        engine = MagicMock()
        engine.read_resource.return_value = None
        engine.list_resources.return_value = []
        engine.config = {}

        result = compact_week(date(2026, 2, 23), engine)
        assert result == ""

    @patch("soul_agent.modules.compact.call_deepseek", return_value="")
    def test_compact_llm_failure_fallback(self, mock_llm):
        from soul_agent.modules.compact import compact_week

        engine = MagicMock()
        engine.config = {}

        def mock_read(rel_path):
            if "logs/" in rel_path:
                return "---\ndate: 2026-02-23\n---\n[10:00] (note) test"
            return None
        engine.read_resource.side_effect = mock_read
        engine.list_resources.return_value = []

        result = compact_week(date(2026, 2, 23), engine)

        # Should still produce output (fallback)
        assert "Week" in result or "test" in result


class TestCompactMonth:
    @patch("soul_agent.modules.compact.call_deepseek", return_value="# Monthly Report\n- Overview")
    def test_compact_with_weekly_reports(self, mock_llm):
        from soul_agent.modules.compact import compact_month

        engine = MagicMock()
        engine.config = {}
        engine.list_resources.return_value = ["2026-W08.md", "2026-W09.md"]
        engine.read_resource.side_effect = lambda rel_path: (
            "---\ntype: weekly-report\n---\nWeek content"
            if "insights/" in rel_path else None
        )

        result = compact_month(date(2026, 2, 23), engine)

        assert "Monthly Report" in result
        engine.write_resource.assert_called_once()

    @patch("soul_agent.modules.compact.call_deepseek", return_value="# Monthly Report")
    def test_compact_month_fallback_to_daily(self, mock_llm):
        from soul_agent.modules.compact import compact_month

        engine = MagicMock()
        engine.config = {}

        # list_resources returns empty for insights (no weekly reports)
        def mock_list(directory):
            return []
        engine.list_resources.side_effect = mock_list

        def mock_read(rel_path):
            if "logs/" in rel_path:
                return "---\ndate: 2026-02-01\n---\n[10:00] (note) entry"
            return None
        engine.read_resource.side_effect = mock_read

        result = compact_month(date(2026, 2, 15), engine)
        assert result != ""
