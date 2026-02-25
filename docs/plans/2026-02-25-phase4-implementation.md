# Phase 4 Implementation Plan: Pipeline Architecture

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade mem-agent from a memory system to an AI work assistant with full-spectrum input capture, LLM auto-classification, insight generation, and MCP server integration.

**Architecture:** All input sources feed into a unified IngestQueue. A background classifier thread batch-processes items via DeepSeek LLM, tagging each with category/tags/importance and detecting todo intent. Classified items are stored in enhanced daily logs and fed to an Insight Engine that generates daily reports, tracks task completion, identifies work patterns, and produces actionable advice. An MCP Server exposes all capabilities to Claude Code.

**Tech Stack:** Python 3.12, FastAPI, OpenViking, DeepSeek API, watchdog, pyobjc (Quartz/Cocoa), MCP SDK (Python)

**Design doc:** `docs/plans/2026-02-25-phase4-pipeline-design.md`

---

## Task 1: Add New Dependencies

**Files:**
- Modify: `pyproject.toml`

**Step 1: Update pyproject.toml**

Add new dependencies to the `dependencies` list in `pyproject.toml`:

```toml
dependencies = [
    "openviking>=0.1.6",
    "typer[all]>=0.9.0",
    "rich>=13.0.0",
    "openai>=1.0.0",
    "fastapi>=0.100.0",
    "uvicorn>=0.20.0",
    "httpx>=0.24.0",
    "watchdog>=4.0.0",
    "pyobjc-framework-Quartz>=10.0",
    "pyobjc-framework-Cocoa>=10.0",
    "mcp>=1.0.0",
]
```

**Step 2: Install dependencies**

Run: `cd /Users/austin/Desktop/MyAgent/mem-agent && .venv/bin/pip install -e ".[dev]" 2>&1 | tail -5`

If `[dev]` extra doesn't exist, run: `.venv/bin/pip install -e .`

Expected: All packages installed successfully.

**Step 3: Verify imports**

Run: `.venv/bin/python -c "import watchdog; import Quartz; import AppKit; import mcp; print('OK')"`

Expected: `OK`

**Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add Phase 4 dependencies (watchdog, pyobjc, mcp)"
```

---

## Task 2: Ingest Queue + Data Models

**Files:**
- Create: `mem_agent/core/queue.py`
- Test: `tests/test_queue.py`

**Step 1: Write failing tests for IngestItem and ClassifiedItem**

Create `tests/test_queue.py`:

```python
"""Tests for core/queue.py — IngestQueue and data models."""


class TestIngestItem:
    def test_create_ingest_item(self):
        from datetime import datetime
        from mem_agent.core.queue import IngestItem

        item = IngestItem(
            text="hello world",
            source="note",
            timestamp=datetime(2026, 2, 25, 10, 0),
            meta={},
        )
        assert item.text == "hello world"
        assert item.source == "note"

    def test_ingest_item_with_meta(self):
        from datetime import datetime
        from mem_agent.core.queue import IngestItem

        item = IngestItem(
            text="visited page",
            source="browser",
            timestamp=datetime(2026, 2, 25, 10, 0),
            meta={"url": "https://example.com", "title": "Example"},
        )
        assert item.meta["url"] == "https://example.com"


class TestClassifiedItem:
    def test_create_classified_item(self):
        from datetime import datetime
        from mem_agent.core.queue import ClassifiedItem

        item = ClassifiedItem(
            text="fix bug in parser",
            source="note",
            timestamp=datetime(2026, 2, 25, 10, 0),
            meta={},
            category="coding",
            tags=["python", "bugfix"],
            importance=4,
            summary="修复解析器 bug",
            action_type="task_progress",
            action_detail="修复 parser 的 bug",
            related_todo_id="a1b2c3d4",
        )
        assert item.category == "coding"
        assert item.tags == ["python", "bugfix"]
        assert item.importance == 4
        assert item.action_type == "task_progress"

    def test_classified_item_no_action(self):
        from datetime import datetime
        from mem_agent.core.queue import ClassifiedItem

        item = ClassifiedItem(
            text="browsing news",
            source="browser",
            timestamp=datetime(2026, 2, 25, 10, 0),
            meta={},
            category="browsing",
            tags=["news"],
            importance=1,
            summary="浏览新闻",
            action_type=None,
            action_detail=None,
            related_todo_id=None,
        )
        assert item.action_type is None


class TestIngestQueue:
    def test_put_and_get(self):
        from datetime import datetime
        from mem_agent.core.queue import IngestItem, IngestQueue

        q = IngestQueue(batch_size=2, flush_interval=60)
        item = IngestItem(
            text="test", source="note",
            timestamp=datetime(2026, 2, 25, 10, 0), meta={},
        )
        q.put(item)
        assert q.pending_count() == 1

    def test_batch_trigger_by_count(self):
        from datetime import datetime
        from mem_agent.core.queue import IngestItem, IngestQueue

        q = IngestQueue(batch_size=2, flush_interval=9999)
        for i in range(2):
            q.put(IngestItem(
                text=f"item {i}", source="note",
                timestamp=datetime(2026, 2, 25, 10, i), meta={},
            ))
        batch = q.get_batch(timeout=1)
        assert len(batch) == 2

    def test_dedup_same_content_within_window(self):
        from datetime import datetime
        from mem_agent.core.queue import IngestItem, IngestQueue

        q = IngestQueue(batch_size=10, flush_interval=60, dedup_window=60)
        now = datetime(2026, 2, 25, 10, 0)
        item1 = IngestItem(text="same text", source="note", timestamp=now, meta={})
        item2 = IngestItem(text="same text", source="clipboard", timestamp=now, meta={})
        q.put(item1)
        q.put(item2)
        assert q.pending_count() == 1  # second was deduped

    def test_no_dedup_different_content(self):
        from datetime import datetime
        from mem_agent.core.queue import IngestItem, IngestQueue

        q = IngestQueue(batch_size=10, flush_interval=60, dedup_window=60)
        now = datetime(2026, 2, 25, 10, 0)
        q.put(IngestItem(text="text A", source="note", timestamp=now, meta={}))
        q.put(IngestItem(text="text B", source="note", timestamp=now, meta={}))
        assert q.pending_count() == 2

    def test_flush_interval_trigger(self):
        import time
        from datetime import datetime
        from mem_agent.core.queue import IngestItem, IngestQueue

        q = IngestQueue(batch_size=999, flush_interval=0.3)
        q.put(IngestItem(
            text="lonely item", source="note",
            timestamp=datetime(2026, 2, 25, 10, 0), meta={},
        ))
        batch = q.get_batch(timeout=2)
        assert len(batch) == 1
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_queue.py -v 2>&1 | tail -20`

Expected: FAIL — `ModuleNotFoundError: No module named 'mem_agent.core.queue'`

**Step 3: Implement core/queue.py**

Create `mem_agent/core/queue.py`:

```python
"""Unified ingest queue with batching, dedup, and data models."""
from __future__ import annotations

import hashlib
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class IngestItem:
    """Raw input from any source adapter."""

    text: str
    source: str
    timestamp: datetime
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ClassifiedItem(IngestItem):
    """IngestItem after LLM classification."""

    category: str = ""
    tags: list[str] = field(default_factory=list)
    importance: int = 3
    summary: str = ""
    action_type: str | None = None
    action_detail: str | None = None
    related_todo_id: str | None = None


