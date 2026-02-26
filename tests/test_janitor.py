"""Tests for modules/janitor.py — automatic cleanup daemon."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestRunJanitor:
    @patch("mem_agent.modules.janitor.scan_all_expired")
    @patch("mem_agent.modules.janitor.archive_resource")
    def test_run_archives_expired(self, mock_archive, mock_scan):
        from mem_agent.modules.janitor import run_janitor

        engine = MagicMock()
        mock_scan.return_value = [
            {"uri": "viking://resources/logs/old1.md"},
            {"uri": "viking://resources/logs/old2.md"},
        ]
        mock_archive.return_value = True

        result = run_janitor(engine)

        assert result["scanned"] == 2
        assert result["archived"] == 2
        assert mock_archive.call_count == 2

    @patch("mem_agent.modules.janitor.scan_all_expired")
    def test_run_nothing_expired(self, mock_scan):
        from mem_agent.modules.janitor import run_janitor

        engine = MagicMock()
        mock_scan.return_value = []

        result = run_janitor(engine)

        assert result["scanned"] == 0
        assert result["archived"] == 0

    @patch("mem_agent.modules.janitor.scan_all_expired")
    @patch("mem_agent.modules.janitor.archive_resource")
    def test_run_partial_archive_failure(self, mock_archive, mock_scan):
        from mem_agent.modules.janitor import run_janitor

        engine = MagicMock()
        mock_scan.return_value = [
            {"uri": "viking://resources/logs/old1.md"},
            {"uri": "viking://resources/logs/old2.md"},
        ]
        mock_archive.side_effect = [True, False]

        result = run_janitor(engine)

        assert result["scanned"] == 2
        assert result["archived"] == 1

    @patch("mem_agent.modules.janitor.scan_all_expired")
    @patch("mem_agent.modules.janitor.archive_resource")
    def test_run_updates_stats(self, mock_archive, mock_scan):
        from mem_agent.modules.janitor import janitor_stats, run_janitor

        engine = MagicMock()
        mock_scan.return_value = [{"uri": "viking://resources/logs/old.md"}]
        mock_archive.return_value = True

        # Reset stats
        janitor_stats["total_archived"] = 0

        run_janitor(engine)

        assert janitor_stats["last_run"] is not None
        assert janitor_stats["last_archived"] == 1
        assert janitor_stats["total_archived"] == 1


class TestJanitorThread:
    def test_start_stop(self):
        from mem_agent.modules.janitor import start_janitor_thread

        engine = MagicMock()
        thread, stop_event = start_janitor_thread(engine)

        assert thread.is_alive()

        stop_event.set()
        thread.join(timeout=2)
        assert not thread.is_alive()
