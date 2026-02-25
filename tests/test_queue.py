"""Tests for core/queue.py — IngestItem, ClassifiedItem, and IngestQueue."""

from __future__ import annotations

import pytest


class TestIngestItem:
    def test_create_basic(self):
        from datetime import datetime

        from mem_agent.core.queue import IngestItem

        ts = datetime(2026, 1, 15, 10, 30, 0)
        item = IngestItem(text="hello world", source="note", timestamp=ts)
        assert item.text == "hello world"
        assert item.source == "note"
        assert item.timestamp == ts
        assert item.meta == {}

    def test_create_with_meta(self):
        from datetime import datetime

        from mem_agent.core.queue import IngestItem

        ts = datetime(2026, 1, 15, 10, 30, 0)
        item = IngestItem(
            text="clipboard data",
            source="clipboard",
            timestamp=ts,
            meta={"app": "Safari", "url": "https://example.com"},
        )
        assert item.meta["app"] == "Safari"
        assert item.meta["url"] == "https://example.com"


class TestClassifiedItem:
    def test_create_all_fields(self):
        from datetime import datetime

        from mem_agent.core.queue import ClassifiedItem

        ts = datetime(2026, 2, 1, 8, 0, 0)
        item = ClassifiedItem(
            text="buy groceries",
            source="input-method",
            timestamp=ts,
            meta={"lang": "en"},
            category="task",
            tags=["errands", "personal"],
            importance=5,
            summary="Need to buy groceries",
            action_type="todo",
            action_detail="Add to shopping list",
            related_todo_id="todo-42",
        )
        assert item.text == "buy groceries"
        assert item.source == "input-method"
        assert item.timestamp == ts
        assert item.meta == {"lang": "en"}
        assert item.category == "task"
        assert item.tags == ["errands", "personal"]
        assert item.importance == 5
        assert item.summary == "Need to buy groceries"
        assert item.action_type == "todo"
        assert item.action_detail == "Add to shopping list"
        assert item.related_todo_id == "todo-42"

    def test_create_no_action(self):
        from datetime import datetime

        from mem_agent.core.queue import ClassifiedItem

        ts = datetime(2026, 2, 1, 9, 0, 0)
        item = ClassifiedItem(
            text="interesting article about AI",
            source="browser",
            timestamp=ts,
        )
        assert item.category == ""
        assert item.tags == []
        assert item.importance == 3
        assert item.summary == ""
        assert item.action_type is None
        assert item.action_detail is None
        assert item.related_todo_id is None


class TestIngestQueue:
    def test_put_and_get_basic(self):
        from datetime import datetime

        from mem_agent.core.queue import IngestItem, IngestQueue

        q = IngestQueue(batch_size=1, flush_interval=5.0)
        ts = datetime(2026, 2, 1, 10, 0, 0)
        item = IngestItem(text="test item", source="note", timestamp=ts)

        result = q.put(item)
        assert result is True
        assert q.pending_count() == 1

        batch = q.get_batch(timeout=1.0)
        assert len(batch) == 1
        assert batch[0].text == "test item"
        assert q.pending_count() == 0

    def test_batch_trigger_by_count(self):
        from datetime import datetime

        from mem_agent.core.queue import IngestItem, IngestQueue

        q = IngestQueue(batch_size=3, flush_interval=60.0)
        for i in range(3):
            ts = datetime(2026, 2, 1, 10, 0, i)
            q.put(IngestItem(text=f"item {i}", source="terminal", timestamp=ts))

        batch = q.get_batch(timeout=1.0)
        assert len(batch) == 3

    def test_dedup_same_content_within_window(self):
        from datetime import datetime

        from mem_agent.core.queue import IngestItem, IngestQueue

        q = IngestQueue(batch_size=10, flush_interval=60.0, dedup_window=300.0)
        ts = datetime(2026, 2, 1, 10, 0, 0)

        result1 = q.put(IngestItem(text="duplicate", source="note", timestamp=ts))
        result2 = q.put(IngestItem(text="duplicate", source="clipboard", timestamp=ts))

        assert result1 is True
        assert result2 is False
        assert q.pending_count() == 1

    def test_no_dedup_for_different_content(self):
        from datetime import datetime

        from mem_agent.core.queue import IngestItem, IngestQueue

        q = IngestQueue(batch_size=10, flush_interval=60.0, dedup_window=300.0)
        ts = datetime(2026, 2, 1, 10, 0, 0)

        result1 = q.put(IngestItem(text="first message", source="note", timestamp=ts))
        result2 = q.put(IngestItem(text="second message", source="note", timestamp=ts))

        assert result1 is True
        assert result2 is True
        assert q.pending_count() == 2

    def test_flush_interval_trigger(self):
        import time
        from datetime import datetime

        from mem_agent.core.queue import IngestItem, IngestQueue

        q = IngestQueue(batch_size=100, flush_interval=0.3)
        ts = datetime(2026, 2, 1, 10, 0, 0)
        q.put(IngestItem(text="waiting item", source="file", timestamp=ts))

        start = time.monotonic()
        batch = q.get_batch(timeout=2.0)
        elapsed = time.monotonic() - start

        assert len(batch) == 1
        assert batch[0].text == "waiting item"
        assert elapsed >= 0.2  # flushed by interval, not instantly