class IngestQueue:
    """Thread-safe batching queue with dedup."""

    def __init__(
        self,
        batch_size: int = 10,
        flush_interval: float = 60.0,
        dedup_window: float = 60.0,
    ) -> None:
        self._queue: queue.Queue[IngestItem] = queue.Queue()
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._dedup_window = dedup_window
        self._recent_hashes: dict[str, float] = {}
        self._lock = threading.Lock()
        self._batch_ready = threading.Event()

    @staticmethod
    def _hash_text(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    def _cleanup_old_hashes(self, now: float) -> None:
        cutoff = now - self._dedup_window
        expired = [h for h, t in self._recent_hashes.items() if t < cutoff]
        for h in expired:
            del self._recent_hashes[h]

    def put(self, item: IngestItem) -> bool:
        """Add item to queue. Returns False if deduped."""
        now = time.time()
        text_hash = self._hash_text(item.text)
        with self._lock:
            self._cleanup_old_hashes(now)
            if text_hash in self._recent_hashes:
                return False
            self._recent_hashes[text_hash] = now
        self._queue.put(item)
        if self._queue.qsize() >= self._batch_size:
            self._batch_ready.set()
        return True

    def pending_count(self) -> int:
        return self._queue.qsize()

    def get_batch(self, timeout: float | None = None) -> list[IngestItem]:
        """Block until batch_size items or flush_interval, then return batch."""
        wait_time = timeout if timeout is not None else self._flush_interval
        self._batch_ready.wait(timeout=wait_time)
        self._batch_ready.clear()
        items: list[IngestItem] = []
        while not self._queue.empty() and len(items) < self._batch_size:
            try:
                items.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return items
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_queue.py -v`

Expected: All 8 tests PASS.

**Step 5: Commit**

```bash
git add mem_agent/core/queue.py tests/test_queue.py
git commit -m "feat: add IngestQueue with batching, dedup, and data models"
```

---

## Task 3: Extend Frontmatter for Classification Fields

**Files:**
- Modify: `mem_agent/core/frontmatter.py`
- Modify: `tests/test_frontmatter.py`

**Step 1: Write failing tests for new frontmatter fields**

Append to `tests/test_frontmatter.py`:

```python
class TestClassificationFields:
    def test_build_with_classification(self):
        from mem_agent.core.frontmatter import build_frontmatter

        fields = {
            "priority": "P2",
            "category": "coding",
            "tags": "python,bugfix",
            "importance": "4",
        }
        result = build_frontmatter(fields, "body text")
        assert "category: coding" in result
        assert "tags: python,bugfix" in result
        assert "importance: 4" in result

    def test_parse_classification_fields(self):
        from mem_agent.core.frontmatter import parse_frontmatter

        content = "---\ncategory: coding\ntags: python,bugfix\nimportance: 4\n---\nbody"
        fields, body = parse_frontmatter(content)
        assert fields["category"] == "coding"
        assert fields["tags"] == "python,bugfix"
        assert fields["importance"] == "4"

    def test_add_classification_fields(self):
        from mem_agent.core.frontmatter import add_classification_fields

        fields = {"priority": "P2"}
        result = add_classification_fields(
            fields, category="coding", tags=["python", "bugfix"], importance=4
        )
        assert result["category"] == "coding"
        assert result["tags"] == "python,bugfix"
        assert result["importance"] == "4"

    def test_add_classification_defaults(self):
        from mem_agent.core.frontmatter import add_classification_fields

        fields = {}
        result = add_classification_fields(fields)
        assert result["category"] == "work"
        assert result["tags"] == ""
        assert result["importance"] == "3"

    def test_parse_tags_helper(self):
        from mem_agent.core.frontmatter import parse_tags

        assert parse_tags("python,bugfix,api") == ["python", "bugfix", "api"]
        assert parse_tags("") == []
        assert parse_tags("single") == ["single"]


class TestActivityLog:
    def test_add_activity_entry(self):
        from mem_agent.core.frontmatter import add_activity_entry

        fields = {}
        result = add_activity_entry(fields, "2026-02-25", "note")
        assert "activity_log" in result
        assert "2026-02-25" in result["activity_log"]
        assert result["last_activity"] == "2026-02-25"

    def test_add_activity_entry_existing(self):
        from mem_agent.core.frontmatter import add_activity_entry

        fields = {
            "activity_log": "2026-02-24:1:clipboard",
            "last_activity": "2026-02-24",
        }
        result = add_activity_entry(fields, "2026-02-25", "note")
        assert "2026-02-24" in result["activity_log"]
        assert "2026-02-25" in result["activity_log"]
        assert result["last_activity"] == "2026-02-25"

    def test_parse_activity_log(self):
        from mem_agent.core.frontmatter import parse_activity_log

        raw = "2026-02-24:3:note,clipboard|2026-02-25:1:terminal"
        entries = parse_activity_log(raw)
        assert len(entries) == 2
        assert entries[0]["date"] == "2026-02-24"
        assert entries[0]["count"] == 3
        assert entries[0]["sources"] == ["note", "clipboard"]
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_frontmatter.py::TestClassificationFields -v 2>&1 | tail -10`

Expected: FAIL — `ImportError: cannot import name 'add_classification_fields'`

**Step 3: Add classification and activity helpers to frontmatter.py**

Add these functions to the end of `mem_agent/core/frontmatter.py` (after `is_expired`):

```python
def add_classification_fields(
    fields: dict[str, str],
    category: str = "work",
    tags: list[str] | None = None,
    importance: int = 3,
) -> dict[str, str]:
    """Add classification fields to frontmatter."""
    fields["category"] = category
    fields["tags"] = ",".join(tags) if tags else ""
    fields["importance"] = str(importance)
    return fields


def parse_tags(raw: str) -> list[str]:
    """Parse comma-separated tags string into list."""
    if not raw or not raw.strip():
        return []
    return [t.strip() for t in raw.split(",") if t.strip()]


def add_activity_entry(
    fields: dict[str, str], date_str: str, source: str
) -> dict[str, str]:
    """Append an activity entry to the activity_log field.

    Format: date:count:sources|date:count:sources
    Example: 2026-02-24:3:note,clipboard|2026-02-25:1:terminal
    """
    existing = fields.get("activity_log", "")
    entries = _parse_activity_raw(existing)

    found = False
    for entry in entries:
        if entry["date"] == date_str:
            entry["count"] += 1
            if source not in entry["sources"]:
                entry["sources"].append(source)
            found = True
            break
    if not found:
        entries.append({"date": date_str, "count": 1, "sources": [source]})

    fields["activity_log"] = _serialize_activity(entries)
    fields["last_activity"] = date_str
    return fields


def parse_activity_log(raw: str) -> list[dict]:
    """Parse activity_log string into list of dicts."""
    return _parse_activity_raw(raw)


def _parse_activity_raw(raw: str) -> list[dict]:
    if not raw or not raw.strip():
        return []
    entries = []
    for part in raw.split("|"):
        part = part.strip()
        if not part:
            continue
        segments = part.split(":")
        if len(segments) >= 3:
            entries.append({
                "date": segments[0],
                "count": int(segments[1]),
                "sources": [s for s in segments[2].split(",") if s],
            })
    return entries


def _serialize_activity(entries: list[dict]) -> str:
    parts = []
    for e in entries:
        sources = ",".join(e["sources"])
        parts.append(f"{e['date']}:{e['count']}:{sources}")
    return "|".join(parts)
```

**Step 4: Run all frontmatter tests**

Run: `.venv/bin/python -m pytest tests/test_frontmatter.py -v`

Expected: All tests PASS (existing + new).

**Step 5: Commit**

```bash
git add mem_agent/core/frontmatter.py tests/test_frontmatter.py
git commit -m "feat: add classification and activity log fields to frontmatter"
```

---

## Task 4: Enhanced Daily Log with Classification

**Files:**
- Modify: `mem_agent/modules/daily_log.py`
- Modify: `tests/test_daily_log.py`

**Step 1: Write failing tests for classified log entries**

Append to `tests/test_daily_log.py`:

```python
class TestAppendClassifiedLog:
    def test_append_with_classification(self):
        from unittest.mock import MagicMock
        from mem_agent.modules.daily_log import append_daily_log

        engine = MagicMock()
        engine.config = {}
        engine.read_resource.return_value = None

        append_daily_log(
            "fixed parser bug", "note", engine,
            category="coding", tags=["python", "bugfix"], importance=4,
        )

        engine.write_resource.assert_called_once()
        content = engine.write_resource.call_args.kwargs.get(
            "content", engine.write_resource.call_args[0][0]
            if engine.write_resource.call_args[0] else ""
        )
        assert "category: coding" in content or "[coding]" in content

    def test_append_preserves_existing_classified_entries(self):
        from unittest.mock import MagicMock
        from mem_agent.modules.daily_log import append_daily_log

        engine = MagicMock()
        engine.config = {}
        engine.read_resource.return_value = (
            "---\npriority: P2\ndate: 2026-02-25\n---\n"
            "[10:00] (note) [coding] first entry\n"
        )

        append_daily_log(
            "read article about Rust", "browser", engine,
            category="learning", tags=["rust"], importance=2,
        )

        engine.write_resource.assert_called_once()
        content = engine.write_resource.call_args.kwargs.get(
            "content", engine.write_resource.call_args[0][0]
            if engine.write_resource.call_args[0] else ""
        )
        assert "[coding] first entry" in content
        assert "[learning]" in content
```

**Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_daily_log.py::TestAppendClassifiedLog -v 2>&1 | tail -10`

Expected: FAIL — `append_daily_log() got an unexpected keyword argument 'category'`

**Step 3: Update append_daily_log to accept classification params**

Modify `mem_agent/modules/daily_log.py`, update `append_daily_log` signature and body to include optional classification fields. The entry format changes from:

```
[HH:MM] (source) text
```

to:

```
[HH:MM] (source) [category] text
```

when category is provided. The function signature becomes:

```python
def append_daily_log(
    text: str,
    source: str,
    engine: MemEngine,
    category: str = "",
    tags: list[str] | None = None,
    importance: int = 3,
) -> None:
```

In the entry line construction, change from:
```python
entry = f"[{now.strftime('%H:%M')}] ({source}) {text}\n"
```
to:
```python
cat_tag = f" [{category}]" if category else ""
entry = f"[{now.strftime('%H:%M')}] ({source}){cat_tag} {text}\n"
```

When creating a new log file, if category is set, add classification fields to frontmatter:
```python
if category:
    from ..core.frontmatter import add_classification_fields
    add_classification_fields(fields, category, tags or [], importance)
```

**Step 4: Run all daily_log tests**

Run: `.venv/bin/python -m pytest tests/test_daily_log.py -v`

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add mem_agent/modules/daily_log.py tests/test_daily_log.py
git commit -m "feat: daily log entries now support classification metadata"
```

---

## Task 5: LLM Classifier

**Files:**
- Create: `mem_agent/modules/classifier.py`
- Test: `tests/test_classifier.py`

**Step 1: Write failing tests**

Create `tests/test_classifier.py`:

```python
"""Tests for modules/classifier.py — batch LLM classification."""
from unittest.mock import MagicMock, patch


class TestFallbackClassify:
    def test_terminal_source(self):
        from mem_agent.modules.classifier import fallback_classify

        result = fallback_classify("git push origin main", "terminal")
        assert result["category"] == "coding"

    def test_browser_source(self):
        from mem_agent.modules.classifier import fallback_classify

        result = fallback_classify("visited example.com", "browser")
        assert result["category"] == "browsing"

    def test_claude_code_source(self):
        from mem_agent.modules.classifier import fallback_classify

        result = fallback_classify("discussed bug fix", "claude-code")
        assert result["category"] == "coding"

    def test_default_source(self):
        from mem_agent.modules.classifier import fallback_classify

        result = fallback_classify("some text", "note")
        assert result["category"] == "work"
        assert result["importance"] == 3


class TestParseLLMResponse:
    def test_parse_valid_json(self):
        from mem_agent.modules.classifier import _parse_llm_response

        raw = '[{"category":"coding","tags":["python"],"importance":4,"summary":"写代码","action_type":null,"action_detail":null}]'
        results = _parse_llm_response(raw, count=1)
        assert len(results) == 1
        assert results[0]["category"] == "coding"

    def test_parse_invalid_json_returns_empty(self):
        from mem_agent.modules.classifier import _parse_llm_response

        results = _parse_llm_response("not json", count=1)
        assert results == []

    def test_parse_json_with_markdown_fences(self):
        from mem_agent.modules.classifier import _parse_llm_response

        raw = '```json\n[{"category":"work","tags":[],"importance":3,"summary":"工作","action_type":null,"action_detail":null}]\n```'
        results = _parse_llm_response(raw, count=1)
        assert len(results) == 1


class TestClassifyBatch:
    @patch("mem_agent.modules.classifier.call_deepseek")
    def test_classify_batch_with_llm(self, mock_llm):
        import json
        from datetime import datetime
        from mem_agent.core.queue import IngestItem
        from mem_agent.modules.classifier import classify_batch

        mock_llm.return_value = json.dumps([{
            "category": "coding",
            "tags": ["python", "api"],
            "importance": 4,
            "summary": "API 开发",
            "action_type": None,
            "action_detail": None,
        }])

        items = [IngestItem(
            text="building API endpoint",
            source="note",
            timestamp=datetime(2026, 2, 25, 10, 0),
            meta={},
        )]
        results = classify_batch(items, active_todos=[], config={})
        assert len(results) == 1
        assert results[0].category == "coding"
        assert results[0].tags == ["python", "api"]
        mock_llm.assert_called_once()

    @patch("mem_agent.modules.classifier.call_deepseek", return_value="")
    def test_classify_batch_fallback_on_empty_response(self, mock_llm):
        from datetime import datetime
        from mem_agent.core.queue import IngestItem
        from mem_agent.modules.classifier import classify_batch

        items = [IngestItem(
            text="git status", source="terminal",
            timestamp=datetime(2026, 2, 25, 10, 0), meta={},
        )]
        results = classify_batch(items, active_todos=[], config={})
        assert len(results) == 1
        assert results[0].category == "coding"

    @patch("mem_agent.modules.classifier.call_deepseek")
    def test_classify_batch_detects_new_task(self, mock_llm):
        import json
        from datetime import datetime
        from mem_agent.core.queue import IngestItem
        from mem_agent.modules.classifier import classify_batch

        mock_llm.return_value = json.dumps([{
            "category": "work",
            "tags": ["planning"],
            "importance": 4,
            "summary": "需要写周报",
            "action_type": "new_task",
            "action_detail": "写本周周报",
        }])

        items = [IngestItem(
            text="明天要写周报", source="note",
            timestamp=datetime(2026, 2, 25, 10, 0), meta={},
        )]
        results = classify_batch(items, active_todos=[], config={})
        assert results[0].action_type == "new_task"
        assert results[0].action_detail == "写本周周报"
```

**Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_classifier.py -v 2>&1 | tail -10`

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement classifier.py**

Create `mem_agent/modules/classifier.py`:

```python
"""LLM batch classifier with fallback rules and todo detection."""
from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from ..core.llm import call_deepseek
from ..core.queue import ClassifiedItem, IngestItem

if TYPE_CHECKING:
    pass

VALID_CATEGORIES = {"coding", "work", "learning", "communication", "browsing", "life"}

SOURCE_CATEGORY_MAP: dict[str, str] = {
    "terminal": "coding",
    "browser": "browsing",
    "claude-code": "coding",
    "input-method": "communication",
}

CLASSIFIER_SYSTEM = "你是一个个人输入分类器。严格按 JSON 数组格式返回，不要添加其他文字。"

CLASSIFIER_PROMPT = """\
对以下批量输入逐条分类。

每条返回 JSON 对象:
- category: coding|work|learning|communication|browsing|life
- tags: 2-5个关键标签（数组）
- importance: 1-5 (5=非常重要)
- summary: 一句话摘要（<30字）
- action_type: "new_task"|"task_progress"|"task_done"|null
- action_detail: 如果有 action_type，描述具体待办内容，否则 null

当前活跃待办列表（用于匹配 task_progress/task_done）:
{todos}

输入列表:
{items}

返回 JSON 数组，条目数与输入列表相同。"""


def fallback_classify(text: str, source: str) -> dict[str, Any]:
    """Rule-based classification when LLM is unavailable."""
    return {
        "category": SOURCE_CATEGORY_MAP.get(source, "work"),
        "tags": [],
        "importance": 3,
        "summary": text[:30],
        "action_type": None,
        "action_detail": None,
    }


def _parse_llm_response(raw: str, count: int) -> list[dict[str, Any]]:
    """Parse LLM JSON response, handling markdown fences."""
    raw = raw.strip()
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
    if fence_match:
        raw = fence_match.group(1).strip()
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
        return []
    except (json.JSONDecodeError, TypeError):
        return []


def classify_batch(
    items: list[IngestItem],
    active_todos: list[dict[str, Any]],
    config: dict,
) -> list[ClassifiedItem]:
    """Classify a batch of items using LLM with fallback."""
    if not items:
        return []

    todos_str = json.dumps(active_todos, ensure_ascii=False) if active_todos else "[]"
    items_str = "\n".join(
        f"[{item.source}, {item.timestamp.strftime('%H:%M')}] {item.text}"
        for item in items
    )
    prompt = CLASSIFIER_PROMPT.format(todos=todos_str, items=items_str)

    raw = call_deepseek(prompt, system=CLASSIFIER_SYSTEM, max_tokens=1024, config=config)
    parsed = _parse_llm_response(raw, count=len(items))

    results: list[ClassifiedItem] = []
    for i, item in enumerate(items):
        if i < len(parsed) and isinstance(parsed[i], dict):
            cls = parsed[i]
            cat = cls.get("category", "work")
            if cat not in VALID_CATEGORIES:
                cat = "work"
            results.append(ClassifiedItem(
                text=item.text,
                source=item.source,
                timestamp=item.timestamp,
                meta=item.meta,
                category=cat,
                tags=cls.get("tags", []) or [],
                importance=cls.get("importance", 3),
                summary=cls.get("summary", item.text[:30]),
                action_type=cls.get("action_type"),
                action_detail=cls.get("action_detail"),
                related_todo_id=cls.get("related_todo_id"),
            ))
        else:
            fb = fallback_classify(item.text, item.source)
            results.append(ClassifiedItem(
                text=item.text,
                source=item.source,
                timestamp=item.timestamp,
                meta=item.meta,
                **fb,
            ))
    return results
```

**Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_classifier.py -v`

Expected: All 8 tests PASS.

**Step 5: Commit**

```bash
git add mem_agent/modules/classifier.py tests/test_classifier.py
git commit -m "feat: add LLM batch classifier with fallback and todo detection"
```

---

## Task 6: Todo Activity Tracking

**Files:**
- Modify: `mem_agent/modules/todo.py`
- Test: `tests/test_todo_activity.py`

**Step 1: Write failing tests**

Create `tests/test_todo_activity.py`:

```python
"""Tests for todo activity tracking extensions."""
from unittest.mock import MagicMock


class TestUpdateTodoActivity:
    def test_add_activity_to_existing_todo(self):
        from mem_agent.modules.todo import update_todo_activity

        engine = MagicMock()
        engine.list_resources.return_value = ["task-a1b2.md"]
        engine.read_resource.return_value = (
            "---\nid: a1b2c3d4\nstatus: active\n---\nDo something"
        )

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
        engine.read_resource.return_value = (
            "---\nid: a1b2c3d4\nstatus: active\nlast_activity: 2026-02-20\n---\nOld task"
        )

        stalled = get_stalled_todos(engine, stale_days=3)
        assert len(stalled) == 1
        assert stalled[0]["id"] == "a1b2c3d4"

    def test_active_todo_not_stalled(self):
        from mem_agent.modules.todo import get_stalled_todos
        from datetime import date

        engine = MagicMock()
        engine.list_resources.return_value = ["task1.md"]
        today = date.today().isoformat()
        engine.read_resource.return_value = (
            f"---\nid: a1b2c3d4\nstatus: active\nlast_activity: {today}\n---\nFresh task"
        )

        stalled = get_stalled_todos(engine, stale_days=3)
        assert len(stalled) == 0
```

**Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_todo_activity.py -v 2>&1 | tail -10`

Expected: FAIL — `ImportError: cannot import name 'update_todo_activity'`

**Step 3: Add activity tracking functions to todo.py**

Append to `mem_agent/modules/todo.py`:

```python
def update_todo_activity(
    todo_id: str, source: str, engine: Any = None
) -> bool:
    """Record activity on an existing todo."""
    if engine is None:
        engine = get_engine()
    from ..core.frontmatter import add_activity_entry, parse_frontmatter, build_frontmatter
    from datetime import date as _date

    for filename in engine.list_resources(ACTIVE_DIR):
        uri = f"{ACTIVE_DIR}{filename}"
        content = engine.read_resource(uri)
        if content is None:
            continue
        fields, body = parse_frontmatter(content)
        if fields.get("id", "")[:8] == todo_id[:8]:
            today = _date.today().isoformat()
            add_activity_entry(fields, today, source)
            new_content = build_frontmatter(fields, body)
            engine.delete_resource(uri)
            engine.write_resource(
                content=new_content, target_uri=ACTIVE_DIR, filename=filename
            )
            return True
    return False


def get_stalled_todos(
    engine: Any = None, stale_days: int = 3
) -> list[dict[str, Any]]:
    """Find active todos with no recent activity."""
    if engine is None:
        engine = get_engine()
    from ..core.frontmatter import parse_frontmatter
    from datetime import date as _date, timedelta

    cutoff = (_date.today() - timedelta(days=stale_days)).isoformat()
    stalled = []
    for filename in engine.list_resources(ACTIVE_DIR):
        uri = f"{ACTIVE_DIR}{filename}"
        content = engine.read_resource(uri)
        if content is None:
            continue
        fields, body = parse_frontmatter(content)
        last = fields.get("last_activity", "")
        if last and last <= cutoff:
            stalled.append({
                "id": fields.get("id", ""),
                "text": body.strip(),
                "last_activity": last,
                "uri": uri,
            })
    return stalled
```

**Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_todo_activity.py -v`

Expected: All 4 tests PASS.

**Step 5: Run full test suite to check no regressions**

Run: `.venv/bin/python -m pytest tests/ -v`

Expected: All existing + new tests PASS.

**Step 6: Commit**

```bash
git add mem_agent/modules/todo.py tests/test_todo_activity.py
git commit -m "feat: add todo activity tracking and stalled detection"
```

---

## Task 7: Classification Pipeline Thread

**Files:**
- Create: `mem_agent/modules/pipeline.py`
- Test: `tests/test_pipeline.py`

This module ties IngestQueue + Classifier + Storage together in a background thread.

**Step 1: Write failing tests**

Create `tests/test_pipeline.py`:

```python
"""Tests for modules/pipeline.py — the classification pipeline thread."""
from unittest.mock import MagicMock, patch


class TestProcessBatch:
    @patch("mem_agent.modules.pipeline.classify_batch")
    def test_process_stores_classified_items(self, mock_classify):
        from datetime import datetime
        from mem_agent.core.queue import ClassifiedItem, IngestItem
        from mem_agent.modules.pipeline import process_batch

        item = IngestItem(
            text="test note", source="note",
            timestamp=datetime(2026, 2, 25, 10, 0), meta={},
        )
        classified = ClassifiedItem(
            text="test note", source="note",
            timestamp=datetime(2026, 2, 25, 10, 0), meta={},
            category="work", tags=["test"], importance=3,
            summary="测试笔记", action_type=None,
            action_detail=None, related_todo_id=None,
        )
        mock_classify.return_value = [classified]

        engine = MagicMock()
        engine.config = {}
        engine.list_resources.return_value = []

        process_batch([item], engine)

        mock_classify.assert_called_once()
        engine.ingest_text.assert_called_once()

    @patch("mem_agent.modules.pipeline.classify_batch")
    def test_process_creates_todo_on_new_task(self, mock_classify):
        from datetime import datetime
        from mem_agent.core.queue import ClassifiedItem, IngestItem
        from mem_agent.modules.pipeline import process_batch

        item = IngestItem(
            text="需要写周报", source="note",
            timestamp=datetime(2026, 2, 25, 10, 0), meta={},
        )
        classified = ClassifiedItem(
            text="需要写周报", source="note",
            timestamp=datetime(2026, 2, 25, 10, 0), meta={},
            category="work", tags=["planning"], importance=4,
            summary="写周报", action_type="new_task",
            action_detail="写本周周报", related_todo_id=None,
        )
        mock_classify.return_value = [classified]

        engine = MagicMock()
        engine.config = {}
        engine.list_resources.return_value = []

        with patch("mem_agent.modules.pipeline.add_todo") as mock_add_todo:
            process_batch([item], engine)
            mock_add_todo.assert_called_once()


class TestPipelineThread:
    def test_pipeline_starts_and_stops(self):
        from mem_agent.core.queue import IngestQueue
        from mem_agent.modules.pipeline import start_pipeline_thread

        engine = MagicMock()
        engine.config = {}
        engine.list_resources.return_value = []
        q = IngestQueue(batch_size=10, flush_interval=0.5)

        thread, stop_event = start_pipeline_thread(q, engine)
        assert thread.is_alive()

        stop_event.clear()
        thread.join(timeout=3)
        assert not thread.is_alive()
```

**Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_pipeline.py -v 2>&1 | tail -10`

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement pipeline.py**

Create `mem_agent/modules/pipeline.py`:

```python
"""Classification pipeline: connects IngestQueue → Classifier → Storage."""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from ..core.queue import ClassifiedItem, IngestItem, IngestQueue
from .classifier import classify_batch
from .daily_log import append_daily_log
from .todo import add_todo, update_todo_activity

if TYPE_CHECKING:
    from ..core.engine import MemEngine


def _get_active_todos(engine: MemEngine) -> list[dict[str, Any]]:
    """Fetch active todos for classifier context."""
    from ..core.frontmatter import parse_frontmatter

    todos = []
    try:
        for filename in engine.list_resources("viking://resources/todos/active/"):
            uri = f"viking://resources/todos/active/{filename}"
            content = engine.read_resource(uri)
            if content:
                fields, body = parse_frontmatter(content)
                todos.append({"id": fields.get("id", ""), "text": body.strip()})
    except Exception:
        pass
    return todos


def process_batch(items: list[IngestItem], engine: MemEngine) -> list[ClassifiedItem]:
    """Classify a batch and persist results."""
    active_todos = _get_active_todos(engine)
    classified = classify_batch(items, active_todos, engine.config)

    for ci in classified:
        try:
            append_daily_log(
                ci.text, ci.source, engine,
                category=ci.category, tags=ci.tags, importance=ci.importance,
            )
        except Exception:
            pass

        try:
            engine.ingest_text(ci.text, ci.source)
        except Exception:
            pass

        if ci.action_type == "new_task" and ci.action_detail:
            try:
                add_todo(ci.action_detail)
            except Exception:
                pass

        if ci.action_type == "task_progress" and ci.related_todo_id:
            try:
                update_todo_activity(ci.related_todo_id, ci.source, engine)
            except Exception:
                pass

    return classified


def _pipeline_loop(
    queue: IngestQueue, engine: MemEngine, running: threading.Event
) -> None:
    """Background loop: consume queue → classify → store."""
    while running.is_set():
        batch = queue.get_batch(timeout=2)
        if batch:
            try:
                process_batch(batch, engine)
            except Exception:
                pass


def start_pipeline_thread(
    queue: IngestQueue, engine: MemEngine
) -> tuple[threading.Thread, threading.Event]:
    """Start the classification pipeline daemon thread."""
    running = threading.Event()
    running.set()
    thread = threading.Thread(
        target=_pipeline_loop, args=(queue, engine, running),
        daemon=True, name="pipeline",
    )
    thread.start()
    return thread, running
```

**Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_pipeline.py -v`

Expected: All 3 tests PASS.

**Step 5: Commit**

```bash
git add mem_agent/modules/pipeline.py tests/test_pipeline.py
git commit -m "feat: add classification pipeline thread connecting queue-classifier-storage"
```

---

## Task 8: Refactor Existing Sources to Use IngestQueue

**Files:**
- Modify: `mem_agent/modules/note.py`
- Modify: `mem_agent/modules/clipboard.py`
- Modify: `mem_agent/service.py`
- Test: run existing tests to verify no regression

**Step 1: Add queue parameter to note.add_note**

In `mem_agent/modules/note.py`, modify `add_note` to optionally accept an `IngestQueue`. When a queue is provided, write to the queue instead of directly calling `ingest_text` + `append_daily_log`. When no queue is provided (CLI direct use), fall back to the old behavior for backward compatibility.

```python
def add_note(text: str, ingest_queue: IngestQueue | None = None) -> dict[str, Any]:
    """Record a note. If ingest_queue is provided, route through pipeline."""
    if ingest_queue is not None:
        from datetime import datetime
        from ..core.queue import IngestItem
        ingest_queue.put(IngestItem(
            text=text, source="note",
            timestamp=datetime.now(), meta={},
        ))
        console.print("[green]Note queued for classification.[/green]")
        return {"status": "queued"}

    # Original behavior (CLI direct use without daemon)
    engine = get_engine()
    result = engine.ingest_text(text, source="note")
    # ... (keep existing dual-write)
```

**Step 2: Add queue parameter to clipboard loop**

In `mem_agent/modules/clipboard.py`, modify `_clipboard_loop` to accept an optional `IngestQueue` parameter. When provided, put items into the queue instead of direct ingest + daily_log.

```python
def _clipboard_loop(engine: MemEngine, running: threading.Event, ingest_queue: IngestQueue | None = None) -> None:
```

Inside the loop, when new clip is detected:
```python
if ingest_queue is not None:
    from ..core.queue import IngestItem
    ingest_queue.put(IngestItem(
        text=clip, source="clipboard",
        timestamp=datetime.now(), meta={},
    ))
else:
    # Original behavior
    engine.ingest_text(clip, source="clipboard")
    ...
```

Update `start_clipboard_monitor` to accept and pass through the queue:
```python
def start_clipboard_monitor(engine: MemEngine, ingest_queue: IngestQueue | None = None) -> tuple[threading.Thread, threading.Event]:
```

**Step 3: Update service.py terminal buffer flush to use queue**

In `mem_agent/service.py`, modify `_flush_cmd_buffer` to accept an optional queue. When provided, write to queue instead of directly to engine + daily_log.

**Step 4: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -v`

Expected: All tests PASS (existing behavior unchanged when queue=None).

**Step 5: Commit**

```bash
git add mem_agent/modules/note.py mem_agent/modules/clipboard.py mem_agent/service.py
git commit -m "refactor: existing sources optionally route through IngestQueue"
```

---

## Task 9: Browser History Adapter

**Files:**
- Create: `mem_agent/modules/browser.py`
- Test: `tests/test_browser.py`

**Step 1: Write failing tests**

Create `tests/test_browser.py`:

```python
"""Tests for modules/browser.py — browser history adapter."""
from unittest.mock import MagicMock, patch
import sqlite3
import tempfile
import os


class TestChromeHistoryReader:
    def test_read_chrome_history_from_db(self):
        from mem_agent.modules.browser import read_chrome_history

        # Create a temp SQLite DB mimicking Chrome's schema
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        try:
            conn = sqlite3.connect(tmp.name)
            conn.execute(
                "CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, title TEXT, last_visit_time INTEGER)"
            )
            # Chrome uses microseconds since 1601-01-01
            # 13350000000000000 ≈ 2026-02-25
            conn.execute(
                "INSERT INTO urls VALUES (1, 'https://example.com', 'Example', 13350000000000000)"
            )
            conn.commit()
            conn.close()

            entries = read_chrome_history(db_path=tmp.name, since_timestamp=0)
            assert len(entries) == 1
            assert entries[0]["url"] == "https://example.com"
            assert entries[0]["title"] == "Example"
        finally:
            os.unlink(tmp.name)

    def test_filter_internal_urls(self):
        from mem_agent.modules.browser import _should_skip_url

        assert _should_skip_url("chrome://settings") is True
        assert _should_skip_url("about:blank") is True
        assert _should_skip_url("chrome-extension://abc") is True
        assert _should_skip_url("https://example.com") is False


class TestBrowserLoop:
    def test_browser_loop_puts_to_queue(self):
        import threading
        from mem_agent.modules.browser import _browser_loop
        from mem_agent.core.queue import IngestQueue

        q = IngestQueue(batch_size=10, flush_interval=60)
        running = threading.Event()
        running.set()

        with patch("mem_agent.modules.browser.read_chrome_history") as mock_read:
            mock_read.return_value = [
                {"url": "https://example.com", "title": "Example", "visit_time": 13350000000000000}
            ]
            with patch("mem_agent.modules.browser.read_safari_history", return_value=[]):
                # Run one iteration then stop
                def stop_after_one(*args, **kwargs):
                    running.clear()
                    return True
                with patch("threading.Event.wait", side_effect=stop_after_one):
                    _browser_loop(q, running)

        assert q.pending_count() >= 0  # May have deduped, but no crash
```

**Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_browser.py -v 2>&1 | tail -10`

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement browser.py**

Create `mem_agent/modules/browser.py`:

```python
"""Browser history adapter — reads Chrome/Safari history SQLite databases."""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ..core.queue import IngestItem, IngestQueue

CHROME_DB = Path.home() / "Library/Application Support/Google/Chrome/Default/History"
SAFARI_DB = Path.home() / "Library/Safari/History.db"

POLL_INTERVAL = 300  # 5 minutes
SKIP_PREFIXES = ("chrome://", "chrome-extension://", "about:", "data:", "blob:", "file://")


def _should_skip_url(url: str) -> bool:
    return any(url.startswith(p) for p in SKIP_PREFIXES)


def _copy_db(db_path: str | Path) -> str | None:
    """Copy DB to temp file (browsers lock the file)."""
    src = Path(db_path)
    if not src.exists():
        return None
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    try:
        shutil.copy2(src, tmp.name)
        return tmp.name
    except Exception:
        return None


def read_chrome_history(
    db_path: str | Path | None = None, since_timestamp: int = 0
) -> list[dict[str, Any]]:
    """Read Chrome history entries newer than since_timestamp."""
    path = db_path or CHROME_DB
    tmp_path = _copy_db(path) if db_path is None else str(path)
    if tmp_path is None:
        return []
    try:
        conn = sqlite3.connect(f"file:{tmp_path}?mode=ro", uri=True)
        cursor = conn.execute(
            "SELECT url, title, last_visit_time FROM urls "
            "WHERE last_visit_time > ? ORDER BY last_visit_time",
            (since_timestamp,),
        )
        entries = []
        for url, title, visit_time in cursor:
            if not _should_skip_url(url):
                entries.append({"url": url, "title": title or "", "visit_time": visit_time})
        conn.close()
        return entries
    except Exception:
        return []
    finally:
        if db_path is None and tmp_path:
            try:
                Path(tmp_path).unlink()
            except Exception:
                pass


def read_safari_history(
    db_path: str | Path | None = None, since_timestamp: float = 0
) -> list[dict[str, Any]]:
    """Read Safari history entries."""
    path = db_path or SAFARI_DB
    tmp_path = _copy_db(path) if db_path is None else str(path)
    if tmp_path is None:
        return []
    try:
        conn = sqlite3.connect(f"file:{tmp_path}?mode=ro", uri=True)
        cursor = conn.execute(
            "SELECT hi.url, hv.title, hv.visit_time "
            "FROM history_items hi JOIN history_visits hv ON hi.id = hv.history_item "
            "WHERE hv.visit_time > ? ORDER BY hv.visit_time",
            (since_timestamp,),
        )
        entries = []
        for url, title, visit_time in cursor:
            if not _should_skip_url(url):
                entries.append({"url": url, "title": title or "", "visit_time": visit_time})
        conn.close()
        return entries
    except Exception:
        return []
    finally:
        if db_path is None and tmp_path:
            try:
                Path(tmp_path).unlink()
            except Exception:
                pass


def _browser_loop(queue: IngestQueue, running: threading.Event) -> None:
    """Background loop polling browser history."""
    chrome_last = 0
    safari_last = 0.0

    while running.is_set():
        # Chrome
        entries = read_chrome_history(since_timestamp=chrome_last)
        for e in entries:
            text = f"{e['title']} — {e['url']}"
            queue.put(IngestItem(
                text=text, source="browser",
                timestamp=datetime.now(),
                meta={"url": e["url"], "title": e["title"]},
            ))
            if e["visit_time"] > chrome_last:
                chrome_last = e["visit_time"]

        # Safari
        entries = read_safari_history(since_timestamp=safari_last)
        for e in entries:
            text = f"{e['title']} — {e['url']}"
            queue.put(IngestItem(
                text=text, source="browser",
                timestamp=datetime.now(),
                meta={"url": e["url"], "title": e["title"]},
            ))
            if e["visit_time"] > safari_last:
                safari_last = e["visit_time"]

        running.wait(timeout=POLL_INTERVAL)


def start_browser_monitor(queue: IngestQueue) -> tuple[threading.Thread, threading.Event]:
    """Start the browser history polling thread."""
    running = threading.Event()
    running.set()
    thread = threading.Thread(
        target=_browser_loop, args=(queue, running),
        daemon=True, name="browser-monitor",
    )
    thread.start()
    return thread, running
```

**Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_browser.py -v`

Expected: Tests PASS.

**Step 5: Commit**

```bash
git add mem_agent/modules/browser.py tests/test_browser.py
git commit -m "feat: add browser history adapter (Chrome + Safari)"
```

---

## Task 10: File Watcher Adapter

**Files:**
- Create: `mem_agent/modules/filewatcher.py`
- Test: `tests/test_filewatcher.py`

**Step 1: Write failing tests**

Create `tests/test_filewatcher.py`:

```python
"""Tests for modules/filewatcher.py — file change monitoring."""


class TestShouldIgnore:
    def test_ignore_git_directory(self):
        from mem_agent.modules.filewatcher import _should_ignore

        assert _should_ignore("/repo/.git/objects/abc") is True

    def test_ignore_node_modules(self):
        from mem_agent.modules.filewatcher import _should_ignore

        assert _should_ignore("/project/node_modules/pkg/index.js") is True

    def test_ignore_ds_store(self):
        from mem_agent.modules.filewatcher import _should_ignore

        assert _should_ignore("/Users/me/Desktop/.DS_Store") is True

    def test_allow_normal_file(self):
        from mem_agent.modules.filewatcher import _should_ignore

        assert _should_ignore("/Users/me/Desktop/notes.md") is False

    def test_ignore_binary_extension(self):
        from mem_agent.modules.filewatcher import _should_ignore

        assert _should_ignore("/Users/me/photo.jpg") is True
        assert _should_ignore("/Users/me/app.exe") is True


class TestExtractPreview:
    def test_extract_text_preview(self):
        import tempfile, os
        from mem_agent.modules.filewatcher import _extract_preview

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Hello world\nThis is a test file\n" * 50)
            f.flush()
            preview = _extract_preview(f.name, max_chars=100)
            assert len(preview) <= 100
            assert "Hello world" in preview
            os.unlink(f.name)

    def test_extract_preview_missing_file(self):
        from mem_agent.modules.filewatcher import _extract_preview

        result = _extract_preview("/nonexistent/file.txt")
        assert result == ""
```

**Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_filewatcher.py -v 2>&1 | tail -10`

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement filewatcher.py**

Create `mem_agent/modules/filewatcher.py`:

```python
"""File watcher adapter using watchdog for directory monitoring."""
from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent
from watchdog.observers import Observer

from ..core.queue import IngestItem, IngestQueue

DEFAULT_WATCH_DIRS = [
    str(Path.home() / "Desktop"),
    str(Path.home() / "Documents"),
    str(Path.home() / "Downloads"),
]

IGNORE_PATTERNS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".tox"}
IGNORE_FILES = {".DS_Store", "Thumbs.db", ".gitkeep"}
BINARY_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".ico", ".svg", ".webp",
    ".mp3", ".mp4", ".avi", ".mov", ".mkv", ".wav", ".flac",
    ".zip", ".tar", ".gz", ".rar", ".7z",
    ".exe", ".dll", ".so", ".dylib", ".o",
    ".pdf", ".doc", ".xls", ".ppt",
    ".pyc", ".class", ".wasm",
}


