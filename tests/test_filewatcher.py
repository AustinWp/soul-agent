"""Tests for modules/filewatcher.py — file watcher adapter."""
from __future__ import annotations

import os
import tempfile


class TestShouldIgnore:
    def test_ignore_git_dir(self):
        from soul_agent.modules.filewatcher import _should_ignore

        assert _should_ignore("/home/user/project/.git/config") is True

    def test_ignore_node_modules(self):
        from soul_agent.modules.filewatcher import _should_ignore

        assert _should_ignore("/home/user/project/node_modules/pkg/index.js") is True

    def test_ignore_ds_store(self):
        from soul_agent.modules.filewatcher import _should_ignore

        assert _should_ignore("/home/user/Desktop/.DS_Store") is True

    def test_ignore_binary_extension(self):
        from soul_agent.modules.filewatcher import _should_ignore

        assert _should_ignore("/home/user/photos/image.png") is True
        assert _should_ignore("/home/user/files/archive.zip") is True
        assert _should_ignore("/home/user/music/song.mp3") is True

    def test_allow_normal_text_file(self):
        from soul_agent.modules.filewatcher import _should_ignore

        assert _should_ignore("/home/user/project/readme.txt") is False

    def test_allow_python_file(self):
        from soul_agent.modules.filewatcher import _should_ignore

        assert _should_ignore("/home/user/project/main.py") is False

    def test_allow_markdown_file(self):
        from soul_agent.modules.filewatcher import _should_ignore

        assert _should_ignore("/home/user/notes/todo.md") is False

    def test_ignore_pycache(self):
        from soul_agent.modules.filewatcher import _should_ignore

        assert _should_ignore("/home/user/project/__pycache__/module.cpython-312.pyc") is True

    def test_ignore_hidden_files(self):
        from soul_agent.modules.filewatcher import _should_ignore

        assert _should_ignore("/home/user/.hidden_file") is True

    def test_ignore_venv(self):
        from soul_agent.modules.filewatcher import _should_ignore

        assert _should_ignore("/home/user/project/.venv/lib/python3.12/site.py") is True


class TestExtractPreview:
    def test_extract_preview_basic(self):
        from soul_agent.modules.filewatcher import _extract_preview

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Hello, this is a test file with some content.")
            path = f.name

        try:
            preview = _extract_preview(path)
            assert preview == "Hello, this is a test file with some content."
        finally:
            os.unlink(path)

    def test_extract_preview_truncates(self):
        from soul_agent.modules.filewatcher import _extract_preview

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("A" * 1000)
            path = f.name

        try:
            preview = _extract_preview(path, max_chars=100)
            assert len(preview) == 100
            assert preview == "A" * 100
        finally:
            os.unlink(path)

    def test_extract_preview_missing_file(self):
        from soul_agent.modules.filewatcher import _extract_preview

        result = _extract_preview("/tmp/nonexistent_file_99999.txt")
        assert result == ""

    def test_extract_preview_empty_file(self):
        from soul_agent.modules.filewatcher import _extract_preview

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            path = f.name

        try:
            preview = _extract_preview(path)
            assert preview == ""
        finally:
            os.unlink(path)


class TestFileHandler:
    def test_handler_ignores_directories(self):
        from unittest.mock import MagicMock

        from soul_agent.modules.filewatcher import _FileHandler

        queue = MagicMock()
        handler = _FileHandler(queue)

        event = MagicMock()
        event.is_directory = True
        event.src_path = "/home/user/project"

        handler.dispatch(event)
        queue.put.assert_not_called()

    def test_handler_ignores_ignored_files(self):
        from unittest.mock import MagicMock

        from soul_agent.modules.filewatcher import _FileHandler

        queue = MagicMock()
        handler = _FileHandler(queue)

        event = MagicMock()
        event.is_directory = False
        event.src_path = "/home/user/.DS_Store"
        event.event_type = "modified"

        handler.dispatch(event)
        queue.put.assert_not_called()

    def test_handler_processes_valid_file(self):
        from unittest.mock import MagicMock

        from soul_agent.modules.filewatcher import _FileHandler

        queue = MagicMock()
        handler = _FileHandler(queue)

        # Create a real temp file so _extract_preview can read it
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("print('hello')")
            path = f.name

        try:
            event = MagicMock()
            event.is_directory = False
            event.src_path = path
            event.event_type = "created"

            handler.dispatch(event)
            queue.put.assert_called_once()

            item = queue.put.call_args[0][0]
            assert item.source == "file"
            assert "created" in item.text
            assert item.meta["event_type"] == "created"
        finally:
            os.unlink(path)
