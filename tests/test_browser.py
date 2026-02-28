"""Tests for modules/browser.py — browser history adapter."""
from __future__ import annotations

import os
import sqlite3
import tempfile


class TestShouldSkipUrl:
    def test_skip_chrome_internal(self):
        from soul_agent.modules.browser import _should_skip_url

        assert _should_skip_url("chrome://settings") is True

    def test_skip_chrome_extension(self):
        from soul_agent.modules.browser import _should_skip_url

        assert _should_skip_url("chrome-extension://abc/popup.html") is True

    def test_skip_about_blank(self):
        from soul_agent.modules.browser import _should_skip_url

        assert _should_skip_url("about:blank") is True

    def test_allow_https(self):
        from soul_agent.modules.browser import _should_skip_url

        assert _should_skip_url("https://example.com") is False

    def test_allow_http(self):
        from soul_agent.modules.browser import _should_skip_url

        assert _should_skip_url("http://example.com/page") is False

    def test_skip_empty_url(self):
        from soul_agent.modules.browser import _should_skip_url

        assert _should_skip_url("") is True

    def test_skip_binary_extension(self):
        from soul_agent.modules.browser import _should_skip_url

        assert _should_skip_url("https://example.com/file.pdf") is True
        assert _should_skip_url("https://example.com/image.png") is True
        assert _should_skip_url("https://example.com/archive.zip") is True

    def test_allow_html_extension(self):
        from soul_agent.modules.browser import _should_skip_url

        assert _should_skip_url("https://example.com/page.html") is False

    def test_skip_data_url(self):
        from soul_agent.modules.browser import _should_skip_url

        assert _should_skip_url("data:text/html,<h1>test</h1>") is True

    def test_skip_devtools(self):
        from soul_agent.modules.browser import _should_skip_url

        assert _should_skip_url("devtools://devtools/bundled/inspector.html") is True


class TestCopyDb:
    def test_copy_existing_db(self):
        from soul_agent.modules.browser import _copy_db

        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            f.write(b"test data")
            src = f.name

        try:
            result = _copy_db(src)
            assert result is not None
            assert os.path.exists(result)
            with open(result, "rb") as f:
                assert f.read() == b"test data"
            os.unlink(result)
        finally:
            os.unlink(src)

    def test_copy_nonexistent_db(self):
        from soul_agent.modules.browser import _copy_db

        result = _copy_db("/tmp/nonexistent_browser_db_12345.sqlite")
        assert result is None


class TestReadChromeHistory:
    def _create_chrome_db(self) -> str:
        """Create a temp SQLite DB with Chrome schema and a test row."""
        tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        tmp.close()
        conn = sqlite3.connect(tmp.name)
        conn.execute("""
            CREATE TABLE urls (
                id INTEGER PRIMARY KEY,
                url TEXT NOT NULL,
                title TEXT DEFAULT '',
                visit_count INTEGER DEFAULT 0,
                typed_count INTEGER DEFAULT 0,
                last_visit_time INTEGER DEFAULT 0,
                hidden INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE visits (
                id INTEGER PRIMARY KEY,
                url INTEGER NOT NULL,
                visit_time INTEGER NOT NULL,
                from_visit INTEGER DEFAULT 0,
                transition INTEGER DEFAULT 0,
                segment_id INTEGER DEFAULT 0,
                visit_duration INTEGER DEFAULT 0
            )
        """)
        # Insert a URL: Chrome epoch for 2026-01-15 12:00:00 UTC
        # Unix timestamp for 2026-01-15 12:00:00 UTC = 1768478400
        # Chrome timestamp = (1768478400 * 1000000) + 11644473600000000
        chrome_ts = (1768478400 * 1_000_000) + 11_644_473_600_000_000
        conn.execute(
            "INSERT INTO urls (id, url, title) VALUES (1, 'https://example.com/page', 'Example Page')"
        )
        conn.execute(
            "INSERT INTO visits (id, url, visit_time) VALUES (1, 1, ?)",
            (chrome_ts,),
        )
        # Insert a chrome:// URL that should be filtered
        conn.execute(
            "INSERT INTO urls (id, url, title) VALUES (2, 'chrome://settings', 'Settings')"
        )
        conn.execute(
            "INSERT INTO visits (id, url, visit_time) VALUES (2, 2, ?)",
            (chrome_ts + 1000,),
        )
        conn.commit()
        conn.close()
        return tmp.name

    def test_read_chrome_history_basic(self):
        from soul_agent.modules.browser import read_chrome_history

        db_path = self._create_chrome_db()
        try:
            results = read_chrome_history(db_path=db_path, since_timestamp=0)
            assert len(results) == 1
            assert results[0]["url"] == "https://example.com/page"
            assert results[0]["title"] == "Example Page"
            assert isinstance(results[0]["visit_time"], float)
        finally:
            os.unlink(db_path)

    def test_read_chrome_history_filters_internal(self):
        from soul_agent.modules.browser import read_chrome_history

        db_path = self._create_chrome_db()
        try:
            results = read_chrome_history(db_path=db_path, since_timestamp=0)
            urls = [r["url"] for r in results]
            assert "chrome://settings" not in urls
        finally:
            os.unlink(db_path)

    def test_read_chrome_history_since_filter(self):
        from soul_agent.modules.browser import read_chrome_history

        db_path = self._create_chrome_db()
        try:
            # Use a timestamp after the test visit → should get nothing
            future_ts = 1768478400 + 3600  # one hour after the test visit
            results = read_chrome_history(db_path=db_path, since_timestamp=future_ts)
            assert len(results) == 0
        finally:
            os.unlink(db_path)

    def test_read_chrome_history_missing_db(self):
        from soul_agent.modules.browser import read_chrome_history

        results = read_chrome_history(db_path="/tmp/nonexistent_chrome_db_99999.sqlite")
        assert results == []