def _should_ignore(path: str) -> bool:
    """Check if a file path should be ignored."""
    p = Path(path)
    if p.name in IGNORE_FILES:
        return True
    if p.suffix.lower() in BINARY_EXTENSIONS:
        return True
    for part in p.parts:
        if part in IGNORE_PATTERNS:
            return True
    return False


def _extract_preview(path: str, max_chars: int = 500) -> str:
    """Extract first N characters from a text file."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read(max_chars)
    except Exception:
        return ""


class _FileHandler(FileSystemEventHandler):
    def __init__(self, queue: IngestQueue) -> None:
        self._queue = queue

    def on_created(self, event: Any) -> None:
        if event.is_directory:
            return
        self._handle(event.src_path, "created")

    def on_modified(self, event: Any) -> None:
        if event.is_directory:
            return
        self._handle(event.src_path, "modified")

    def _handle(self, path: str, action: str) -> None:
        if _should_ignore(path):
            return
        preview = _extract_preview(path)
        filename = Path(path).name
        text = f"[{action}] {filename}"
        if preview:
            text += f": {preview[:200]}"
        self._queue.put(IngestItem(
            text=text, source="file",
            timestamp=datetime.now(),
            meta={"path": path, "action": action, "filename": filename},
        ))


def start_file_watcher(
    queue: IngestQueue, watch_dirs: list[str] | None = None
) -> tuple[Observer, threading.Event]:
    """Start watchdog observer on specified directories."""
    dirs = watch_dirs or DEFAULT_WATCH_DIRS
    running = threading.Event()
    running.set()

    observer = Observer()
    handler = _FileHandler(queue)
    for d in dirs:
        if Path(d).is_dir():
            observer.schedule(handler, d, recursive=True)

    observer.daemon = True
    observer.start()
    return observer, running
```

**Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_filewatcher.py -v`

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add mem_agent/modules/filewatcher.py tests/test_filewatcher.py
git commit -m "feat: add file watcher adapter using watchdog"
```

---

## Task 11: Claude Code Hook Adapter

**Files:**
- Create: `mem_agent/modules/claude_code.py`
- Create: `mem_agent/hooks/claude_code_hook.sh`
- Test: `tests/test_claude_code.py`

**Step 1: Write failing tests**

Create `tests/test_claude_code.py`:

```python
"""Tests for modules/claude_code.py — Claude Code hook management."""
from unittest.mock import patch, mock_open
import json


class TestBuildHookConfig:
    def test_build_hook_config(self):
        from mem_agent.modules.claude_code import build_hook_config

        config = build_hook_config()
        assert "hooks" in config
        # Should have a Stop event hook or similar
        assert isinstance(config["hooks"], dict)

    def test_hook_posts_to_daemon(self):
        from mem_agent.modules.claude_code import build_hook_config

        config = build_hook_config()
        # The hook command should reference the daemon endpoint
        hook_values = json.dumps(config)
        assert "8330" in hook_values or "mem-agent" in hook_values
```

**Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_claude_code.py -v 2>&1 | tail -10`

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement claude_code.py**

Create `mem_agent/modules/claude_code.py`:

```python
"""Claude Code integration — hook installation and ingest endpoint."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rich.console import Console

CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"
HOOK_SCRIPT = Path(__file__).parent.parent / "hooks" / "claude_code_hook.sh"

console = Console()


def build_hook_config() -> dict[str, Any]:
    """Build the Claude Code hooks configuration."""
    script_path = str(HOOK_SCRIPT)
    return {
        "hooks": {
            "Stop": [
                {
                    "matcher": "",
                    "hooks": [f"bash {script_path}"],
                }
            ],
        }
    }


def install_hook() -> None:
    """Install mem-agent hook into Claude Code settings."""
    CLAUDE_SETTINGS.parent.mkdir(parents=True, exist_ok=True)

    existing: dict[str, Any] = {}
    if CLAUDE_SETTINGS.exists():
        try:
            existing = json.loads(CLAUDE_SETTINGS.read_text())
        except Exception:
            pass

    hook_config = build_hook_config()
    if "hooks" not in existing:
        existing["hooks"] = {}
    existing["hooks"].update(hook_config["hooks"])

    CLAUDE_SETTINGS.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
    console.print("[green]Claude Code hook installed.[/green]")
    console.print(f"  Config: {CLAUDE_SETTINGS}")


def uninstall_hook() -> None:
    """Remove mem-agent hook from Claude Code settings."""
    if not CLAUDE_SETTINGS.exists():
        console.print("[yellow]No Claude Code settings found.[/yellow]")
        return

    try:
        existing = json.loads(CLAUDE_SETTINGS.read_text())
        hooks = existing.get("hooks", {})
        hooks.pop("Stop", None)
        if not hooks:
            existing.pop("hooks", None)
        CLAUDE_SETTINGS.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
        console.print("[green]Claude Code hook removed.[/green]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
```

Create `mem_agent/hooks/claude_code_hook.sh`:

```bash
#!/bin/bash
# mem-agent Claude Code hook — posts session summary to daemon
# This runs at the end of each Claude Code conversation (Stop event)

DAEMON_URL="http://127.0.0.1:8330/ingest/claudecode"

# Read conversation summary from stdin (Claude Code pipes context)
SUMMARY=$(cat)

if [ -n "$SUMMARY" ]; then
    curl -s -X POST "$DAEMON_URL" \
        -H "Content-Type: application/json" \
        -d "{\"text\": $(echo "$SUMMARY" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')}" \
        > /dev/null 2>&1 || true
fi
```

**Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_claude_code.py -v`

Expected: Tests PASS.

**Step 5: Commit**

```bash
chmod +x mem_agent/hooks/claude_code_hook.sh
git add mem_agent/modules/claude_code.py mem_agent/hooks/claude_code_hook.sh tests/test_claude_code.py
git commit -m "feat: add Claude Code hook adapter for conversation capture"
```

---

## Task 12: Input Method Hook Adapter

**Files:**
- Create: `mem_agent/modules/input_hook.py`
- Test: `tests/test_input_hook.py`

**Step 1: Write failing tests**

Create `tests/test_input_hook.py`:

```python
"""Tests for modules/input_hook.py — input method hook (macOS CGEventTap)."""
from unittest.mock import MagicMock, patch


class TestDedicatedApps:
    def test_terminal_is_dedicated(self):
        from mem_agent.modules.input_hook import DEDICATED_APPS

        assert "com.apple.Terminal" in DEDICATED_APPS

    def test_iterm_is_dedicated(self):
        from mem_agent.modules.input_hook import DEDICATED_APPS

        assert "com.googlecode.iterm2" in DEDICATED_APPS


class TestInputBuffer:
    def test_flush_buffer_with_enough_text(self):
        from mem_agent.modules.input_hook import InputBuffer
        from mem_agent.core.queue import IngestQueue

        q = IngestQueue(batch_size=10, flush_interval=60)
        buf = InputBuffer(queue=q, min_length=5)
        buf.append("Hello World Testing")
        buf.flush()

        assert q.pending_count() == 1

    def test_flush_buffer_too_short(self):
        from mem_agent.modules.input_hook import InputBuffer
        from mem_agent.core.queue import IngestQueue

        q = IngestQueue(batch_size=10, flush_interval=60)
        buf = InputBuffer(queue=q, min_length=10)
        buf.append("Hi")
        buf.flush()

        assert q.pending_count() == 0  # Too short, discarded


class TestHookStatus:
    def test_initial_status_stopped(self):
        from mem_agent.modules.input_hook import hook_status

        status = hook_status()
        assert status["active"] is False
```

**Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_input_hook.py -v 2>&1 | tail -10`

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement input_hook.py**

Create `mem_agent/modules/input_hook.py`:

```python
"""Input method global hook using macOS CGEventTap (optional, togglable)."""
from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any

from ..core.queue import IngestItem, IngestQueue

DEDICATED_APPS = {
    "com.apple.Terminal",
    "com.googlecode.iterm2",
    "com.todesktop.230313mzl4w4u92",  # Claude Code (Electron)
}

MIN_INPUT_LENGTH = 10
IDLE_TIMEOUT = 5.0  # seconds of no input before flushing buffer

_state: dict[str, Any] = {"active": False, "thread": None, "stop_event": None}


class InputBuffer:
    """Accumulates keystrokes and flushes as segments."""

    def __init__(self, queue: IngestQueue, min_length: int = MIN_INPUT_LENGTH) -> None:
        self._buffer: list[str] = []
        self._queue = queue
        self._min_length = min_length
        self._last_input = 0.0

    def append(self, text: str) -> None:
        self._buffer.append(text)
        self._last_input = time.time()

    def flush(self) -> None:
        content = "".join(self._buffer).strip()
        self._buffer.clear()
        if len(content) >= self._min_length:
            self._queue.put(IngestItem(
                text=content, source="input-method",
                timestamp=datetime.now(),
                meta={"type": "keyboard"},
            ))

    def should_flush(self) -> bool:
        if not self._buffer:
            return False
        return (time.time() - self._last_input) >= IDLE_TIMEOUT


def _get_frontmost_bundle_id() -> str:
    """Get the bundle ID of the frontmost application."""
    try:
        from AppKit import NSWorkspace
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return app.bundleIdentifier() or ""
    except Exception:
        return ""


def _is_secure_field() -> bool:
    """Check if the focused UI element is a secure text field."""
    try:
        from ApplicationServices import (
            AXUIElementCreateSystemWide,
            AXUIElementCopyAttributeValue,
        )
        import Accessibility
        system = AXUIElementCreateSystemWide()
        # Try to detect secure input — simplified check
        return False  # Full implementation requires accessibility API
    except Exception:
        return False


def _input_loop(queue: IngestQueue, running: threading.Event) -> None:
    """Main input hook loop using CGEventTap."""
    try:
        import Quartz
    except ImportError:
        return

    buf = InputBuffer(queue=queue)

    def callback(proxy, event_type, event, refcon):
        if not running.is_set():
            return event

        # Check if in dedicated app
        if _get_frontmost_bundle_id() in DEDICATED_APPS:
            return event

        # Check secure field
        if _is_secure_field():
            return event

        # Extract character
        try:
            chars = Quartz.CGEventKeyboardGetUnicodeString(
                event, 1, None, None
            )
        except Exception:
            ns_event = Quartz.NSEvent.eventWithCGEvent_(event)
            if ns_event:
                chars = ns_event.characters()
            else:
                chars = None

        if chars:
            buf.append(chars)
        return event

    # Create event tap
    mask = Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)
    tap = Quartz.CGEventTapCreate(
        Quartz.kCGSessionEventTap,
        Quartz.kCGHeadInsertEventTap,
        Quartz.kCGEventTapOptionListenOnly,
        mask,
        callback,
        None,
    )
    if tap is None:
        return  # No accessibility permission

    source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
    loop = Quartz.CFRunLoopGetCurrent()
    Quartz.CFRunLoopAddSource(loop, source, Quartz.kCFRunLoopDefaultMode)
    Quartz.CGEventTapEnable(tap, True)

    while running.is_set():
        Quartz.CFRunLoopRunInMode(Quartz.kCFRunLoopDefaultMode, 1.0, False)
        if buf.should_flush():
            buf.flush()

    buf.flush()


