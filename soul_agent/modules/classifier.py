"""LLM-powered batch classifier for ingest items.

Classifies IngestItems into categories with importance scores, tags,
summaries, and optional action types using DeepSeek.  Falls back to
rule-based classification when the LLM is unavailable.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..core.llm import call_deepseek
from ..core.queue import ClassifiedItem, IngestItem

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_CATEGORIES = {"coding", "work", "learning", "communication", "browsing", "life"}

SOURCE_CATEGORY_MAP: dict[str, str] = {
    "terminal": "coding",
    "browser": "browsing",
    "claude-code": "coding",
    "input-method": "communication",
}

SYSTEM_PROMPT = (
    "你是一个个人记忆助手的分类引擎。"
    "将每个条目分类到恰好一个类别，并返回结构化 JSON。"
    "所有文本字段（summary、action_detail）必须使用中文输出。"
)

BATCH_PROMPT_TEMPLATE = """\
对以下每个条目进行分类。每个条目返回一个 JSON 对象，包含：
- "category": {valid_categories} 中的一个
- "tags": 简短关键词列表（中文）
- "importance": 整数 1-5（1=琐碎, 5=关键）
- "summary": 一句话中文摘要
- "action_type": null、"new_task" 或 "update_task"
- "action_detail": 字符串或 null — 如果有 action_type 则用中文描述该动作
- "related_todo_id": 字符串或 null — 如果是更新已有待办则填其 ID

action_type 严格规则（必须遵守）：
1. 来源为 file、browser、clipboard 的条目：action_type 必须为 null，不得创建任务
2. importance <= 2 的条目：action_type 必须为 null
3. 优先使用 "update_task" 关联已有待办，而非创建新任务
4. 只有用户明确表达了意图（如笔记、终端命令中的 TODO）才可以 "new_task"
5. "评估 X"、"探索 Y"、"了解 Z" 类描述不应创建任务

返回一个恰好包含 {count} 个对象的 JSON 数组（与条目顺序一致）。
不要用 markdown 代码块包裹输出。

{todo_context}

条目：
{items_block}
"""

# ---------------------------------------------------------------------------
# Fallback (rule-based) classification
# ---------------------------------------------------------------------------


def fallback_classify(text: str, source: str) -> dict[str, Any]:
    """Rule-based classification used when the LLM is unavailable.

    Returns a dict with the same keys as an LLM classification result.
    """
    category = SOURCE_CATEGORY_MAP.get(source, "work")
    return {
        "category": category,
        "tags": [],
        "importance": 3,
        "summary": "",
        "action_type": None,
        "action_detail": None,
        "related_todo_id": None,
    }


# ---------------------------------------------------------------------------
# LLM response parsing
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)


def _parse_llm_response(raw: str, count: int) -> list[dict[str, Any]]:
    """Parse the LLM JSON response into a list of classification dicts.

    Handles optional markdown code fences (```json ... ```).
    Returns an empty list on any parse failure or count mismatch.
    """
    text = raw.strip()
    if not text:
        return []

    # Strip markdown fences if present
    fence_match = _FENCE_RE.search(text)
    if fence_match:
        text = fence_match.group(1).strip()

    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return []

    if not isinstance(parsed, list):
        return []

    if len(parsed) != count:
        return []

    return parsed


# ---------------------------------------------------------------------------
# Batch classification
# ---------------------------------------------------------------------------


def classify_batch(
    items: list[IngestItem],
    active_todos: list[Any],
    config: dict[str, Any] | None = None,
) -> list[ClassifiedItem]:
    """Classify a batch of IngestItems via DeepSeek LLM.

    Falls back to rule-based classification for any item where the LLM
    did not produce a valid result.
    """
    if not items:
        return []

    # Build the todo context block
    if active_todos:
        todo_lines = []
        for t in active_todos:
            tid = t.get("id", "?") if isinstance(t, dict) else getattr(t, "id", "?")
            txt = t.get("text", "") if isinstance(t, dict) else getattr(t, "text", "")
            todo_lines.append(f"  - [{tid}] {txt}")
        todo_context = "Active todos:\n" + "\n".join(todo_lines)
    else:
        todo_context = "No active todos."

    # Build items block
    items_block_parts: list[str] = []
    for idx, item in enumerate(items):
        items_block_parts.append(
            f"{idx + 1}. [{item.source}] {item.text}"
        )
    items_block = "\n".join(items_block_parts)

    prompt = BATCH_PROMPT_TEMPLATE.format(
        valid_categories=", ".join(sorted(VALID_CATEGORIES)),
        count=len(items),
        todo_context=todo_context,
        items_block=items_block,
    )

    raw = call_deepseek(prompt, system=SYSTEM_PROMPT, max_tokens=1024, config=config)
    parsed = _parse_llm_response(raw, count=len(items))

    results: list[ClassifiedItem] = []
    for idx, item in enumerate(items):
        if parsed and idx < len(parsed):
            entry = parsed[idx]
            category = entry.get("category", "")
            if category not in VALID_CATEGORIES:
                category = SOURCE_CATEGORY_MAP.get(item.source, "work")
            classified = ClassifiedItem(
                text=item.text,
                source=item.source,
                timestamp=item.timestamp,
                meta=item.meta,
                category=category,
                tags=entry.get("tags", []),
                importance=entry.get("importance", 3),
                summary=entry.get("summary", ""),
                action_type=entry.get("action_type"),
                action_detail=entry.get("action_detail"),
                related_todo_id=entry.get("related_todo_id"),
            )
        else:
            fb = fallback_classify(item.text, item.source)
            classified = ClassifiedItem(
                text=item.text,
                source=item.source,
                timestamp=item.timestamp,
                meta=item.meta,
                category=fb["category"],
                tags=fb["tags"],
                importance=fb["importance"],
                summary=fb["summary"],
                action_type=fb["action_type"],
                action_detail=fb["action_detail"],
                related_todo_id=fb["related_todo_id"],
            )
        results.append(classified)

    return results
