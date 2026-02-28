"""Tests for modules/insight.py — daily insight engine."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _clear_log_cache():
    from soul_agent.modules.daily_log import clear_daily_log_cache
    clear_daily_log_cache()
    yield
    clear_daily_log_cache()

class TestParseDailyLogEntries:
    def test_parse_classified_entries(self):
        from soul_agent.modules.insight import parse_daily_log_entries

        log_content = (
            "---\ndate: 2026-02-25\n---\n"
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
        from soul_agent.modules.insight import parse_daily_log_entries

        log_content = (
            "---\ndate: 2026-02-25\n---\n"
            "[09:15] (note) quick standup meeting notes"
        )
        entries = parse_daily_log_entries(log_content)
        assert len(entries) == 1
        assert entries[0]["category"] == "uncategorized"
        assert entries[0]["source"] == "note"
        assert "standup meeting" in entries[0]["text"]

    def test_parse_empty_content(self):
        from soul_agent.modules.insight import parse_daily_log_entries

        entries = parse_daily_log_entries("")
        assert entries == []

    def test_parse_mixed_entries(self):
        from soul_agent.modules.insight import parse_daily_log_entries

        log_content = (
            "---\ndate: 2026-02-25\n---\n"
            "[10:00] (terminal) [coding] wrote tests\n"
            "[11:00] (note) unclassified entry"
        )
        entries = parse_daily_log_entries(log_content)
        assert len(entries) == 2
        assert entries[0]["category"] == "coding"
        assert entries[1]["category"] == "uncategorized"


class TestComputeTimeAllocation:
    def test_basic_allocation(self):
        from soul_agent.modules.insight import compute_time_allocation

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
        from soul_agent.modules.insight import compute_time_allocation

        result = compute_time_allocation([])
        assert result == {}


class TestGetTopTags:
    def test_top_tags(self):
        from soul_agent.modules.insight import get_top_tags

        entries = [
            {"time": "10:00", "source": "terminal", "category": "coding", "text": "a", "tags": ["python", "refactor"]},
            {"time": "11:00", "source": "terminal", "category": "coding", "text": "b", "tags": ["python", "testing"]},
            {"time": "12:00", "source": "browser", "category": "learning", "text": "c", "tags": ["rust"]},
        ]
        result = get_top_tags(entries, n=10)
        assert result[0] == ("python", 2)
        assert len(result) == 4

    def test_top_tags_limit(self):
        from soul_agent.modules.insight import get_top_tags

        entries = [
            {"time": "10:00", "source": "terminal", "category": "coding", "text": "a", "tags": ["python", "refactor"]},
            {"time": "11:00", "source": "terminal", "category": "coding", "text": "b", "tags": ["python", "testing"]},
            {"time": "12:00", "source": "browser", "category": "learning", "text": "c", "tags": ["rust"]},
        ]
        result = get_top_tags(entries, n=2)
        assert len(result) == 2
        assert result[0] == ("python", 2)

    def test_top_tags_empty(self):
        from soul_agent.modules.insight import get_top_tags

        result = get_top_tags([], n=10)
        assert result == []


class TestBuildDailyInsight:
    @patch("soul_agent.modules.insight.call_deepseek", return_value="- 建议1\n- 建议2")
    def test_build_daily_insight(self, mock_llm):
        from soul_agent.modules.insight import build_daily_insight

        engine = MagicMock()
        engine.config = {}
        log_content = (
            "---\ndate: 2026-02-25\n---\n"
            "[10:00] (terminal) [coding] wrote unit tests for insight module\n"
            "[11:30] (browser) [learning] read article about design patterns\n"
            "[14:00] (terminal) [coding] refactored parser module"
        )
        engine.read_resource.side_effect = lambda rel_path: log_content if "logs" in rel_path else None
        engine.list_resources.return_value = []
        engine.search.return_value = []

        report = build_daily_insight(date(2026, 2, 25), engine)
        assert "今日工作总结" in report
        assert "任务状态" in report
        assert "洞察与建议" in report
        assert "时间分布" in report
        # Phase 1 + Phase 2 = 2 LLM calls
        assert mock_llm.call_count == 2

    @patch("soul_agent.modules.insight.call_deepseek", return_value="- 建议")
    def test_build_daily_insight_with_notes(self, mock_llm):
        """Notes (source=note) should be included as high-value content."""
        from soul_agent.modules.insight import build_daily_insight

        engine = MagicMock()
        engine.config = {}
        log_content = (
            "---\ndate: 2026-02-25\n---\n"
            "[10:00] (terminal) [coding] wrote tests\n"
            "[11:00] (note) [work] 会议纪要：Q2目标确认，需要跟进预算审批"
        )
        engine.read_resource.side_effect = lambda rel_path: log_content if "logs" in rel_path else None
        engine.list_resources.return_value = []
        engine.search.return_value = []

        report = build_daily_insight(date(2026, 2, 25), engine)
        assert "今日工作总结" in report
        phase1_call = mock_llm.call_args_list[0]
        assert "会议纪要" in phase1_call.kwargs.get("prompt", phase1_call[1].get("prompt", "")) or \
               "会议纪要" in str(phase1_call)

    @patch("soul_agent.modules.insight.call_deepseek", return_value="- 建议")
    def test_build_daily_insight_filters_noise(self, mock_llm):
        """Temp file entries should be filtered out."""
        from soul_agent.modules.insight import build_daily_insight

        engine = MagicMock()
        engine.config = {}
        log_content = (
            "---\ndate: 2026-02-25\n---\n"
            "[10:00] (fs) [file] File moved: report.tmp\n"
            "[10:05] (editor) [coding] Edited main.py\n"
            "[10:10] (fs) [file] Created ~$draft.docx"
        )
        engine.read_resource.side_effect = lambda rel_path: log_content if "logs" in rel_path else None
        engine.list_resources.return_value = []
        engine.search.return_value = []

        report = build_daily_insight(date(2026, 2, 25), engine)
        assert "coding" in report
        assert mock_llm.call_count == 2

    def test_build_daily_insight_no_data(self):
        from soul_agent.modules.insight import build_daily_insight

        engine = MagicMock()
        engine.config = {}
        engine.read_resource.return_value = None

        report = build_daily_insight(date(2026, 2, 25), engine)
        assert "无数据" in report or report == ""


class TestSaveDailyInsight:
    @patch("soul_agent.modules.insight.build_daily_insight", return_value="# Insight Report\nsome content")
    def test_save_daily_insight(self, mock_build):
        from soul_agent.modules.insight import save_daily_insight

        engine = MagicMock()
        engine.config = {}

        result = save_daily_insight(date(2026, 2, 25), engine)
        assert result == "# Insight Report\nsome content"
        engine.write_resource.assert_called_once()
        call_kwargs = engine.write_resource.call_args.kwargs
        assert "daily-2026-02-25.md" in call_kwargs["filename"]


class TestFilterAndCluster:
    def test_is_noise(self):
        from soul_agent.modules.insight import _is_noise

        assert _is_noise("File moved: foo.tmp") is True
        assert _is_noise("download.crdownload") is True
        assert _is_noise("~$report.docx") is True
        assert _is_noise(".DS_Store access") is True
        assert _is_noise("Edited quarterly report") is False

    def test_dedup_browsing(self):
        from soul_agent.modules.insight import _dedup_browsing

        entries = [
            {"time": "10:00", "source": "browsing", "category": "web", "text": "visited https://example.com/page1", "tags": []},
            {"time": "10:05", "source": "browsing", "category": "web", "text": "visited https://example.com/page1", "tags": []},
            {"time": "10:10", "source": "browsing", "category": "web", "text": "visited https://example.com/page2", "tags": []},
            {"time": "10:15", "source": "editor", "category": "coding", "text": "editing main.py", "tags": []},
        ]
        result = _dedup_browsing(entries)
        assert len(result) == 3

    def test_time_period(self):
        from soul_agent.modules.insight import _time_period

        assert _time_period("09:30") == "上午"
        assert _time_period("12:00") == "下午"
        assert _time_period("18:00") == "晚上"

    def test_cluster_consecutive_entries(self):
        from soul_agent.modules.insight import _filter_and_cluster_entries

        entries = [
            {"time": "09:00", "source": "editor", "category": "coding", "text": "Edited main.py", "tags": []},
            {"time": "09:10", "source": "editor", "category": "coding", "text": "Edited utils.py", "tags": []},
            {"time": "09:15", "source": "editor", "category": "coding", "text": "Edited tests.py", "tags": []},
            {"time": "14:00", "source": "meeting", "category": "communication", "text": "Team standup", "tags": []},
        ]
        filtered, clusters = _filter_and_cluster_entries(entries)
        assert len(filtered) == 4
        coding_cluster = [c for c in clusters if c["category"] == "coding"]
        assert len(coding_cluster) == 1
        assert coding_cluster[0]["count"] == 3
        assert coding_cluster[0]["period"] == "上午"

    def test_noise_filtered_from_clusters(self):
        from soul_agent.modules.insight import _filter_and_cluster_entries

        entries = [
            {"time": "09:00", "source": "fs", "category": "file", "text": "File moved: temp.tmp", "tags": []},
            {"time": "09:05", "source": "editor", "category": "coding", "text": "Edited main.py", "tags": []},
        ]
        filtered, clusters = _filter_and_cluster_entries(entries)
        assert len(filtered) == 1
        assert filtered[0]["text"] == "Edited main.py"


class TestStartInsightThread:
    def test_starts_and_stops(self):
        from soul_agent.modules.insight import start_insight_thread

        engine = MagicMock()
        engine.config = {}
        engine.read_resource.return_value = None
        engine.list_resources.return_value = []

        thread, stop_event = start_insight_thread(engine)
        assert thread.is_alive()
        stop_event.clear()
        thread.join(timeout=3)
        assert not thread.is_alive()