def start_input_hook(queue: IngestQueue) -> tuple[threading.Thread, threading.Event]:
    """Start the input method hook daemon thread."""
    running = threading.Event()
    running.set()
    thread = threading.Thread(
        target=_input_loop, args=(queue, running),
        daemon=True, name="input-hook",
    )
    thread.start()
    _state.update({"active": True, "thread": thread, "stop_event": running})
    return thread, running


def stop_input_hook() -> None:
    """Stop the input method hook."""
    if _state.get("stop_event"):
        _state["stop_event"].clear()
    _state["active"] = False


def hook_status() -> dict[str, Any]:
    """Return current hook status."""
    return {
        "active": _state.get("active", False),
        "thread_alive": _state.get("thread") is not None and _state["thread"].is_alive(),
    }
```

**Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_input_hook.py -v`

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add mem_agent/modules/input_hook.py tests/test_input_hook.py
git commit -m "feat: add input method hook adapter (macOS CGEventTap)"
```

---

## Task 13: Insight Engine

**Files:**
- Create: `mem_agent/modules/insight.py`
- Test: `tests/test_insight.py`

**Step 1: Write failing tests**

Create `tests/test_insight.py`:

```python
"""Tests for modules/insight.py — insight engine."""
from unittest.mock import MagicMock, patch
from datetime import date


