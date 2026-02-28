"""Tests for modules/pipeline.py — classification pipeline."""
from __future__ import annotations
from unittest.mock import MagicMock, patch


class TestProcessBatch:
    @patch("soul_agent.modules.pipeline.classify_batch")
    def test_process_stores_classified_items(self, mock_classify):
        from datetime import datetime
        from soul_agent.core.queue import ClassifiedItem, IngestItem
        from soul_agent.modules.pipeline import process_batch

        item = IngestItem(text="test note", source="note", timestamp=datetime(2026, 2, 25, 10, 0), meta={})
        classified = ClassifiedItem(text="test note", source="note", timestamp=datetime(2026, 2, 25, 10, 0), meta={},
            category="work", tags=["test"], importance=3, summary="test", action_type=None, action_detail=None, related_todo_id=None)
        mock_classify.return_value = [classified]
        engine = MagicMock()
        engine.config = {}
        engine.list_resources.return_value = []

        process_batch([item], engine)
        mock_classify.assert_called_once()

    @patch("soul_agent.modules.pipeline.classify_batch")
    def test_process_creates_todo_on_new_task(self, mock_classify):
        from datetime import datetime
        from soul_agent.core.queue import ClassifiedItem, IngestItem
        from soul_agent.modules.pipeline import process_batch

        item = IngestItem(text="need to write report", source="note", timestamp=datetime(2026, 2, 25, 10, 0), meta={})
        classified = ClassifiedItem(text="need to write report", source="note", timestamp=datetime(2026, 2, 25, 10, 0), meta={},
            category="work", tags=["planning"], importance=4, summary="write report", action_type="new_task", action_detail="Write weekly report", related_todo_id=None)
        mock_classify.return_value = [classified]
        engine = MagicMock()
        engine.config = {}
        engine.list_resources.return_value = []

        with patch("soul_agent.modules.pipeline.add_todo") as mock_add_todo:
            process_batch([item], engine)
            mock_add_todo.assert_called_once()


class TestPipelineThread:
    def test_pipeline_starts_and_stops(self):
        from soul_agent.core.queue import IngestQueue
        from soul_agent.modules.pipeline import start_pipeline_thread

        engine = MagicMock()
        engine.config = {}
        engine.list_resources.return_value = []
        q = IngestQueue(batch_size=10, flush_interval=0.5)

        thread, stop_event = start_pipeline_thread(q, engine)
        assert thread.is_alive()
        stop_event.clear()
        thread.join(timeout=3)
        assert not thread.is_alive()
