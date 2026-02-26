"""Tests for modules/lifecycle.py — priority tagging and expiry management."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest


class TestTagResource:
    def test_tag_existing_resource(self):
        from mem_agent.modules.lifecycle import tag_resource

        engine = MagicMock()
        engine.read_resource.return_value = "---\nid: abc\n---\nsome body"

        result = tag_resource(
            "viking://resources/logs/2026-02-23.md",
            priority="P1",
            ttl_days=90,
            engine=engine,
        )

        assert result is True
        engine.delete_resource.assert_called_once()
        content = engine.write_resource.call_args.kwargs["content"]
        assert "priority: P1" in content
        assert "expire:" in content

    def test_tag_missing_resource(self):
        from mem_agent.modules.lifecycle import tag_resource

        engine = MagicMock()
        engine.read_resource.return_value = None

        result = tag_resource(
            "viking://resources/logs/missing.md",
            priority="P1",
            ttl_days=90,
            engine=engine,
        )

        assert result is False


class TestScanExpired:
    def test_scan_finds_expired(self):
        from mem_agent.modules.lifecycle import scan_expired

        yesterday = (date.today() - timedelta(days=1)).isoformat()
        engine = MagicMock()
        engine.list_resources.return_value = ["old.md", "new.md"]
        engine.read_resource.side_effect = [
            f"---\npriority: P2\nexpire: {yesterday}\n---\nold content",
            "---\npriority: P1\nexpire: 2099-12-31\n---\nnew content",
        ]

        expired = scan_expired("viking://resources/logs/", engine)

        assert len(expired) == 1
        assert expired[0]["filename"] == "old.md"

    def test_scan_empty_directory(self):
        from mem_agent.modules.lifecycle import scan_expired

        engine = MagicMock()
        engine.list_resources.return_value = []

        expired = scan_expired("viking://resources/logs/", engine)
        assert expired == []

    def test_scan_skips_dotfiles(self):
        from mem_agent.modules.lifecycle import scan_expired

        engine = MagicMock()
        engine.list_resources.return_value = [".abstract", "file.md"]
        engine.read_resource.return_value = "---\npriority: P1\n---\nbody"

        scan_expired("viking://resources/logs/", engine)

        # Should only read file.md
        engine.read_resource.assert_called_once()


class TestArchiveResource:
    def test_archive_moves_to_archive(self):
        from mem_agent.modules.lifecycle import archive_resource

        engine = MagicMock()
        engine.read_resource.return_value = "---\npriority: P2\n---\nold content"

        result = archive_resource("viking://resources/logs/2026-01-01.md", engine)

        assert result is True
        engine.write_resource.assert_called_once()
        assert engine.write_resource.call_args.kwargs["target_uri"] == "viking://resources/archive/"
        assert "logs_" in engine.write_resource.call_args.kwargs["filename"]
        engine.delete_resource.assert_called_once_with("viking://resources/logs/2026-01-01.md")

    def test_archive_missing_resource(self):
        from mem_agent.modules.lifecycle import archive_resource

        engine = MagicMock()
        engine.read_resource.return_value = None

        result = archive_resource("viking://resources/logs/missing.md", engine)
        assert result is False


class TestScanAllExpired:
    def test_scans_all_directories(self):
        from mem_agent.modules.lifecycle import SCAN_DIRS, scan_all_expired

        engine = MagicMock()
        engine.list_resources.return_value = []

        scan_all_expired(engine)

        # Should have called list_resources for each scan directory
        assert engine.list_resources.call_count == len(SCAN_DIRS)