class TestReadSafariHistory:
    def _create_safari_db(self) -> str:
        """Create a temp SQLite DB with Safari schema and a test row."""
        tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        tmp.close()
        conn = sqlite3.connect(tmp.name)
        conn.execute("""
            CREATE TABLE history_items (
                id INTEGER PRIMARY KEY,
                url TEXT NOT NULL,
                domain_expansion TEXT,
                visit_count INTEGER DEFAULT 0,
                daily_visit_counts BLOB,
                weekly_visit_counts BLOB,
                autocomplete_triggers BLOB,
                should_recompute_derived_visit_counts INTEGER DEFAULT 0,
                visit_count_score INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE history_visits (
                id INTEGER PRIMARY KEY,
                history_item INTEGER NOT NULL,
                visit_time REAL NOT NULL,
                title TEXT DEFAULT '',
                http_non_get INTEGER DEFAULT 0,
                redirect_source INTEGER,
                redirect_destination INTEGER,
                origin INTEGER DEFAULT 0,
                generation INTEGER DEFAULT 0,
                attributes INTEGER DEFAULT 0,
                score INTEGER DEFAULT 0
            )
        """)
        # Safari epoch: seconds since 2001-01-01
        # For 2026-01-15 12:00:00 UTC: unix=1768478400, safari=1768478400-978307200=790171200
        safari_ts = 1768478400 - 978_307_200
        conn.execute(
            "INSERT INTO history_items (id, url) VALUES (1, 'https://apple.com/safari')"
        )
        conn.execute(
            "INSERT INTO history_visits (id, history_item, visit_time, title) VALUES (1, 1, ?, 'Safari Page')",
            (safari_ts,),
        )
        conn.commit()
        conn.close()
        return tmp.name

    def test_read_safari_history_basic(self):
        from soul_agent.modules.browser import read_safari_history

        db_path = self._create_safari_db()
        try:
            results = read_safari_history(db_path=db_path, since_timestamp=0)
            assert len(results) == 1
            assert results[0]["url"] == "https://apple.com/safari"
            assert results[0]["title"] == "Safari Page"
        finally:
            os.unlink(db_path)

    def test_read_safari_history_missing_db(self):
        from soul_agent.modules.browser import read_safari_history

        results = read_safari_history(db_path="/tmp/nonexistent_safari_db_99999.sqlite")
        assert results == []


class TestBinaryExtensionFilter:
    def test_binary_pdf_filtered(self):
        from soul_agent.modules.browser import _should_skip_url

        assert _should_skip_url("https://example.com/document.pdf") is True

    def test_binary_jpg_filtered(self):
        from soul_agent.modules.browser import _should_skip_url

        assert _should_skip_url("https://cdn.example.com/photo.jpg") is True

    def test_binary_exe_filtered(self):
        from soul_agent.modules.browser import _should_skip_url

        assert _should_skip_url("https://download.example.com/setup.exe") is True

    def test_binary_with_query_params(self):
        from soul_agent.modules.browser import _should_skip_url

        assert _should_skip_url("https://example.com/file.zip?v=2") is True

    def test_non_binary_passes(self):
        from soul_agent.modules.browser import _should_skip_url

        assert _should_skip_url("https://example.com/article") is False
        assert _should_skip_url("https://example.com/page.html") is False
