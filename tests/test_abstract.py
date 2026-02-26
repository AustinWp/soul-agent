"""Tests for modules/abstract.py — L0 directory abstract operations."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestRefreshAbstract:
    @patch("mem_agent.modules.abstract.call_deepseek", return_value="# Summary\nTest summary")
    def test_refresh_with_files(self, mock_llm):
        from mem_agent.modules.abstract import refresh_abstract

        engine = MagicMock()
        engine.list_resources.return_value = ["file1.md", "file2.md"]
        engine.read_resource.return_value = "Some content here"
        engine.config = {}

        result = refresh_abstract("viking://resources/logs/", engine)

        assert result == "# Summary\nTest summary"
        engine.write_resource.assert_called_once()
        assert engine.write_resource.call_args.kwargs["filename"] == ".abstract"

    def test_refresh_no_files(self):
        from mem_agent.modules.abstract import refresh_abstract

        engine = MagicMock()
        engine.list_resources.return_value = []

        result = refresh_abstract("viking://resources/logs/", engine)
        assert result == ""

    @patch("mem_agent.modules.abstract.call_deepseek", return_value="")
    def test_refresh_llm_failure_fallback(self, mock_llm):
        from mem_agent.modules.abstract import refresh_abstract

        engine = MagicMock()
        engine.list_resources.return_value = ["note1.md"]
        engine.read_resource.return_value = "content"
        engine.config = {}

        result = refresh_abstract("viking://resources/logs/", engine)

        # Should use fallback file listing
        assert "note1.md" in result

    def test_refresh_skips_dotfiles(self):
        from mem_agent.modules.abstract import refresh_abstract

        engine = MagicMock()
        engine.list_resources.return_value = [".abstract", "real.md"]
        engine.read_resource.return_value = "content"
        engine.config = {}

        with patch("mem_agent.modules.abstract.call_deepseek", return_value="summary"):
            refresh_abstract("viking://resources/logs/", engine)

        # Should only read real.md, not .abstract
        read_calls = engine.read_resource.call_args_list
        uris = [c.args[0] if c.args else c.kwargs.get("uri", "") for c in read_calls]
        assert "viking://resources/logs/.abstract" not in uris


class TestReadAbstract:
    def test_read_existing(self):
        from mem_agent.modules.abstract import read_abstract

        engine = MagicMock()
        engine.read_resource.return_value = "abstract content"

        result = read_abstract("viking://resources/logs/", engine)
        assert result == "abstract content"

    def test_read_missing(self):
        from mem_agent.modules.abstract import read_abstract

        engine = MagicMock()
        engine.read_resource.return_value = None

        result = read_abstract("viking://resources/logs/", engine)
        assert result is None


class TestAbstractRefresher:
    def test_schedule_marks_dirty(self):
        from mem_agent.modules.abstract import AbstractRefresher

        engine = MagicMock()
        refresher = AbstractRefresher(engine)

        refresher.schedule("viking://resources/logs/")
        assert "viking://resources/logs/" in refresher._dirty

    def test_schedule_dedup(self):
        from mem_agent.modules.abstract import AbstractRefresher

        engine = MagicMock()
        refresher = AbstractRefresher(engine)

        refresher.schedule("viking://resources/logs/")
        first_time = refresher._dirty["viking://resources/logs/"]

        refresher.schedule("viking://resources/logs/")
        # Should not update the timestamp
        assert refresher._dirty["viking://resources/logs/"] == first_time

    def test_start_stop(self):
        from mem_agent.modules.abstract import AbstractRefresher

        engine = MagicMock()
        refresher = AbstractRefresher(engine)

        refresher.start()
        assert refresher._thread is not None
        assert refresher._thread.is_alive()

        refresher.stop()
        refresher._thread.join(timeout=2)
