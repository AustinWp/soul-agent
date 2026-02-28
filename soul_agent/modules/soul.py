"""Soul engine — persistent user profile that evolves from daily insights.

The soul (core/SOUL.md) captures identity, traits, work style, preferences,
values, and current focus. It auto-evolves after each daily insight cycle,
and is injected into all LLM calls for personalised context.
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

SOUL_PATH = "core/SOUL.md"
SOUL_SECTIONS = ["身份", "性格特质", "工作风格", "偏好与习惯", "核心价值观", "近期关注", "成长轨迹"]

_INIT_SYSTEM = (
    "你是一个用户画像整理助手。将用户提供的自我描述整理成标准分节格式。"
    "保留用户原意，不要虚构信息。如果某个分节没有对应信息，写'（待发现）'。"
)

_INIT_PROMPT_TEMPLATE = (
    "将以下自我描述整理成标准灵魂画像格式。\n\n"
    "用户描述：\n{preset}\n\n"
    "请输出以下分节（每节用 ## 开头）：\n"
    "## 身份\n## 性格特质\n## 工作风格\n## 偏好与习惯\n## 核心价值观\n## 近期关注\n\n"
    "每节用简洁的描述，1-3行即可。只输出分节内容，不要其他。"
)

_CHAT_SYSTEM = (
    "你是用户的数字灵魂。你拥有用户的画像、近期记忆和洞察报告。"
    "基于这些真实上下文回答用户的问题，给出个性化的建议和回答。"
    "不要编造你不知道的信息。如果上下文不足以回答，坦诚说明。"
    "用中文回答，风格简洁、真诚、有洞察力。"
)

_CHAT_PROMPT_TEMPLATE = (
    "以下是关于用户的上下文信息：\n\n{context}\n\n"
    "用户的问题：{question}\n\n"
    "请基于以上上下文给出个性化的回答。"
)

_EVOLVE_SYSTEM = (
    "你是一个灵魂画像演进助手。根据用户的新记忆和洞察报告，判断灵魂画像的哪些部分需要更新。"
    "只更新有实质性变化的部分，保守更新——宁可不改也不要乱改。"
)

_EVOLVE_PROMPT_TEMPLATE = (
    "当前灵魂画像：\n{current_soul}\n\n"
    "新记忆片段：\n{memories}\n\n"
    "今日洞察报告摘要：\n{insight}\n\n"
    "请判断灵魂画像的哪些分节需要更新。\n"
    "规则：\n"
    "- 只返回需要更新的分节，不需要更新的不要包含\n"
    "- 不要更新'成长轨迹'（系统会自动追加）\n"
    "- 如果没有任何分节需要更新，返回空对象 {{}}\n"
    "- 更新内容应该是该分节的完整新内容（不是增量）\n\n"
    '请严格返回 JSON 对象，格式：{{"分节名": "新内容", ...}}\n'
    "只输出 JSON，不要其他内容。"
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_soul(engine: VaultEngine) -> str | None:
    """Read SOUL.md full content. Returns None if not found."""
    return engine.read_resource(SOUL_PATH)


def get_soul_context(engine: VaultEngine) -> str:
    """Return soul summary (first 6 sections, without growth log) for LLM injection."""
    content = load_soul(engine)
    if not content:
        return ""

    _, body = parse_frontmatter(content)
    if not body.strip():
        return ""

    sections = _parse_sections(body)
    context_parts: list[str] = []
    for name in SOUL_SECTIONS:
        if name == "成长轨迹":
            continue
        if name in sections and sections[name].strip() and sections[name].strip() != "（待发现）":
            context_parts.append(f"【{name}】{sections[name].strip()}")

    return "\n".join(context_parts)


def init_soul(preset: str, engine: VaultEngine) -> str:
    """Initialize SOUL.md from a user-provided preset text.

    If preset already has standard section structure, writes directly.
    Otherwise, uses LLM to format into standard sections.
    """
    today = date.today().isoformat()

    # Check if preset is already structured (has at least 3 of our sections)
    section_count = sum(1 for s in SOUL_SECTIONS if f"## {s}" in preset)
    if section_count >= 3:
        body = preset.strip()
        # Ensure growth log section exists
        if "## 成长轨迹" not in body:
            body += f"\n\n## 成长轨迹\n- {today}: 灵魂初始化"
    else:
        body = _llm_format_soul(preset, engine)
        if not body:
            body = _fallback_format_soul(preset)
        body += f"\n\n## 成长轨迹\n- {today}: 灵魂初始化"

    # Prepend the title
    full_body = f"# 我的数字灵魂\n\n{body}"

    fields = {
        "type": "soul",
        "version": "1",
        "last_evolved": today,
        "evolution_count": "0",
    }
    content = build_frontmatter(fields, full_body)

    engine.write_resource(content=content, directory="core", filename="SOUL.md")
    return content


def evolve_soul(
    new_memories: list[dict[str, Any]],
    insight_report: str,
    engine: VaultEngine,
) -> bool:
    """Evolve the soul based on new memories and today's insight.

    Returns True if the soul was updated, False otherwise.
    """
    current = load_soul(engine)
    if not current:
        return False

    fields, body = parse_frontmatter(current)

    # Build memory text for the prompt
    memory_lines: list[str] = []
    for m in new_memories[:10]:
        text = m.get("text", "")
        if text:
            memory_lines.append(f"- {text}")
    memory_text = "\n".join(memory_lines) if memory_lines else "（无新记忆）"

    # Truncate insight for prompt
    insight_text = insight_report[:2000] if insight_report else "（无洞察）"

    updates = _llm_evolve(body, memory_text, insight_text, engine)
    if not updates:
        return False

    # Merge updates into current soul
    today = date.today()
    new_body = _merge_sections(body, updates, today)

    # Update frontmatter
    evolution_count = int(fields.get("evolution_count", "0")) + 1
    fields["last_evolved"] = today.isoformat()
    fields["evolution_count"] = str(evolution_count)

    content = build_frontmatter(fields, new_body)
    engine.write_resource(content=content, directory="core", filename="SOUL.md")
    return True


# ---------------------------------------------------------------------------
# Section parsing & merging
# ---------------------------------------------------------------------------

def _parse_sections(body: str) -> dict[str, str]:
    """Parse markdown ## sections into a dict.

    Returns {section_name: content_text}.
    """
    sections: dict[str, str] = {}
    current_name: str | None = None
    current_lines: list[str] = []

    for line in body.split("\n"):
        if line.startswith("## "):
            if current_name is not None:
                sections[current_name] = "\n".join(current_lines).strip()
            current_name = line[3:].strip()
            current_lines = []
        elif current_name is not None:
            current_lines.append(line)

    if current_name is not None:
        sections[current_name] = "\n".join(current_lines).strip()

    return sections


def _merge_sections(current_body: str, updates: dict[str, str], today: date) -> str:
    """Merge LLM section updates back into the soul body.

    Also appends a growth log entry summarizing what changed.
    """
    sections = _parse_sections(current_body)

    # Apply updates (skip 成长轨迹 — we handle it separately)
    changed_names: list[str] = []
    for name, new_content in updates.items():
        if name == "成长轨迹":
            continue
        if name in SOUL_SECTIONS:
            sections[name] = new_content.strip()
            changed_names.append(name)

    # Append growth log entry
    growth = sections.get("成长轨迹", "")
    change_desc = "、".join(changed_names) if changed_names else "微调"
    growth += f"\n- {today.isoformat()}: 演进 — {change_desc}更新"
    sections["成长轨迹"] = growth.strip()

    # Rebuild body preserving section order
    lines: list[str] = ["# 我的数字灵魂", ""]
    for name in SOUL_SECTIONS:
        if name in sections:
            lines.append(f"## {name}")
            lines.append(sections[name])
            lines.append("")

    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# LLM calls
# ---------------------------------------------------------------------------

def _llm_format_soul(preset: str, engine: VaultEngine) -> str:
    """Use LLM to format free-text preset into standard sections."""
    prompt = _INIT_PROMPT_TEMPLATE.format(preset=preset[:2000])

    response = call_deepseek(
        prompt=prompt,
        system=_INIT_SYSTEM,
        max_tokens=600,
        config=engine.config,
    )
    return response or ""


def _llm_evolve(
    current_soul: str,
    memory_text: str,
    insight_text: str,
    engine: VaultEngine,
) -> dict[str, str]:
    """Call LLM to determine which sections need updating.

    Returns dict of {section_name: new_content} or empty dict.
    """
    prompt = _EVOLVE_PROMPT_TEMPLATE.format(
        current_soul=current_soul[:3000],
        memories=memory_text,
        insight=insight_text[:1500],
    )

    response = call_deepseek(
        prompt=prompt,
        system=_EVOLVE_SYSTEM,
        max_tokens=800,
        config=engine.config,
    )

    if not response:
        return {}

    return _parse_evolve_response(response)


def _parse_evolve_response(response: str) -> dict[str, str]:
    """Parse LLM JSON response into section updates dict."""
    response = response.strip()

    # Handle markdown code blocks
    if "```" in response:
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", response, re.DOTALL)
        if match:
            response = match.group(1).strip()

    try:
        result = json.loads(response)
    except json.JSONDecodeError:
        # Try to find JSON object in response
        match = re.search(r"\{.*\}", response, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group(0))
            except json.JSONDecodeError:
                return {}
        else:
            return {}

    if not isinstance(result, dict):
        return {}

    # Validate: only accept known sections
    valid: dict[str, str] = {}
    for key, value in result.items():
        if key in SOUL_SECTIONS and key != "成长轨迹" and isinstance(value, str) and value.strip():
            valid[key] = value
    return valid


def chat_with_soul(question: str, engine: VaultEngine) -> str:
    """Answer a user question based on soul profile + recent memories + latest insight."""
    # 1. Soul context
    soul_context = get_soul_context(engine)

    # 2. High-importance memories
    from .memory import load_high_importance_memories

    memories = load_high_importance_memories(engine, min_importance=3, limit=5)
    memory_lines = [f"- {m['text']}" for m in memories if m.get("text")]
    memory_text = "\n".join(memory_lines) if memory_lines else "（暂无重要记忆）"

    # 3. Latest insight report
    insight_text = _load_latest_insight(engine)

    # 4. Build prompt
    context_parts: list[str] = []
    if soul_context:
        context_parts.append(f"【灵魂画像】\n{soul_context}")
    context_parts.append(f"【近期重要记忆】\n{memory_text}")
    if insight_text:
        context_parts.append(f"【最新洞察报告】\n{insight_text}")

    full_context = "\n\n".join(context_parts)
    prompt = _CHAT_PROMPT_TEMPLATE.format(context=full_context, question=question)

    # 5. Call LLM
    response = call_deepseek(
        prompt=prompt,
        system=_CHAT_SYSTEM,
        max_tokens=800,
        config=engine.config,
    )

    # 6. Fallback
    if not response:
        if soul_context:
            return f"（LLM 暂时不可用，无法回答。以下是你的灵魂摘要供参考：）\n\n{soul_context}"
        return "（LLM 暂时不可用，且尚未建立灵魂画像。请先运行 `mem soul init`。）"

    return response


def _load_latest_insight(engine: VaultEngine) -> str:
    """Load the most recent daily insight report."""
    from .insight import INSIGHTS_DIR

    files = engine.list_resources(INSIGHTS_DIR)
    daily_files = sorted(
        [f for f in files if f.startswith("daily-")],
        reverse=True,
    )
    if not daily_files:
        return ""

    content = engine.read_resource(f"{INSIGHTS_DIR}/{daily_files[0]}")
    if not content:
        return ""

    _, body = parse_frontmatter(content)
    # Truncate to keep prompt reasonable
    return body.strip()[:2000]


def _fallback_format_soul(preset: str) -> str:
    """Rule-based fallback when LLM is unavailable."""
    lines: list[str] = []
    lines.append("## 身份")
    lines.append(preset.strip())
    lines.append("")
    for section in SOUL_SECTIONS[1:]:
        if section == "成长轨迹":
            continue
        lines.append(f"## {section}")
        lines.append("（待发现）")
        lines.append("")
    return "\n".join(lines).rstrip()
