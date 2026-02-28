"""Integration tests: verify all 7 data input sources produce vault writes."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from soul_agent.core.queue import IngestItem, IngestQueue
from soul_agent.modules.daily_log import LOGS_DIR, append_daily_log, clear_daily_log_cache


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def vault_engine():
    """Create a real VaultEngine backed by a temp directory."""
    from soul_agent.core.vault import VaultEngine

    with tempfile.TemporaryDirectory() as tmpdir:
        engine = VaultEngine.__new__(VaultEngine)
        engine._instance = None
        engine._config = {"vault_path": tmpdir, "llm": {"provider": "test"}}
        engine._vault_root = Path(tmpdir)
        engine._initialized = True
        engine._ensure_directories()
        clear_daily_log_cache()
        yield engine
        clear_daily_log_cache()


@pytest.fixture()
def ingest_queue():
    return IngestQueue(batch_size=10, flush_interval=0.5, dedup_window=60)


# ===========================================================================
# 1. Note — direct write to daily log
# ===========================================================================

class TestNoteSource:
    def test_note_writes_to_daily_log(self, vault_engine):
        """add_note() → engine.append_log() → logs/{date}.md exists."""
        with patch("soul_agent.modules.note.get_engine", return_value=vault_engine):
            from soul_agent.modules.note import add_note

            result = add_note("今天天气不错，适合写代码")
            assert result["status"] == "ok"

        today = date.today().isoformat()
        log_path = vault_engine.vault_root / LOGS_DIR / f"{today}.md"
        assert log_path.exists(), f"Daily log not created at {log_path}"
        content = log_path.read_text(encoding="utf-8")
        assert "今天天气不错" in content
        assert "(note)" in content

    def test_note_queued_when_queue_provided(self, vault_engine, ingest_queue):
        """add_note() with queue → item queued, NOT written to vault directly."""
        with patch("soul_agent.modules.note.get_engine", return_value=vault_engine):
            from soul_agent.modules.note import add_note

            result = add_note("queued note", ingest_queue=ingest_queue)
            assert result["status"] == "queued"
            assert ingest_queue.pending_count() == 1

        # Vault should NOT have a log yet (queue hasn't been processed)
        today = date.today().isoformat()
        log_path = vault_engine.vault_root / LOGS_DIR / f"{today}.md"
        assert not log_path.exists()


# ===========================================================================
# 2. Clipboard — polls pasteboard, writes to log or queue
# ===========================================================================

class TestClipboardSource:
    def test_clipboard_direct_write(self, vault_engine):
        """Clipboard without queue → engine.append_log()."""
        from soul_agent.modules.clipboard import _clipboard_loop, clip_stats

        running = threading.Event()
        running.set()

        call_count = 0
        original_text = "This is clipboard test content that is long enough to pass the minimum length filter"

        def fake_clipboard():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "initial"  # first call seeds hash
            if call_count <= 3:
                return original_text
            running.clear()  # stop after capture
            return original_text

        with (
            patch("soul_agent.modules.clipboard._get_clipboard_text", side_effect=fake_clipboard),
            patch("soul_agent.modules.clipboard._POLL_INTERVAL", 0.1),
        ):
            _clipboard_loop(vault_engine, running)

        today = date.today().isoformat()
        log_path = vault_engine.vault_root / LOGS_DIR / f"{today}.md"
        assert log_path.exists(), "Clipboard content not written to daily log"
        content = log_path.read_text(encoding="utf-8")
        assert "clipboard test content" in content
        assert "(clipboard)" in content

    def test_clipboard_queued(self, vault_engine, ingest_queue):
        """Clipboard with queue → IngestItem placed on queue."""
        from soul_agent.modules.clipboard import _clipboard_loop

        running = threading.Event()
        running.set()

        call_count = 0

        def fake_clipboard():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "seed"
            if call_count <= 3:
                return "Clipboard queued content with enough length to pass filter"
            running.clear()
            return "same"

        with (
            patch("soul_agent.modules.clipboard._get_clipboard_text", side_effect=fake_clipboard),
            patch("soul_agent.modules.clipboard._POLL_INTERVAL", 0.1),
        ):
            _clipboard_loop(vault_engine, running, ingest_queue=ingest_queue)

        assert ingest_queue.pending_count() >= 1, "Clipboard should have queued at least one item"


# ===========================================================================
# 3. Browser — reads SQLite history, pushes to queue
# ===========================================================================

class TestBrowserSource:
    def _create_fake_chrome_db(self, tmpdir: str) -> str:
        """Create a minimal Chrome History SQLite database for testing."""
        db_path = os.path.join(tmpdir, "History")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, title TEXT)")
        conn.execute("CREATE TABLE visits (id INTEGER PRIMARY KEY, url INTEGER, visit_time INTEGER)")

        # Chrome uses microseconds since 1601-01-01
        # Current time in Chrome epoch:
        from soul_agent.modules.browser import _CHROME_EPOCH_OFFSET

        chrome_now = int(time.time() * 1_000_000) + _CHROME_EPOCH_OFFSET
        conn.execute("INSERT INTO urls VALUES (1, 'https://example.com', 'Example Site')")
        conn.execute("INSERT INTO visits VALUES (1, 1, ?)", (chrome_now,))
        conn.commit()
        conn.close()
        return db_path

    def test_chrome_history_reads_entries(self):
        """read_chrome_history() → returns list of dicts with url/title/visit_time."""
        from soul_agent.modules.browser import read_chrome_history

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._create_fake_chrome_db(tmpdir)
            results = read_chrome_history(db_path=db_path, since_timestamp=0)
            assert len(results) >= 1
            assert results[0]["url"] == "https://example.com"
            assert results[0]["title"] == "Example Site"

    def test_browser_items_go_to_queue(self, ingest_queue):
        """Browser history entries → IngestItem on queue."""
        history = [{"url": "https://test.com", "title": "Test Page", "visit_time": time.time()}]

        from soul_agent.core.queue import IngestItem

        for item in history:
            text = f"Visited: {item['title']} — {item['url']}"
            ingest_queue.put(IngestItem(
                text=text,
                source="browser",
                timestamp=datetime.fromtimestamp(item["visit_time"], tz=timezone.utc),
                meta={"url": item["url"], "title": item["title"], "browser": "chrome"},
            ))

        assert ingest_queue.pending_count() == 1

    def test_browser_url_filtering(self):
        """Internal URLs (chrome://, etc.) should be skipped."""
        from soul_agent.modules.browser import _should_skip_url

        assert _should_skip_url("chrome://settings") is True
        assert _should_skip_url("chrome-extension://abc123") is True
        assert _should_skip_url("file:///tmp/test.html") is True
        assert _should_skip_url("https://example.com/doc.pdf") is True
        assert _should_skip_url("https://example.com") is False
        assert _should_skip_url("") is True


# ===========================================================================
# 4. Terminal — hook captures commands, flushes to service/log
# ===========================================================================

class TestTerminalSource:
    def test_hook_script_exists(self):
        """The zsh hook script file must exist."""
        from soul_agent.modules.terminal import HOOK_SCRIPT

        assert HOOK_SCRIPT.exists(), f"Hook script missing: {HOOK_SCRIPT}"

    def test_hook_marker_defined(self):
        from soul_agent.modules.terminal import HOOK_MARKER

        assert HOOK_MARKER
        assert "soul-agent" in HOOK_MARKER

    def test_terminal_data_reaches_daily_log(self, vault_engine):
        """Simulate terminal command being written to daily log."""
        append_daily_log("$ git status", "terminal", vault_engine)

        today = date.today().isoformat()
        log_path = vault_engine.vault_root / LOGS_DIR / f"{today}.md"
        assert log_path.exists()
        content = log_path.read_text(encoding="utf-8")
        assert "git status" in content
        assert "(terminal)" in content


# ===========================================================================
# 5. File watcher — monitors directories, pushes events to queue
# ===========================================================================

class TestFileWatcherSource:
    def test_file_handler_creates_ingest_items(self, ingest_queue):
        """_FileHandler.dispatch() → IngestItem on queue."""
        from soul_agent.modules.filewatcher import _FileHandler

        handler = _FileHandler(ingest_queue)

        # Simulate a file creation event
        event = MagicMock()
        event.is_directory = False
        event.event_type = "created"
        event.src_path = "/tmp/test_note.txt"

        with patch("soul_agent.modules.filewatcher._extract_preview", return_value="file preview content"):
            handler.dispatch(event)

        assert ingest_queue.pending_count() == 1

    def test_ignored_paths_filtered(self):
        """Ignored dirs/files/extensions are properly filtered."""
        from soul_agent.modules.filewatcher import _should_ignore

        assert _should_ignore("/project/.git/config") is True
        assert _should_ignore("/project/node_modules/pkg/index.js") is True
        assert _should_ignore("/tmp/.DS_Store") is True
        assert _should_ignore("/tmp/image.png") is True
        assert _should_ignore("/tmp/document.txt") is False

    def test_file_event_ignored_for_directory(self, ingest_queue):
        """Directory events should be ignored."""
        from soul_agent.modules.filewatcher import _FileHandler

        handler = _FileHandler(ingest_queue)
        event = MagicMock()
        event.is_directory = True
        event.event_type = "created"
        event.src_path = "/tmp/newdir"

        handler.dispatch(event)
        assert ingest_queue.pending_count() == 0


# ===========================================================================
# 6. Input method — captures keystrokes, batches to queue
# ===========================================================================

class TestInputMethodSource:
    def test_input_buffer_flushes_to_queue(self, ingest_queue):
        """InputBuffer accumulates text and flushes to IngestQueue."""
        from soul_agent.modules.input_hook import InputBuffer

        buf = InputBuffer(ingest_queue, min_length=5)
        buf.append("hello")
        buf.append(" world")

        assert buf.should_flush() is True
        buf.flush()
        assert ingest_queue.pending_count() == 1

    def test_input_buffer_discards_short_text(self, ingest_queue):
        """Short accumulated text (<min_length) is discarded on flush."""
        from soul_agent.modules.input_hook import InputBuffer

        buf = InputBuffer(ingest_queue, min_length=20)
        buf.append("hi")
        buf.flush()
        assert ingest_queue.pending_count() == 0

    def test_hook_status_initial(self):
        """Hook status should have expected keys."""
        from soul_agent.modules.input_hook import hook_status

        status = hook_status()
        assert "active" in status
        assert "keystrokes" in status
        assert "flushes" in status

    def test_dedicated_apps_defined(self):
        """DEDICATED_APPS should include terminal emulators and IDEs."""
        from soul_agent.modules.input_hook import DEDICATED_APPS

        assert "com.apple.Terminal" in DEDICATED_APPS
        assert "com.microsoft.VSCode" in DEDICATED_APPS


# ===========================================================================
# 7. Claude Code — hook config and settings management
# ===========================================================================

class TestClaudeCodeSource:
    def test_hook_config_structure(self):
        """build_hook_config() returns valid hooks dict."""
        from soul_agent.modules.claude_code import build_hook_config

        config = build_hook_config()
        assert "hooks" in config
        assert "postToolUse" in config["hooks"]

        groups = config["hooks"]["postToolUse"]
        assert len(groups) >= 1
        assert groups[0]["matcher"] == ".*"
        assert len(groups[0]["hooks"]) >= 1
        assert groups[0]["hooks"][0]["type"] == "command"

    def test_install_creates_settings(self):
        """install_hook() creates settings.json with hook config."""
        from soul_agent.modules.claude_code import HOOK_MARKER, install_hook

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_settings = Path(tmpdir) / "settings.json"
            with patch("soul_agent.modules.claude_code.CLAUDE_SETTINGS", fake_settings):
                install_hook()

            assert fake_settings.exists()
            import json

            data = json.loads(fake_settings.read_text())
            assert "hooks" in data
            # Verify marker is present
            found = False
            for group in data["hooks"]["postToolUse"]:
                for hook in group.get("hooks", []):
                    if hook.get("description") == HOOK_MARKER:
                        found = True
            assert found, "Hook marker not found in installed settings"

    def test_install_idempotent(self):
        """Installing twice doesn't duplicate the hook."""
        from soul_agent.modules.claude_code import install_hook

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_settings = Path(tmpdir) / "settings.json"
            with patch("soul_agent.modules.claude_code.CLAUDE_SETTINGS", fake_settings):
                install_hook()
                install_hook()  # second call

            import json

            data = json.loads(fake_settings.read_text())
            groups = data["hooks"]["postToolUse"]
            assert len(groups) == 1, "Hook should not be duplicated"

    def test_uninstall_removes_hook(self):
        """uninstall_hook() removes the soul-agent hook."""
        from soul_agent.modules.claude_code import install_hook, uninstall_hook

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_settings = Path(tmpdir) / "settings.json"
            with patch("soul_agent.modules.claude_code.CLAUDE_SETTINGS", fake_settings):
                install_hook()
                uninstall_hook()

            import json

            data = json.loads(fake_settings.read_text())
            groups = data["hooks"]["postToolUse"]
            # All groups containing our hook should be removed
            for group in groups:
                for hook in group.get("hooks", []):
                    assert hook.get("description") != "soul-agent-claude-code-hook"


# ===========================================================================
# End-to-end: Source → IngestQueue → Pipeline → Daily Log → Vault File
# ===========================================================================

class TestEndToEndPipeline:
    @patch("soul_agent.modules.pipeline.classify_batch")
    def test_note_through_pipeline_to_vault(self, mock_classify, vault_engine, ingest_queue):
        """note → queue → pipeline → daily_log → vault file."""
        from soul_agent.core.queue import ClassifiedItem
        from soul_agent.modules.pipeline import process_batch

        ts = datetime.now()
        item = IngestItem(text="学习了 Python 装饰器", source="note", timestamp=ts, meta={})

        classified = ClassifiedItem(
            text="学习了 Python 装饰器", source="note", timestamp=ts, meta={},
            category="learning", tags=["python"], importance=4,
            summary="learned decorators", action_type=None, action_detail=None, related_todo_id=None,
        )
        mock_classify.return_value = [classified]

        process_batch([item], vault_engine)

        today = date.today().isoformat()
        log_path = vault_engine.vault_root / LOGS_DIR / f"{today}.md"
        assert log_path.exists()
        content = log_path.read_text(encoding="utf-8")
        assert "Python 装饰器" in content
        assert "(note)" in content
        assert "[learning]" in content

    @patch("soul_agent.modules.pipeline.classify_batch")
    def test_clipboard_through_pipeline(self, mock_classify, vault_engine):
        """clipboard → pipeline → daily_log."""
        from soul_agent.core.queue import ClassifiedItem
        from soul_agent.modules.pipeline import process_batch

        ts = datetime.now()
        item = IngestItem(text="Copied code snippet: def hello()", source="clipboard", timestamp=ts, meta={})

        classified = ClassifiedItem(
            text="Copied code snippet: def hello()", source="clipboard", timestamp=ts, meta={},
            category="code", tags=["python", "snippet"], importance=2,
            summary="code snippet", action_type=None, action_detail=None, related_todo_id=None,
        )
        mock_classify.return_value = [classified]

        process_batch([item], vault_engine)

        today = date.today().isoformat()
        log_path = vault_engine.vault_root / LOGS_DIR / f"{today}.md"
        content = log_path.read_text(encoding="utf-8")
        assert "(clipboard)" in content
        assert "def hello()" in content

    @patch("soul_agent.modules.pipeline.classify_batch")
    def test_browser_through_pipeline(self, mock_classify, vault_engine):
        """browser → pipeline → daily_log."""
        from soul_agent.core.queue import ClassifiedItem
        from soul_agent.modules.pipeline import process_batch

        ts = datetime.now()
        item = IngestItem(
            text="Visited: Python Docs — https://docs.python.org",
            source="browser", timestamp=ts,
            meta={"url": "https://docs.python.org", "browser": "chrome"},
        )

        classified = ClassifiedItem(
            text="Visited: Python Docs — https://docs.python.org",
            source="browser", timestamp=ts, meta=item.meta,
            category="learning", tags=["python", "docs"], importance=3,
            summary="visited python docs", action_type=None, action_detail=None, related_todo_id=None,
        )
        mock_classify.return_value = [classified]

        process_batch([item], vault_engine)

        today = date.today().isoformat()
        log_path = vault_engine.vault_root / LOGS_DIR / f"{today}.md"
        content = log_path.read_text(encoding="utf-8")
        assert "(browser)" in content
        assert "docs.python.org" in content

    @patch("soul_agent.modules.pipeline.classify_batch")
    def test_file_through_pipeline(self, mock_classify, vault_engine):
        """file watcher → pipeline → daily_log."""
        from soul_agent.core.queue import ClassifiedItem
        from soul_agent.modules.pipeline import process_batch

        ts = datetime.now()
        item = IngestItem(
            text="File created: report.md\n---\n# Monthly Report",
            source="file", timestamp=ts,
            meta={"path": "/Users/austin/Desktop/report.md", "event_type": "created"},
        )

        classified = ClassifiedItem(
            text=item.text, source="file", timestamp=ts, meta=item.meta,
            category="work", tags=["report"], importance=3,
            summary="new report file", action_type=None, action_detail=None, related_todo_id=None,
        )
        mock_classify.return_value = [classified]

        process_batch([item], vault_engine)

        today = date.today().isoformat()
        log_path = vault_engine.vault_root / LOGS_DIR / f"{today}.md"
        content = log_path.read_text(encoding="utf-8")
        assert "(file)" in content
        assert "report.md" in content

    @patch("soul_agent.modules.pipeline.classify_batch")
    def test_input_method_through_pipeline(self, mock_classify, vault_engine):
        """input-method → pipeline → daily_log."""
        from soul_agent.core.queue import ClassifiedItem
        from soul_agent.modules.pipeline import process_batch

        ts = datetime.now()
        item = IngestItem(text="Typed text: 明天下午开会讨论方案", source="input-method", timestamp=ts, meta={})

        classified = ClassifiedItem(
            text=item.text, source="input-method", timestamp=ts, meta={},
            category="work", tags=["meeting"], importance=3,
            summary="meeting discussion", action_type=None, action_detail=None, related_todo_id=None,
        )
        mock_classify.return_value = [classified]

        process_batch([item], vault_engine)

        today = date.today().isoformat()
        log_path = vault_engine.vault_root / LOGS_DIR / f"{today}.md"
        content = log_path.read_text(encoding="utf-8")
        assert "(input-method)" in content
        assert "开会讨论" in content

    @patch("soul_agent.modules.pipeline.classify_batch")
    def test_pipeline_creates_todo_on_new_task(self, mock_classify, vault_engine):
        """Pipeline with action_type=new_task → creates a todo file."""
        from soul_agent.core.queue import ClassifiedItem
        from soul_agent.modules.pipeline import process_batch

        ts = datetime.now()
        item = IngestItem(text="需要写周报", source="note", timestamp=ts, meta={})

        classified = ClassifiedItem(
            text="需要写周报", source="note", timestamp=ts, meta={},
            category="work", tags=["report"], importance=4,
            summary="write weekly report", action_type="new_task",
            action_detail="写本周周报", related_todo_id=None,
        )
        mock_classify.return_value = [classified]

        process_batch([item], vault_engine)

        # Check that a todo was created
        todos = vault_engine.list_resources("todos/active")
        assert len(todos) >= 1, "Pipeline should have created a todo"

    @patch("soul_agent.modules.pipeline.classify_batch")
    def test_multi_source_daily_log_accumulation(self, mock_classify, vault_engine):
        """Multiple sources write to the same daily log file."""
        from soul_agent.core.queue import ClassifiedItem
        from soul_agent.modules.pipeline import process_batch

        ts = datetime.now()
        items_data = [
            ("Morning standup notes", "note", "work"),
            ("Copied API key docs", "clipboard", "code"),
            ("Visited: GitHub — https://github.com", "browser", "code"),
        ]

        for text, source, category in items_data:
            item = IngestItem(text=text, source=source, timestamp=ts, meta={})
            classified = ClassifiedItem(
                text=text, source=source, timestamp=ts, meta={},
                category=category, tags=[], importance=3,
                summary=text[:20], action_type=None, action_detail=None, related_todo_id=None,
            )
            mock_classify.return_value = [classified]
            process_batch([item], vault_engine)

        today = date.today().isoformat()
        log_path = vault_engine.vault_root / LOGS_DIR / f"{today}.md"
        content = log_path.read_text(encoding="utf-8")

        # All three sources should appear in the same log file
        assert "(note)" in content
        assert "(clipboard)" in content
        assert "(browser)" in content
        assert "standup" in content
        assert "API key" in content
        assert "github.com" in content


# ===========================================================================
# Queue dedup & batching
# ===========================================================================

class TestQueueMechanics:
    def test_dedup_rejects_identical_text(self, ingest_queue):
        """Same text within dedup_window is rejected."""
        ts = datetime.now()
        item1 = IngestItem(text="duplicate text", source="note", timestamp=ts, meta={})
        item2 = IngestItem(text="duplicate text", source="clipboard", timestamp=ts, meta={})

        assert ingest_queue.put(item1) is True
        assert ingest_queue.put(item2) is False
        assert ingest_queue.pending_count() == 1

    def test_different_text_accepted(self, ingest_queue):
        """Different text should be accepted."""
        ts = datetime.now()
        item1 = IngestItem(text="text one", source="note", timestamp=ts, meta={})
        item2 = IngestItem(text="text two", source="note", timestamp=ts, meta={})

        assert ingest_queue.put(item1) is True
        assert ingest_queue.put(item2) is True
        assert ingest_queue.pending_count() == 2

    def test_batch_retrieval(self, ingest_queue):
        """get_batch() returns all pending items."""
        ts = datetime.now()
        for i in range(3):
            ingest_queue.put(IngestItem(text=f"item {i}", source="note", timestamp=ts, meta={}))

        batch = ingest_queue.get_batch(timeout=1)
        assert len(batch) == 3
