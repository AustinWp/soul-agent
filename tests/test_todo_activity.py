"""Tests for todo activity tracking extensions."""
from __future__ import annotations
from unittest.mock import MagicMock


class TestUpdateTodoActivity:
    def test_add_activity_to_existing_todo(self):
        from mem_agent.modules.todo import update_todo_activity
        engine = MagicMock()
        engine.list_resources.return_value = ["task-a1b2.md"]
        engine.read_resource.return_value = "---\nid: a1b2c3d4\nstatus: active\n---\nDo something"
        result = update_todo_activity("a1b2c3d4", "note", engine)
        assert result is True
        engine.write_resource.assert_called_once()

    def test_activity_not_found(self):
        from mem_agent.modules.todo import update_todo_activity
        engine = MagicMock()
        engine.list_resources.return_value = []
        result = update_todo_activity("nonexist", "note", engine)
        assert result is False


class TestGetStalledTodos:
    def test_stalled_todo_detected(self):
        from mem_agent.modules.todo import get_stalled_todos
        engine = MagicMock()
        engine.list_resources.return_value = ["task1.md"]
        engine.read_resource.return_value = "---\nid: a1b2c3d4\nstatus: active\nlast_activity: 2026-02-20\n---\nOld task"
        stalled = get_stalled_todos(engine, stale_days=3)
        assert len(stalled) == 1
        assert stalled[0]["id"] == "a1b2c3d4"

    def test_active_todo_not_stalled(self):
        from datetime import date
        from mem_agent.modules.todo import get_stalled_todos
        engine = MagicMock()
        engine.list_resources.return_value = ["task1.md"]
        today = date.today().isoformat()
        engine.read_resource.return_value = f"---\nid: a1b2c3d4\nstatus: active\nlast_activity: {today}\n---\nFresh task"
        stalled = get_stalled_todos(engine, stale_days=3)
        assert len(stalled) == 0
