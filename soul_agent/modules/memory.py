"""Long-term memory extraction — distill persistent memory fragments from insights.

Extracts 3-5 memory fragments from daily insight reports via LLM,
deduplicates against existing memories, and persists to vault.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import TYPE_CHECKING, Any

from ..core.frontmatter import build_frontmatter, parse_frontmatter
from ..core.llm import call_deepseek

if TYPE_CHECKING:
    from ..core.vault import VaultEngine

MEMORIES_DIR = "memories"

VALID_CATEGORIES = {"preference", "pattern", "decision", "learning", "belief"}

_EXTRACT_SYSTEM = (
    "你是一个记忆提炼助手。从用户的每日洞察报告中提取值得长期记住的记忆片段。"
    "只提取有持久价值的内容：用户偏好、行为模式、重要决策、学到的经验、核心信念。"
    "不要提取临时性的事件细节。"
)

_EXTRACT_PROMPT_TEMPLATE = (
    "从以下每日洞察报告中提炼 3-5 条值得长期记住的记忆片段。\n\n"
    "报告内容：\n{report}\n\n"
    "要求：\n"
    "- 每条记忆是一个独立的、可长期保留的观察或结论\n"
    "- category 必须是以下之一：preference, pattern, decision, learning, belief\n"
    "- importance 范围 1-5，5 最重要\n"
    "- tags 用英文逗号分隔\n\n"
    '请严格返回 JSON 数组，格式：\n'
    '[{{"text": "记忆内容", "category": "pattern", "importance": 4, "tags": "focus,deep-work"}}]\n'
    "只输出 JSON，不要其他内容。"
)


def extract_memories(
    insight_report: str,
    target_date: date,
    engine: VaultEngine,
) -> list[dict[str, Any]]:
    """Extract persistent memory fragments from a daily insight report.

    1. Call LLM to extract memory candidates
    2. Deduplicate against existing memories
    3. Write new memories to vault
    4. Return the extracted memories
    """
    if not insight_report or not insight_report.strip():
        return []

    # Skip reports with no real content
    if "无数据" in insight_report or len(insight_report) < 100:
        return []

    raw_memories = _llm_extract(insight_report, engine)
    if not raw_memories:
        return []

    existing = _load_existing_memories(engine)
    new_memories = _deduplicate(raw_memories, existing)

    saved: list[dict[str, Any]] = []
    for seq, mem in enumerate(new_memories, start=1):
        _save_memory(mem, target_date, seq, engine)
        saved.append(mem)

    return saved


def _llm_extract(report: str, engine: VaultEngine) -> list[dict[str, Any]]:
    """Call LLM to extract memory fragments from report."""
    prompt = _EXTRACT_PROMPT_TEMPLATE.format(report=report[:3000])

    # Inject soul context for personality-aware extraction
    system = _EXTRACT_SYSTEM
    try:
        from .soul import get_soul_context
        soul = get_soul_context(engine)
        if soul:
            system = f"用户画像：\n{soul}\n\n{system}"
    except Exception:
        pass

    response = call_deepseek(
        prompt=prompt,
        system=system,
        max_tokens=800,
        config=engine.config,
    )

    if not response:
        return _fallback_extract(report)

    return _parse_llm_response(response)


def _parse_llm_response(response: str) -> list[dict[str, Any]]:
    """Parse LLM JSON response into memory dicts."""
    # Try to extract JSON array from response
    response = response.strip()

    # Handle markdown code blocks
    if "```" in response:
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", response, re.DOTALL)
        if match:
            response = match.group(1).strip()

    try:
        items = json.loads(response)
    except json.JSONDecodeError:
        # Try to find array in response
        match = re.search(r"\[.*\]", response, re.DOTALL)
        if match:
            try:
                items = json.loads(match.group(0))
            except json.JSONDecodeError:
                return []
        else:
            return []

    if not isinstance(items, list):
        return []

    memories: list[dict[str, Any]] = []
    for item in items[:5]:  # Cap at 5
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if not text:
            continue

        category = str(item.get("category", "learning")).strip()
        if category not in VALID_CATEGORIES:
            category = "learning"

        importance = item.get("importance", 3)
        if not isinstance(importance, int) or importance < 1 or importance > 5:
            importance = 3

        tags = str(item.get("tags", "")).strip()

        memories.append({
            "text": text,
            "category": category,
            "importance": importance,
            "tags": tags,
        })

    return memories


def _fallback_extract(report: str) -> list[dict[str, Any]]:
    """Rule-based fallback when LLM is unavailable."""
    memories: list[dict[str, Any]] = []

    # Extract items from "洞察与建议" section
    in_insight = False
    for line in report.split("\n"):
        line = line.strip()
        if "洞察与建议" in line:
            in_insight = True
            continue
        if in_insight and line.startswith("##"):
            break
        if in_insight and line.startswith("- ") and len(line) > 10:
            memories.append({
                "text": line[2:].strip(),
                "category": "learning",
                "importance": 3,
                "tags": "",
            })

    return memories[:3]


def _load_existing_memories(engine: VaultEngine) -> list[str]:
    """Load text of all existing memory fragments."""
    texts: list[str] = []
    for filename in engine.list_resources(MEMORIES_DIR):
        content = engine.read_resource(f"{MEMORIES_DIR}/{filename}")
        if content:
            _, body = parse_frontmatter(content)
            if body.strip():
                texts.append(body.strip())
    return texts


def _deduplicate(
    candidates: list[dict[str, Any]],
    existing_texts: list[str],
) -> list[dict[str, Any]]:
    """Remove candidates that are semantically similar to existing memories.

    Uses simple token overlap for now (no embedding model).
    """
    if not existing_texts:
        return candidates

    result: list[dict[str, Any]] = []
    for candidate in candidates:
        if not _is_duplicate(candidate["text"], existing_texts):
            result.append(candidate)
    return result


def _is_duplicate(text: str, existing: list[str], threshold: float = 0.6) -> bool:
    """Check if text is a duplicate of any existing memory via token overlap."""
    tokens_new = set(_tokenize(text))
    if not tokens_new:
        return False

    for existing_text in existing:
        tokens_old = set(_tokenize(existing_text))
        if not tokens_old:
            continue
        overlap = len(tokens_new & tokens_old)
        smaller = min(len(tokens_new), len(tokens_old))
        if smaller > 0 and overlap / smaller >= threshold:
            return True
    return False


def _tokenize(text: str) -> list[str]:
    """Simple tokenizer: split on whitespace and punctuation."""
    return [t.lower() for t in re.split(r"[\s,，。！？；：、\.\!\?\;\:]+", text) if len(t) > 1]


def _save_memory(
    mem: dict[str, Any],
    target_date: date,
    seq: int,
    engine: VaultEngine,
) -> None:
    """Write a memory fragment to the vault."""
    fields = {
        "type": "memory",
        "source_date": target_date.isoformat(),
        "category": mem["category"],
        "importance": str(mem["importance"]),
        "tags": mem["tags"],
    }
    content = build_frontmatter(fields, mem["text"])
    filename = f"{target_date.isoformat()}-{seq}.md"
    engine.write_resource(content=content, directory=MEMORIES_DIR, filename=filename)


def load_high_importance_memories(
    engine: VaultEngine,
    min_importance: int = 4,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Load memory fragments with importance >= threshold.

    Returns list of {text, category, importance, tags, source_date}.
    """
    memories: list[dict[str, Any]] = []
    for filename in engine.list_resources(MEMORIES_DIR):
        content = engine.read_resource(f"{MEMORIES_DIR}/{filename}")
        if not content:
            continue
        fields, body = parse_frontmatter(content)
        try:
            importance = int(fields.get("importance", "0"))
        except ValueError:
            importance = 0
        if importance >= min_importance and body.strip():
            memories.append({
                "text": body.strip(),
                "category": fields.get("category", ""),
                "importance": importance,
                "tags": fields.get("tags", ""),
                "source_date": fields.get("source_date", ""),
            })
            if len(memories) >= limit:
                break
    return memories


def list_all_memories(engine: VaultEngine) -> list[dict[str, Any]]:
    """List all memory fragments with metadata."""
    memories: list[dict[str, Any]] = []
    for filename in engine.list_resources(MEMORIES_DIR):
        content = engine.read_resource(f"{MEMORIES_DIR}/{filename}")
        if not content:
            continue
        fields, body = parse_frontmatter(content)
        try:
            importance = int(fields.get("importance", "0"))
        except ValueError:
            importance = 0
        memories.append({
            "text": body.strip(),
            "category": fields.get("category", ""),
            "importance": importance,
            "tags": fields.get("tags", ""),
            "source_date": fields.get("source_date", ""),
            "filename": filename,
        })
    return memories


def search_memories_by_query(
    query: str,
    engine: VaultEngine,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Search memory fragments by keyword."""
    return engine.search(query=query, directory=MEMORIES_DIR, limit=limit)
