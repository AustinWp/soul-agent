"""Tests for modules/classifier.py -- LLM-powered batch classification."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest


class TestFallbackClassify:
    def test_terminal_source_maps_to_coding(self):
        from mem_agent.modules.classifier import fallback_classify

        result = fallback_classify("git status", "terminal")
        assert result["category"] == "coding"
        assert result["importance"] == 3
        assert result["action_type"] is None

    def test_browser_source_maps_to_browsing(self):
        from mem_agent.modules.classifier import fallback_classify

        result = fallback_classify("visited google.com", "browser")
        assert result["category"] == "browsing"
        assert result["importance"] == 3
        assert result["action_type"] is None

    def test_claude_code_source_maps_to_coding(self):
        from mem_agent.modules.classifier import fallback_classify

        result = fallback_classify("refactor module", "claude-code")
        assert result["category"] == "coding"
        assert result["importance"] == 3
        assert result["action_type"] is None

    def test_input_method_source_maps_to_communication(self):
        from mem_agent.modules.classifier import fallback_classify

        result = fallback_classify("hello world", "input-method")
        assert result["category"] == "communication"
        assert result["importance"] == 3
        assert result["action_type"] is None

    def test_unknown_source_defaults_to_work(self):
        from mem_agent.modules.classifier import fallback_classify

        result = fallback_classify("some note", "note")
        assert result["category"] == "work"
        assert result["importance"] == 3
        assert result["action_type"] is None


class TestParseLLMResponse:
    def test_valid_json_array(self):
        from mem_agent.modules.classifier import _parse_llm_response

        raw = json.dumps([
            {
                "category": "coding",
                "tags": ["python"],
                "importance": 4,
                "summary": "wrote code",
                "action_type": None,
                "action_detail": None,
                "related_todo_id": None,
            },
        ])
        result = _parse_llm_response(raw, count=1)
        assert len(result) == 1
        assert result[0]["category"] == "coding"
        assert result[0]["importance"] == 4

    def test_invalid_json_returns_empty(self):
        from mem_agent.modules.classifier import _parse_llm_response

        result = _parse_llm_response("this is not json at all", count=1)
        assert result == []

    def test_json_with_markdown_fences(self):
        from mem_agent.modules.classifier import _parse_llm_response

        inner = json.dumps([
            {
                "category": "learning",
                "tags": ["reading"],
                "importance": 2,
                "summary": "read article",
                "action_type": None,
                "action_detail": None,
                "related_todo_id": None,
            },
        ])
        raw = f"```json\n{inner}\n```"
        result = _parse_llm_response(raw, count=1)
        assert len(result) == 1
        assert result[0]["category"] == "learning"

    def test_count_mismatch_returns_empty(self):
        from mem_agent.modules.classifier import _parse_llm_response

        raw = json.dumps([
            {"category": "coding", "tags": [], "importance": 3, "summary": "a"},
        ])
        # Expecting 2 items but got 1
        result = _parse_llm_response(raw, count=2)
        assert result == []


class TestClassifyBatch:
    @patch(
        "mem_agent.modules.classifier.call_deepseek",
        return_value=json.dumps([
            {
                "category": "coding",
                "tags": ["python", "refactor"],
                "importance": 4,
                "summary": "refactored the parser",
                "action_type": None,
                "action_detail": None,
                "related_todo_id": None,
            },
        ]),
    )
    def test_with_llm_response(self, mock_llm):
        from datetime import datetime

        from mem_agent.core.queue import ClassifiedItem, IngestItem
        from mem_agent.modules.classifier import classify_batch

        items = [
            IngestItem(
                text="refactored the parser module",
                source="terminal",
                timestamp=datetime(2026, 2, 25, 10, 0, 0),
            ),
        ]
        result = classify_batch(items, active_todos=[], config={})

        assert len(result) == 1
        assert isinstance(result[0], ClassifiedItem)
        assert result[0].category == "coding"
        assert result[0].importance == 4
        assert result[0].tags == ["python", "refactor"]
        assert result[0].summary == "refactored the parser"
        mock_llm.assert_called_once()

    @patch(
        "mem_agent.modules.classifier.call_deepseek",
        return_value="",
    )
    def test_fallback_on_empty_llm_response(self, mock_llm):
        from datetime import datetime

        from mem_agent.core.queue import ClassifiedItem, IngestItem
        from mem_agent.modules.classifier import classify_batch

        items = [
            IngestItem(
                text="browsing stackoverflow",
                source="browser",
                timestamp=datetime(2026, 2, 25, 10, 0, 0),
            ),
        ]
        result = classify_batch(items, active_todos=[], config={})

        assert len(result) == 1
        assert isinstance(result[0], ClassifiedItem)
        # Fallback: browser -> browsing
        assert result[0].category == "browsing"
        assert result[0].importance == 3

    @patch(
        "mem_agent.modules.classifier.call_deepseek",
        return_value=json.dumps([
            {
                "category": "work",
                "tags": ["task"],
                "importance": 5,
                "summary": "need to finish report",
                "action_type": "new_task",
                "action_detail": "Finish quarterly report by Friday",
                "related_todo_id": None,
            },
        ]),
    )
    def test_detects_new_task_action_type(self, mock_llm):
        from datetime import datetime

        from mem_agent.core.queue import ClassifiedItem, IngestItem
        from mem_agent.modules.classifier import classify_batch

        items = [
            IngestItem(
                text="I need to finish the quarterly report by Friday",
                source="input-method",
                timestamp=datetime(2026, 2, 25, 14, 0, 0),
            ),
        ]
        result = classify_batch(items, active_todos=[], config={})

        assert len(result) == 1
        assert result[0].action_type == "new_task"
        assert result[0].action_detail == "Finish quarterly report by Friday"