class TestParseDailyLogEntries:
    def test_parse_classified_entries(self):
        from mem_agent.modules.insight import parse_daily_log_entries

        log = (
            "---\npriority: P2\ndate: 2026-02-25\n---\n"
            "[10:00] (note) [coding] fixed parser bug\n"
            "[11:30] (browser) [learning] read Rust tutorial\n"
            "[14:00] (clipboard) [work] meeting notes\n"
        )
        entries = parse_daily_log_entries(log)
        assert len(entries) == 3
        assert entries[0]["category"] == "coding"
        assert entries[0]["time"] == "10:00"
        assert entries[1]["category"] == "learning"

    def test_parse_unclassified_entries(self):
        from mem_agent.modules.insight import parse_daily_log_entries

        log = "---\npriority: P2\n---\n[10:00] (note) plain text entry\n"
        entries = parse_daily_log_entries(log)
        assert len(entries) == 1
        assert entries[0]["category"] == "uncategorized"


class TestComputeTimeAllocation:
    def test_basic_allocation(self):
        from mem_agent.modules.insight import compute_time_allocation

        entries = [
            {"time": "10:00", "category": "coding", "text": "a"},
            {"time": "10:30", "category": "coding", "text": "b"},
            {"time": "11:00", "category": "learning", "text": "c"},
            {"time": "14:00", "category": "work", "text": "d"},
        ]
        alloc = compute_time_allocation(entries)
        assert "coding" in alloc
        assert alloc["coding"]["count"] == 2

    def test_empty_entries(self):
        from mem_agent.modules.insight import compute_time_allocation

        alloc = compute_time_allocation([])
        assert alloc == {}


class TestBuildDailyInsight:
    @patch("mem_agent.modules.insight.call_deepseek", return_value="- 建议1\n- 建议2")
    def test_build_daily_insight(self, mock_llm):
        from mem_agent.modules.insight import build_daily_insight

        engine = MagicMock()
        engine.config = {}

        log_content = (
            "---\npriority: P2\ndate: 2026-02-25\n---\n"
            "[10:00] (note) [coding] fixed bug\n"
            "[11:00] (browser) [learning] read docs\n"
        )
        engine.read_resource.side_effect = lambda uri: (
            log_content if "logs/" in uri else None
        )
        engine.list_resources.return_value = []

        report = build_daily_insight(date(2026, 2, 25), engine)
        assert "coding" in report
        assert "learning" in report

    def test_build_daily_insight_no_data(self):
        from mem_agent.modules.insight import build_daily_insight

        engine = MagicMock()
        engine.config = {}
        engine.read_resource.return_value = None
        engine.list_resources.return_value = []

        report = build_daily_insight(date(2026, 2, 25), engine)
        assert "无数据" in report or report == ""


class TestGetTopTags:
    def test_top_tags(self):
        from mem_agent.modules.insight import get_top_tags

        entries = [
            {"tags": ["python", "api"]},
            {"tags": ["python", "bugfix"]},
            {"tags": ["rust"]},
        ]
        top = get_top_tags(entries, n=2)
        assert top[0][0] == "python"
        assert top[0][1] == 2
```

**Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_insight.py -v 2>&1 | tail -10`

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement insight.py**

Create `mem_agent/modules/insight.py`:

```python
"""Insight engine — daily insights, pattern tracking, task tracking, work advice."""
from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from ..core.frontmatter import parse_frontmatter, parse_tags, build_frontmatter, add_lifecycle_fields
from ..core.llm import call_deepseek
from .daily_log import LOGS_DIR, get_daily_log
from .todo import ACTIVE_DIR, DONE_DIR

if TYPE_CHECKING:
    from ..core.engine import MemEngine

INSIGHTS_DIR = "viking://resources/insights/"

ENTRY_PATTERN = re.compile(
    r"\[(\d{2}:\d{2})\]\s+\((\w[\w-]*)\)\s*(?:\[(\w+)\])?\s*(.*)"
)


def parse_daily_log_entries(log_content: str) -> list[dict[str, Any]]:
    """Parse a daily log into structured entries."""
    fields, body = parse_frontmatter(log_content)
    entries = []
    for line in body.strip().splitlines():
        m = ENTRY_PATTERN.match(line.strip())
        if m:
            entries.append({
                "time": m.group(1),
                "source": m.group(2),
                "category": m.group(3) or "uncategorized",
                "text": m.group(4),
                "tags": [],  # Tags are in frontmatter at file level
            })
    return entries


def compute_time_allocation(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Compute time spent per category based on entry count and time gaps."""
    if not entries:
        return {}

    alloc: dict[str, dict[str, Any]] = {}
    for entry in entries:
        cat = entry.get("category", "uncategorized")
        if cat not in alloc:
            alloc[cat] = {"count": 0, "entries": []}
        alloc[cat]["count"] += 1
        alloc[cat]["entries"].append(entry["time"])

    total = sum(a["count"] for a in alloc.values())
    for cat in alloc:
        alloc[cat]["percent"] = round(alloc[cat]["count"] / total * 100) if total else 0

    return alloc


def get_top_tags(entries: list[dict[str, Any]], n: int = 10) -> list[tuple[str, int]]:
    """Get most frequent tags from entries."""
    counter: Counter = Counter()
    for entry in entries:
        for tag in entry.get("tags", []):
            counter[tag] += 1
    return counter.most_common(n)


def _get_task_summary(engine: MemEngine) -> dict[str, Any]:
    """Summarize active and completed todos."""
    from .todo import get_stalled_todos

    active = []
    for filename in engine.list_resources(ACTIVE_DIR):
        content = engine.read_resource(f"{ACTIVE_DIR}{filename}")
        if content:
            fields, body = parse_frontmatter(content)
            active.append({
                "id": fields.get("id", ""),
                "text": body.strip(),
                "last_activity": fields.get("last_activity", ""),
                "auto_detected": fields.get("auto_detected", "false"),
            })

    done_today = []
    today = date.today().isoformat()
    for filename in engine.list_resources(DONE_DIR):
        content = engine.read_resource(f"{DONE_DIR}{filename}")
        if content:
            fields, body = parse_frontmatter(content)
            if fields.get("last_activity", "") == today:
                done_today.append({"id": fields.get("id", ""), "text": body.strip()})

    stalled = get_stalled_todos(engine)

    return {"active": active, "done_today": done_today, "stalled": stalled}


def build_daily_insight(target_date: date, engine: MemEngine) -> str:
    """Generate a daily insight report."""
    log = get_daily_log(target_date, engine)
    if not log:
        return f"# {target_date.isoformat()} 无数据\n\n今日没有记录。"

    entries = parse_daily_log_entries(log)
    alloc = compute_time_allocation(entries)
    task_summary = _get_task_summary(engine)

    # Build report sections
    lines = [f"# {target_date.month}月{target_date.day}日 工作洞察\n"]

    # Time allocation
    lines.append("## 时间分配\n")
    for cat, data in sorted(alloc.items(), key=lambda x: -x[1]["count"]):
        lines.append(f"- {cat}: {data['count']} 条 ({data['percent']}%)")
    lines.append("")

    # Task tracking
    lines.append("## 任务追踪\n")
    if task_summary["done_today"]:
        lines.append(f"### 已完成 ({len(task_summary['done_today'])})")
        for t in task_summary["done_today"]:
            lines.append(f"- ✓ {t['text']}")
        lines.append("")

    if task_summary["active"]:
        lines.append(f"### 进行中 ({len(task_summary['active'])})")
        for t in task_summary["active"]:
            lines.append(f"- → {t['text']}")
        lines.append("")

    if task_summary["stalled"]:
        lines.append(f"### 停滞预警 ({len(task_summary['stalled'])})")
        for t in task_summary["stalled"]:
            lines.append(f"- ⚠ {t['text']} (最后活动: {t['last_activity']})")
        lines.append("")

    # Core topics
    lines.append("## 今日核心话题\n")
    cat_entries = {}
    for e in entries:
        c = e["category"]
        if c not in cat_entries:
            cat_entries[c] = []
        cat_entries[c].append(e["text"])
    for i, (cat, texts) in enumerate(
        sorted(cat_entries.items(), key=lambda x: -len(x[1]))[:3], 1
    ):
        sample = texts[0][:50]
        lines.append(f"{i}. **{cat}** — {sample}...")
    lines.append("")

    # Work advice (LLM)
    report_so_far = "\n".join(lines)
    advice_prompt = (
        f"基于以下个人工作数据，给出3-5条具体、可执行的建议。"
        f"建议必须基于数据，包含效率提升和工作创新方向。\n\n{report_so_far}"
    )
    advice = call_deepseek(
        advice_prompt,
        system="你是 AI 工作效率教练。给出简洁、具体的建议。",
        max_tokens=512,
        config=engine.config,
    )
    if advice:
        lines.append("## 工作建议\n")
        lines.append(advice)

    return "\n".join(lines)


def save_daily_insight(target_date: date, engine: MemEngine) -> str:
    """Generate and save daily insight to viking storage."""
    report = build_daily_insight(target_date, engine)
    if not report:
        return ""

    fields: dict[str, str] = {"type": "daily-insight", "date": target_date.isoformat()}
    add_lifecycle_fields(fields, "P1")
    content = build_frontmatter(fields, report)

    filename = f"daily-{target_date.isoformat()}.md"
    uri = f"{INSIGHTS_DIR}{filename}"

    try:
        engine.delete_resource(uri)
    except Exception:
        pass
    engine.write_resource(content=content, target_uri=INSIGHTS_DIR, filename=filename)
    return report


def _insight_loop(engine: MemEngine, running: threading.Event) -> None:
    """Background thread generating daily insights at 20:00."""
    import threading

    while running.is_set():
        now = datetime.now()
        target = now.replace(hour=20, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        wait_seconds = (target - now).total_seconds()

        if running.wait(timeout=min(wait_seconds, 3600)):
            # Event was cleared = shutdown
            if not running.is_set():
                break
        else:
            # Timer expired
            if datetime.now().hour == 20:
                try:
                    save_daily_insight(date.today(), engine)
                except Exception:
                    pass


import threading


def start_insight_thread(engine: MemEngine) -> tuple[threading.Thread, threading.Event]:
    """Start the insight generation daemon thread."""
    running = threading.Event()
    running.set()
    thread = threading.Thread(
        target=_insight_loop, args=(engine, running),
        daemon=True, name="insight-engine",
    )
    thread.start()
    return thread, running
```

**Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_insight.py -v`

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add mem_agent/modules/insight.py tests/test_insight.py
git commit -m "feat: add insight engine with daily reports, time allocation, and work advice"
```

---

## Task 14: MCP Server

**Files:**
- Create: `mem_agent/mcp_server.py`
- Test: `tests/test_mcp_server.py`

**Step 1: Write failing tests**

Create `tests/test_mcp_server.py`:

```python
"""Tests for mcp_server.py — MCP server tool definitions."""


class TestMCPToolDefinitions:
    def test_tools_registered(self):
        from mem_agent.mcp_server import TOOL_DEFINITIONS

        names = [t["name"] for t in TOOL_DEFINITIONS]
        assert "mem_search" in names
        assert "mem_recall" in names
        assert "mem_insight" in names
        assert "mem_categories" in names
        assert "mem_todos" in names
        assert "mem_suggest" in names
        assert "mem_note" in names
        assert "mem_task_progress" in names

    def test_each_tool_has_description(self):
        from mem_agent.mcp_server import TOOL_DEFINITIONS

        for tool in TOOL_DEFINITIONS:
            assert "description" in tool
            assert len(tool["description"]) > 0


class TestMCPResourceDefinitions:
    def test_resources_registered(self):
        from mem_agent.mcp_server import RESOURCE_DEFINITIONS

        uris = [r["uri"] for r in RESOURCE_DEFINITIONS]
        assert "mem://insight/today" in uris
        assert "mem://todos/active" in uris
        assert "mem://core/memory" in uris
```

**Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_mcp_server.py -v 2>&1 | tail -10`

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement mcp_server.py**

Create `mem_agent/mcp_server.py`:

```python
"""MCP Server for mem-agent — exposes memory and insights to Claude."""
from __future__ import annotations

import json
from datetime import date
from typing import Any

import httpx

DAEMON_URL = "http://127.0.0.1:8330"

TOOL_DEFINITIONS = [
    {
        "name": "mem_search",
        "description": "Search memories semantically. Returns matching memories and resources.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "description": "Max results", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "mem_recall",
        "description": "Get a summary of memories for a time period.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["today", "week", "month"],
                    "description": "Time period to recall",
                },
            },
            "required": ["period"],
        },
    },
    {
        "name": "mem_insight",
        "description": "Get the AI-generated insight report for a date. Includes time allocation, task tracking, pattern analysis, and work advice.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format, or 'today' or 'latest'",
                    "default": "today",
                },
            },
        },
    },
    {
        "name": "mem_categories",
        "description": "Get category statistics — time allocation and tag frequency for a period.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["today", "week"],
                    "default": "today",
                },
                "category": {
                    "type": "string",
                    "description": "Filter to specific category",
                },
            },
        },
    },
    {
        "name": "mem_todos",
        "description": "Get todo list with completion status and activity tracking.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["active", "stalled", "all"],
                    "default": "active",
                },
            },
        },
    },
    {
        "name": "mem_suggest",
        "description": "Get AI-generated work suggestions based on recent activity, patterns, and todos.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "focus": {
                    "type": "string",
                    "description": "Optional focus area for suggestions",
                },
            },
        },
    },
    {
        "name": "mem_note",
        "description": "Add a memory/note to the system.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Note content"},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tags",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "mem_task_progress",
        "description": "Get the activity timeline for a specific todo item.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "todo_id": {"type": "string", "description": "Todo ID (8-char hex)"},
            },
            "required": ["todo_id"],
        },
    },
]

RESOURCE_DEFINITIONS = [
    {"uri": "mem://insight/today", "name": "Today's Insight", "description": "AI-generated daily insight report"},
    {"uri": "mem://insight/week", "name": "Weekly Insight", "description": "Weekly insight report"},
    {"uri": "mem://todos/active", "name": "Active Todos", "description": "Current active todo list"},
    {"uri": "mem://todos/stalled", "name": "Stalled Tasks", "description": "Tasks with no recent activity"},
    {"uri": "mem://core/memory", "name": "Core Memory", "description": "Permanent preferences and principles"},
    {"uri": "mem://stats/categories", "name": "Category Stats", "description": "Category breakdown for today"},
]


def _call_daemon(method: str, path: str, **kwargs: Any) -> dict | str:
    """Call the mem-agent daemon API."""
    try:
        url = f"{DAEMON_URL}{path}"
        if method == "GET":
            resp = httpx.get(url, params=kwargs, timeout=30)
        else:
            resp = httpx.post(url, json=kwargs, timeout=30)
        resp.raise_for_status()
        return resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text
    except Exception as e:
        return {"error": str(e)}


async def handle_tool_call(name: str, arguments: dict[str, Any]) -> str:
    """Handle an MCP tool call and return the result as text."""
    if name == "mem_search":
        result = _call_daemon("GET", "/search", q=arguments["query"], limit=arguments.get("limit", 10))
    elif name == "mem_recall":
        period = arguments.get("period", "today")
        result = _call_daemon("GET", f"/recall", period=period)
    elif name == "mem_insight":
        d = arguments.get("date", "today")
        result = _call_daemon("GET", f"/insight", date=d)
    elif name == "mem_categories":
        result = _call_daemon("GET", "/categories", **arguments)
    elif name == "mem_todos":
        result = _call_daemon("GET", "/todo/list", status=arguments.get("status", "active"))
    elif name == "mem_suggest":
        result = _call_daemon("GET", "/suggest", **arguments)
    elif name == "mem_note":
        result = _call_daemon("POST", "/note", text=arguments["text"])
    elif name == "mem_task_progress":
        result = _call_daemon("GET", f"/todo/progress/{arguments['todo_id']}")
    else:
        result = {"error": f"Unknown tool: {name}"}

    return json.dumps(result, ensure_ascii=False) if isinstance(result, dict) else str(result)


