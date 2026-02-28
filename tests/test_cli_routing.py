"""Tests for CLI-to-HTTP routing when service is running."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from soul_agent.cli import app

runner = CliRunner()


# ── Service detection ────────────────────────────────────────────────────────

class TestServiceDetection:
    def test_service_running_returns_true(self):
        from soul_agent.cli import _service_is_running

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("soul_agent.cli.httpx.get", return_value=mock_resp) as mock_get:
            assert _service_is_running() is True
            mock_get.assert_called_once()

    def test_service_not_running_returns_false(self):
        from soul_agent.cli import _service_is_running

        with patch("soul_agent.cli.httpx.get", side_effect=Exception("connection refused")):
            assert _service_is_running() is False

    def test_service_bad_status_returns_false(self):
        from soul_agent.cli import _service_is_running

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        with patch("soul_agent.cli.httpx.get", return_value=mock_resp):
            assert _service_is_running() is False

    def test_api_url_builds_correctly(self):
        from soul_agent.cli import _api_url

        assert _api_url("/health") == "http://127.0.0.1:8330/health"
        assert _api_url("/todo/list") == "http://127.0.0.1:8330/todo/list"


# ── Note routing ─────────────────────────────────────────────────────────────

class TestNoteRouting:
    @patch("soul_agent.cli._service_is_running", return_value=True)
    def test_note_routes_to_http(self, mock_svc):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "ok"}
        with patch("soul_agent.cli.httpx.post", return_value=mock_resp) as mock_post:
            result = runner.invoke(app, ["note", "test note"])
            assert result.exit_code == 0
            assert "via service" in result.output
            mock_post.assert_called_once()

    @patch("soul_agent.cli._service_is_running", return_value=False)
    @patch("soul_agent.cli._init_engine")
    @patch("soul_agent.modules.note.add_note")
    def test_note_falls_back_to_local(self, mock_add, mock_init, mock_svc):
        result = runner.invoke(app, ["note", "test note"])
        assert result.exit_code == 0
        mock_init.assert_called_once()
        mock_add.assert_called_once_with("test note")


# ── Todo routing ─────────────────────────────────────────────────────────────

class TestTodoRouting:
    @patch("soul_agent.cli._service_is_running", return_value=True)
    def test_todo_add_routes_to_http(self, mock_svc):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "ok", "todo_id": "abc12345"}
        with patch("soul_agent.cli.httpx.post", return_value=mock_resp) as mock_post:
            result = runner.invoke(app, ["todo", "add", "buy milk"])
            assert result.exit_code == 0
            assert "abc12345" in result.output
            mock_post.assert_called_once()

    @patch("soul_agent.cli._service_is_running", return_value=True)
    def test_todo_ls_routes_to_http(self, mock_svc):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "ok",
            "todos": [
                {"id": "abc1", "text": "buy milk", "due": "2026-03-01", "priority": "normal"},
                {"id": "def2", "text": "write tests", "due": "", "priority": "high"},
            ],
        }
        with patch("soul_agent.cli.httpx.get", return_value=mock_resp):
            result = runner.invoke(app, ["todo", "ls"])
            assert result.exit_code == 0
            assert "buy milk" in result.output
            assert "write tests" in result.output

    @patch("soul_agent.cli._service_is_running", return_value=True)
    def test_todo_ls_empty(self, mock_svc):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "ok", "todos": []}
        with patch("soul_agent.cli.httpx.get", return_value=mock_resp):
            result = runner.invoke(app, ["todo", "ls"])
            assert result.exit_code == 0
            assert "No active todos" in result.output

    @patch("soul_agent.cli._service_is_running", return_value=True)
    def test_todo_done_routes_to_http(self, mock_svc):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "ok", "success": True}
        with patch("soul_agent.cli.httpx.post", return_value=mock_resp):
            result = runner.invoke(app, ["todo", "done", "abc1"])
            assert result.exit_code == 0
            assert "marked as done" in result.output

    @patch("soul_agent.cli._service_is_running", return_value=True)
    def test_todo_done_not_found(self, mock_svc):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "ok", "success": False}
        with patch("soul_agent.cli.httpx.post", return_value=mock_resp):
            result = runner.invoke(app, ["todo", "done", "xyz9"])
            assert result.exit_code == 0
            assert "not found" in result.output

    @patch("soul_agent.cli._service_is_running", return_value=True)
    def test_todo_rm_routes_to_http(self, mock_svc):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "ok", "success": True}
        with patch("soul_agent.cli.httpx.post", return_value=mock_resp):
            result = runner.invoke(app, ["todo", "rm", "abc1"])
            assert result.exit_code == 0
            assert "deleted" in result.output


# ── Search routing ───────────────────────────────────────────────────────────

class TestSearchRouting:
    @patch("soul_agent.cli._service_is_running", return_value=True)
    def test_search_routes_to_http(self, mock_svc):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "results": [
                {"path": "logs/2026-02-28.md", "snippet": "test snippet", "filename": "2026-02-28.md"},
            ]
        }
        with patch("soul_agent.cli.httpx.get", return_value=mock_resp):
            result = runner.invoke(app, ["search", "test query"])
            assert result.exit_code == 0
            assert "1 results" in result.output

    @patch("soul_agent.cli._service_is_running", return_value=True)
    def test_search_no_results(self, mock_svc):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"results": []}
        with patch("soul_agent.cli.httpx.get", return_value=mock_resp):
            result = runner.invoke(app, ["search", "nothing"])
            assert result.exit_code == 0
            assert "No results found" in result.output


# ── Recall routing ───────────────────────────────────────────────────────────

class TestRecallRouting:
    @patch("soul_agent.cli._service_is_running", return_value=True)
    def test_recall_today_routes_to_http(self, mock_svc):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "ok",
            "data": {"date": "2026-02-26", "memories": ["did something"], "todos": []},
        }
        with patch("soul_agent.cli.httpx.get", return_value=mock_resp):
            result = runner.invoke(app, ["recall"])
            assert result.exit_code == 0
            assert "Daily Recall" in result.output

    @patch("soul_agent.cli._service_is_running", return_value=True)
    def test_recall_week_routes_to_http(self, mock_svc):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "ok",
            "data": {"week_start": "2026-02-23", "items": ["weekly item"]},
        }
        with patch("soul_agent.cli.httpx.get", return_value=mock_resp):
            result = runner.invoke(app, ["recall", "--week"])
            assert result.exit_code == 0
            assert "Weekly Recall" in result.output


# ── Compact routing ──────────────────────────────────────────────────────────

class TestCompactRouting:
    @patch("soul_agent.cli._service_is_running", return_value=True)
    def test_compact_routes_to_http(self, mock_svc):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "ok", "report": "# Weekly summary\nAll good.", "report_length": 30}
        with patch("soul_agent.cli.httpx.post", return_value=mock_resp):
            result = runner.invoke(app, ["compact"])
            assert result.exit_code == 0
            assert "via service" in result.output


# ── Core routing ─────────────────────────────────────────────────────────────

class TestCoreRouting:
    @patch("soul_agent.cli._service_is_running", return_value=True)
    def test_core_show_routes_to_http(self, mock_svc):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "ok", "content": "# My Memory\nSome content"}
        with patch("soul_agent.cli.httpx.get", return_value=mock_resp):
            result = runner.invoke(app, ["core", "show"])
            assert result.exit_code == 0
            assert "My Memory" in result.output

    @patch("soul_agent.cli._service_is_running", return_value=True)
    def test_core_show_empty(self, mock_svc):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "ok", "content": ""}
        with patch("soul_agent.cli.httpx.get", return_value=mock_resp):
            result = runner.invoke(app, ["core", "show"])
            assert result.exit_code == 0
            assert "No permanent memory" in result.output


# ── Insight routing ──────────────────────────────────────────────────────────

class TestInsightRouting:
    @patch("soul_agent.cli._service_is_running", return_value=True)
    def test_insight_today_routes_to_http(self, mock_svc):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"date": "2026-02-26", "report": "Today was productive."}
        with patch("soul_agent.cli.httpx.get", return_value=mock_resp):
            result = runner.invoke(app, ["insight", "today"])
            assert result.exit_code == 0
            assert "productive" in result.output

    @patch("soul_agent.cli._service_is_running", return_value=True)
    def test_insight_suggest_routes_to_http(self, mock_svc):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"suggestions": "\u5de5\u4f5c\u5efa\u8bae: focus on tests"}
        with patch("soul_agent.cli.httpx.get", return_value=mock_resp):
            result = runner.invoke(app, ["insight", "suggest"])
            assert result.exit_code == 0
            assert "focus on tests" in result.output