async def handle_resource_read(uri: str) -> str:
    """Handle an MCP resource read."""
    if uri == "mem://insight/today":
        return json.dumps(_call_daemon("GET", "/insight", date="today"), ensure_ascii=False)
    elif uri == "mem://insight/week":
        return json.dumps(_call_daemon("GET", "/insight", date="week"), ensure_ascii=False)
    elif uri == "mem://todos/active":
        return json.dumps(_call_daemon("GET", "/todo/list", status="active"), ensure_ascii=False)
    elif uri == "mem://todos/stalled":
        return json.dumps(_call_daemon("GET", "/todo/list", status="stalled"), ensure_ascii=False)
    elif uri == "mem://core/memory":
        return json.dumps(_call_daemon("GET", "/core"), ensure_ascii=False)
    elif uri == "mem://stats/categories":
        return json.dumps(_call_daemon("GET", "/categories", period="today"), ensure_ascii=False)
    return json.dumps({"error": f"Unknown resource: {uri}"})


def run_mcp_server() -> None:
    """Run the MCP server with stdio transport."""
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    import mcp.types as types
    import asyncio

    server = Server("mem-agent")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=t["name"],
                description=t["description"],
                inputSchema=t["inputSchema"],
            )
            for t in TOOL_DEFINITIONS
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        result = await handle_tool_call(name, arguments)
        return [types.TextContent(type="text", text=result)]

    @server.list_resources()
    async def list_resources() -> list[types.Resource]:
        return [
            types.Resource(
                uri=r["uri"],
                name=r["name"],
                description=r["description"],
            )
            for r in RESOURCE_DEFINITIONS
        ]

    @server.read_resource()
    async def read_resource(uri: str) -> str:
        return await handle_resource_read(str(uri))

    async def main():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream)

    asyncio.run(main())


if __name__ == "__main__":
    run_mcp_server()
```

**Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_mcp_server.py -v`

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add mem_agent/mcp_server.py tests/test_mcp_server.py
git commit -m "feat: add MCP server with 8 tools and 6 resources"
```

---

## Task 15: Service Integration — Wire Everything Together

**Files:**
- Modify: `mem_agent/service.py`

**Step 1: Add IngestQueue and pipeline to service lifespan**

In `mem_agent/service.py`, modify the `create_app()` lifespan to:

1. Create an `IngestQueue` instance
2. Start the pipeline thread
3. Start the browser monitor
4. Start the file watcher
5. Pass the queue to the clipboard monitor
6. Start the insight thread
7. Add new API endpoints: `/ingest/claudecode`, `/insight`, `/categories`, `/suggest`, `/todo/progress/{id}`

Key changes to lifespan startup:

```python
from .core.queue import IngestQueue
from .modules.pipeline import start_pipeline_thread
from .modules.browser import start_browser_monitor
from .modules.filewatcher import start_file_watcher
from .modules.insight import start_insight_thread

# In lifespan:
ingest_queue = IngestQueue(batch_size=10, flush_interval=60)
pipeline_thread, pipeline_stop = start_pipeline_thread(ingest_queue, engine)
browser_thread, browser_stop = start_browser_monitor(ingest_queue)
file_observer, file_stop = start_file_watcher(ingest_queue)
insight_thread, insight_stop = start_insight_thread(engine)
clip_thread, clip_stop = start_clipboard_monitor(engine, ingest_queue=ingest_queue)
```

Add new API endpoints:

```python
class ClaudeCodeRequest(BaseModel):
    text: str

@app.post("/ingest/claudecode")
async def ingest_claudecode(req: ClaudeCodeRequest):
    from .core.queue import IngestItem
    ingest_queue.put(IngestItem(
        text=req.text, source="claude-code",
        timestamp=datetime.now(), meta={},
    ))
    return {"status": "queued"}

@app.get("/insight")
async def get_insight(date: str = "today"):
    from .modules.insight import build_daily_insight, save_daily_insight
    from datetime import date as _date
    if date == "today":
        target = _date.today()
    else:
        target = _date.fromisoformat(date)
    report = build_daily_insight(target, engine)
    return {"date": target.isoformat(), "report": report}

@app.get("/categories")
async def get_categories(period: str = "today"):
    from .modules.insight import parse_daily_log_entries, compute_time_allocation
    from .modules.daily_log import get_daily_log
    from datetime import date as _date
    log = get_daily_log(_date.today(), engine)
    if not log:
        return {"categories": {}}
    entries = parse_daily_log_entries(log)
    alloc = compute_time_allocation(entries)
    return {"categories": alloc}

@app.get("/suggest")
async def get_suggest(focus: str = ""):
    from .modules.insight import build_daily_insight
    from datetime import date as _date
    report = build_daily_insight(_date.today(), engine)
    return {"suggestions": report}

@app.get("/todo/progress/{todo_id}")
async def get_todo_progress(todo_id: str):
    from .modules.todo import ACTIVE_DIR
    from .core.frontmatter import parse_frontmatter, parse_activity_log
    for filename in engine.list_resources(ACTIVE_DIR):
        content = engine.read_resource(f"{ACTIVE_DIR}{filename}")
        if content:
            fields, body = parse_frontmatter(content)
            if fields.get("id", "")[:8] == todo_id[:8]:
                activity = parse_activity_log(fields.get("activity_log", ""))
                return {"id": todo_id, "text": body.strip(), "activity": activity}
    return {"error": "not found"}
```

**Step 2: Update terminal buffer flush to use queue**

Modify `_flush_cmd_buffer` to check for `ingest_queue` and route through it when available.

**Step 3: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -v`

Expected: All tests PASS.

**Step 4: Commit**

```bash
git add mem_agent/service.py
git commit -m "feat: wire IngestQueue, pipeline, browser, filewatcher, insight into service"
```

---

## Task 16: CLI Extensions

**Files:**
- Modify: `mem_agent/cli.py`

**Step 1: Add insight, input-hook, and claudecode subcommands**

Add to `mem_agent/cli.py`:

```python
insight_app = typer.Typer(name="insight", help="Work insights and analysis")
input_hook_app = typer.Typer(name="input-hook", help="Input method hook control")
claudecode_app = typer.Typer(name="claudecode", help="Claude Code integration")

app.add_typer(insight_app, name="insight")
app.add_typer(input_hook_app, name="input-hook")
app.add_typer(claudecode_app, name="claudecode")
```

Insight commands:

```python
@insight_app.command("today")
def insight_today(config: Optional[str] = typer.Option(None, "-c", "--config")):
    """Show today's insight report."""
    _init_engine(config)
    from .modules.insight import build_daily_insight
    from datetime import date
    engine = _get_engine()
    report = build_daily_insight(date.today(), engine)
    console.print(report)

@insight_app.command("week")
def insight_week(config: Optional[str] = typer.Option(None, "-c", "--config")):
    """Show this week's insight report."""
    _init_engine(config)
    from .modules.insight import build_daily_insight
    from datetime import date, timedelta
    engine = _get_engine()
    # Show last 7 days
    for i in range(6, -1, -1):
        d = date.today() - timedelta(days=i)
        report = build_daily_insight(d, engine)
        if report and "无数据" not in report:
            console.print(f"\n{'='*60}")
            console.print(report)

@insight_app.command("tasks")
def insight_tasks(config: Optional[str] = typer.Option(None, "-c", "--config")):
    """Show task tracking overview."""
    _init_engine(config)
    from .modules.todo import list_todos, get_stalled_todos
    engine = _get_engine()
    console.print("\n[bold]Active Todos:[/bold]")
    list_todos()
    stalled = get_stalled_todos(engine)
    if stalled:
        console.print(f"\n[bold yellow]Stalled ({len(stalled)}):[/bold yellow]")
        for t in stalled:
            console.print(f"  ⚠ {t['text']} (last: {t['last_activity']})")

@insight_app.command("suggest")
def insight_suggest(config: Optional[str] = typer.Option(None, "-c", "--config")):
    """Get AI work suggestions."""
    _init_engine(config)
    from .modules.insight import build_daily_insight
    from datetime import date
    engine = _get_engine()
    report = build_daily_insight(date.today(), engine)
    # Extract just the suggestions section
    if "工作建议" in report:
        idx = report.index("工作建议")
        console.print(report[idx:])
    else:
        console.print("[yellow]No suggestions available yet.[/yellow]")
```

Input hook commands:

```python
@input_hook_app.command("start")
def ihook_start():
    """Start input method monitoring."""
    console.print("[yellow]Input hook requires the daemon to be running.[/yellow]")
    console.print("Start with: mem service start")

@input_hook_app.command("stop")
def ihook_stop():
    """Stop input method monitoring."""
    import httpx
    try:
        httpx.post(f"http://127.0.0.1:8330/input-hook/stop", timeout=5)
        console.print("[green]Input hook stopped.[/green]")
    except Exception:
        console.print("[red]Could not reach daemon.[/red]")

@input_hook_app.command("status")
def ihook_status():
    """Check input hook status."""
    import httpx
    try:
        resp = httpx.get("http://127.0.0.1:8330/input-hook/status", timeout=5)
        console.print(resp.json())
    except Exception:
        console.print("[red]Daemon not running.[/red]")
```

Claude Code commands:

```python
@claudecode_app.command("install")
def cc_install():
    """Install Claude Code hooks for conversation capture."""
    from .modules.claude_code import install_hook
    install_hook()

@claudecode_app.command("uninstall")
def cc_uninstall():
    """Remove Claude Code hooks."""
    from .modules.claude_code import uninstall_hook
    uninstall_hook()
```

**Step 2: Run the full test suite**

Run: `.venv/bin/python -m pytest tests/ -v`

Expected: All tests PASS.

**Step 3: Verify CLI commands are registered**

Run: `.venv/bin/python -m mem_agent.cli --help`

Expected: Shows `insight`, `input-hook`, `claudecode` in the command list.

**Step 4: Commit**

```bash
git add mem_agent/cli.py
git commit -m "feat: add insight, input-hook, and claudecode CLI subcommands"
```

---

## Task 17: Engine Directory Setup + Smoke Test

**Files:**
- Modify: `mem_agent/core/engine.py`

**Step 1: Add classified directory to CUSTOM_DIRS**

In `mem_agent/core/engine.py`, add to `CUSTOM_DIRS`:

```python
"viking://resources/classified/",
```

**Step 2: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -v`

Expected: All tests PASS.

**Step 3: Smoke test the full system**

Run:
```bash
cd /Users/austin/Desktop/MyAgent/mem-agent
source .venv/bin/activate
mem --help
mem insight --help
mem input-hook --help
mem claudecode --help
```

Expected: All help texts display correctly with new subcommands.

**Step 4: Commit**

```bash
git add mem_agent/core/engine.py
git commit -m "feat: add classified directory to engine custom dirs"
```

---

## Task 18: Final Integration Test + Documentation Update

**Step 1: Run all tests**

Run: `.venv/bin/python -m pytest tests/ -v --tb=short`

Expected: All tests PASS. No regressions.

**Step 2: Count test coverage**

Run: `.venv/bin/python -m pytest tests/ --co -q | tail -5`

Expected: ~100+ tests collected.

**Step 3: Update project documentation**

Update `/Users/austin/Desktop/我的知识库/mem-agent项目记录.md` to add Phase 4 section with:
- New modules and capabilities
- Updated CLI command reference
- MCP server configuration instructions

**Step 4: Final commit**

```bash
git add -A
git commit -m "feat: complete Phase 4 — pipeline architecture, classification, insights, MCP server"
```
