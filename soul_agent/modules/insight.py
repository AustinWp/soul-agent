"""Insight engine — daily work analysis and recommendations.

Two-phase LLM analysis:
  Phase 1: Semantic understanding — extract what the user actually worked on
  Phase 2: Deep insights — generate actionable advice based on context
"""

from __future__ import annotations

import re
import threading
import time as _time
from collections import Counter
from datetime import date, datetime, time as dt_time
from typing import TYPE_CHECKING, Any

from ..core.frontmatter import (
    build_frontmatter,
    parse_frontmatter,
    parse_tags,
)
from ..core.llm import call_deepseek
from .daily_log import LOGS_DIR, get_daily_log
from .todo import ACTIVE_DIR, DONE_DIR, get_stalled_todos

if TYPE_CHECKING:
    from ..core.vault import VaultEngine

INSIGHTS_DIR = "insights"

# Matches: [HH:MM] (source) [category] text  OR  [HH:MM] (source) text
ENTRY_PATTERN = re.compile(
    r"\[(\d{2}:\d{2})\]\s+\(([^)]+)\)\s+(?:\[([^\]]+)\]\s+)?(.*)"
)

# Noise patterns to filter out
_NOISE_PATTERNS = [
    re.compile(r"\.tmp\b", re.IGNORECASE),
    re.compile(r"\.crdownload\b", re.IGNORECASE),
    re.compile(r"~\$"),  # Office temp lock files
    re.compile(r"\.DS_Store\b"),
]


# ---------------------------------------------------------------------------
# Preserved public helpers
# ---------------------------------------------------------------------------

def parse_daily_log_entries(log_content: str) -> list[dict]:
    """Parse daily log body into structured entries.

    Each entry: {"time", "source", "category", "text", "tags"}
    """
    if not log_content or not log_content.strip():
        return []

    _, body = parse_frontmatter(log_content)
    if not body.strip():
        return []

    entries: list[dict] = []
    for line in body.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        m = ENTRY_PATTERN.match(line)
        if m:
            time_str = m.group(1)
            source = m.group(2)
            category = m.group(3) or "uncategorized"
            text = m.group(4)
            tags = re.findall(r"#(\w+)", text)
            entries.append({
                "time": time_str,
                "source": source,
                "category": category,
                "text": text,
                "tags": tags,
            })
    return entries


def compute_time_allocation(entries: list[dict]) -> dict:
    """Count entries per category, compute percentages."""
    if not entries:
        return {}

    total = len(entries)
    allocation: dict[str, dict[str, Any]] = {}

    for entry in entries:
        cat = entry["category"]
        if cat not in allocation:
            allocation[cat] = {"count": 0, "percent": 0.0, "entries": []}
        allocation[cat]["count"] += 1
        allocation[cat]["entries"].append(entry["time"])

    for cat in allocation:
        allocation[cat]["percent"] = round(
            allocation[cat]["count"] / total * 100, 1
        )

    return allocation


def get_top_tags(entries: list[dict], n: int = 10) -> list[tuple[str, int]]:
    """Count tag frequencies across entries, return top N."""
    counter: Counter[str] = Counter()
    for entry in entries:
        for tag in entry.get("tags", []):
            counter[tag] += 1
    return counter.most_common(n)


# ---------------------------------------------------------------------------
# Phase 0: Data collection & noise filtering
# ---------------------------------------------------------------------------

def _is_noise(text: str) -> bool:
    """Check if an entry text matches known noise patterns."""
    for pat in _NOISE_PATTERNS:
        if pat.search(text):
            return True
    return False


def _dedup_browsing(entries: list[dict]) -> list[dict]:
    """Remove duplicate browsing entries, keeping only the first visit."""
    seen_urls: set[str] = set()
    result: list[dict] = []
    for entry in entries:
        if entry["source"] == "browsing":
            url_match = re.search(r"https?://\S+", entry["text"])
            key = url_match.group(0) if url_match else entry["text"]
            if key in seen_urls:
                continue
            seen_urls.add(key)
        result.append(entry)
    return result


def _time_period(time_str: str) -> str:
    """Classify HH:MM into a time period label."""
    hour = int(time_str.split(":")[0])
    if hour < 12:
        return "上午"
    if hour < 18:
        return "下午"
    return "晚上"


def _cluster_entries(entries: list[dict]) -> list[dict]:
    """Cluster consecutive same-category entries into summary groups."""
    if not entries:
        return []

    clusters: list[dict] = []
    current = {
        "period": _time_period(entries[0]["time"]),
        "start": entries[0]["time"],
        "end": entries[0]["time"],
        "category": entries[0]["category"],
        "texts": [entries[0]["text"]],
    }

    for entry in entries[1:]:
        same_cat = entry["category"] == current["category"]
        same_period = _time_period(entry["time"]) == current["period"]
        if same_cat and same_period:
            current["end"] = entry["time"]
            current["texts"].append(entry["text"])
        else:
            clusters.append(_finalize_cluster(current))
            current = {
                "period": _time_period(entry["time"]),
                "start": entry["time"],
                "end": entry["time"],
                "category": entry["category"],
                "texts": [entry["text"]],
            }

    clusters.append(_finalize_cluster(current))
    return clusters


def _finalize_cluster(cluster: dict) -> dict:
    """Convert raw cluster dict into its final summary form."""
    count = len(cluster["texts"])
    if count == 1:
        summary = cluster["texts"][0]
    else:
        summary = f"{cluster['texts'][0]} ... 等{count}项操作"

    time_range = cluster["start"]
    if cluster["end"] != cluster["start"]:
        time_range = f"{cluster['start']}-{cluster['end']}"

    return {
        "period": cluster["period"],
        "time_range": time_range,
        "category": cluster["category"],
        "summary": summary,
        "count": count,
    }


def _filter_and_cluster_entries(entries: list[dict]) -> tuple[list[dict], list[dict]]:
    """Filter noise and cluster entries."""
    cleaned = [e for e in entries if not _is_noise(e["text"])]
    cleaned = _dedup_browsing(cleaned)
    clusters = _cluster_entries(cleaned)
    return cleaned, clusters


def _get_active_todos_detail(engine: VaultEngine) -> list[dict[str, Any]]:
    """Get full details for all active todos."""
    todos: list[dict[str, Any]] = []

    for name in engine.list_resources(ACTIVE_DIR):
        if not name.endswith(".md") or name.startswith("."):
            continue
        rel_path = f"{ACTIVE_DIR}/{name}"
        try:
            content = engine.read_resource(rel_path)
            if not content:
                continue
            fields, body = parse_frontmatter(content)
            todos.append({
                "id": fields.get("id", name.replace(".md", "")),
                "text": body.strip(),
                "due": fields.get("due", ""),
                "priority": fields.get("priority_label", "normal"),
                "created": fields.get("created", ""),
            })
        except Exception:
            continue
    return todos


def _gather_insight_context(
    target_date: date,
    engine: VaultEngine,
) -> dict[str, Any] | None:
    """Aggregate multi-source data for insight generation."""
    log_content = get_daily_log(target_date, engine)
    if not log_content:
        return None

    all_entries = parse_daily_log_entries(log_content)
    if not all_entries:
        return None

    # Separate notes from automated entries
    notes = [e for e in all_entries if e["source"] == "note"]
    automated = [e for e in all_entries if e["source"] != "note"]

    filtered, clusters = _filter_and_cluster_entries(automated)
    all_filtered = sorted(filtered + notes, key=lambda e: e["time"])

    # Task data
    active_todos = _get_active_todos_detail(engine)
    stalled_todos: list[dict[str, Any]] = []
    try:
        stalled_todos = get_stalled_todos(engine, stale_days=3)
    except Exception:
        pass

    # Keyword search for related memories
    memories: list[str] = []
    try:
        date_str = target_date.isoformat()
        results = engine.search(date_str, limit=5)
        for r in results:
            snippet = r.get("snippet", "")
            if snippet:
                memories.append(snippet[:200])
    except Exception:
        pass

    # Load high-importance long-term memories
    long_term_memories: list[str] = []
    try:
        from .memory import load_high_importance_memories

        hi_mems = load_high_importance_memories(engine, min_importance=4, limit=5)
        for m in hi_mems:
            long_term_memories.append(m["text"][:200])
    except Exception:
        pass

    # Load soul context for personalised insights
    soul_context = ""
    try:
        from .soul import get_soul_context
        soul_context = get_soul_context(engine)
    except Exception:
        pass

    return {
        "entries": all_filtered,
        "notes": notes,
        "clusters": clusters,
        "active_todos": active_todos,
        "stalled_todos": stalled_todos,
        "memories": memories,
        "long_term_memories": long_term_memories,
        "soul": soul_context,
    }


# ---------------------------------------------------------------------------
# Phase 1: Semantic understanding
# ---------------------------------------------------------------------------

def _summarize_work(
    context: dict[str, Any],
    engine: VaultEngine,
) -> str:
    """Phase 1 LLM call: extract work items from raw log data."""
    cluster_lines: list[str] = []
    for c in context["clusters"]:
        cluster_lines.append(
            f"[{c['time_range']}] [{c['category']}] {c['summary']}"
        )
    clustered_text = "\n".join(cluster_lines) if cluster_lines else "（无自动记录）"

    notes_lines: list[str] = []
    for n in context["notes"]:
        notes_lines.append(f"[{n['time']}] {n['text']}")
    notes_text = "\n".join(notes_lines) if notes_lines else "（无手动笔记）"

    prompt = (
        "根据以下原始工作日志，提炼出用户今天实际做的工作事项。\n"
        "忽略具体文件名和技术细节，聚焦于：做了什么事、为什么做、产出是什么。\n\n"
        "用户日志：\n"
        f"{clustered_text}\n\n"
        "用户笔记：\n"
        f"{notes_text}\n\n"
        "请用简洁的列表输出今天的工作事项，每项一行，用 - 开头。"
    )

    summary = call_deepseek(
        prompt=prompt,
        system="你是一个工作日志分析助手。从原始日志中提取用户真正做了什么，输出简洁的工作事项列表。",
        max_tokens=300,
        config=engine.config,
    )
    return summary or "- 暂无法总结今日工作"


# ---------------------------------------------------------------------------
# Phase 2: Deep insights
# ---------------------------------------------------------------------------

def _generate_insights(
    work_summary: str,
    context: dict[str, Any],
    engine: VaultEngine,
) -> str:
    """Phase 2 LLM call: generate actionable insights."""
    active_lines: list[str] = []
    for t in context["active_todos"]:
        due = f"（截止: {t['due']}）" if t["due"] else ""
        active_lines.append(f"- [{t['priority']}] {t['text'][:80]}{due}")
    active_text = "\n".join(active_lines) if active_lines else "（无活跃任务）"

    stalled_lines: list[str] = []
    for s in context["stalled_todos"]:
        stalled_lines.append(
            f"- {s['text'][:80]}（最后活动: {s.get('last_activity', '未知')}）"
        )
    stalled_text = "\n".join(stalled_lines) if stalled_lines else "（无停滞任务）"

    memory_text = ""
    if context["memories"]:
        memory_text = "\n相关历史记忆：\n" + "\n".join(
            f"- {m}" for m in context["memories"]
        )
    if context.get("long_term_memories"):
        memory_text += "\n用户长期记忆：\n" + "\n".join(
            f"- {m}" for m in context["long_term_memories"]
        )

    prompt = (
        "基于今日工作总结和任务上下文，给出有价值的洞察。\n\n"
        "要求：\n"
        "- 不要给出\"少切标签\"\"多休息\"\"注意文件管理\"这种表面建议\n"
        "- 聚焦于：未完成的关键事项、可能被遗忘的后续行动、工作优先级判断、值得深入的方向\n"
        "- 如果有会议纪要或笔记，提取未落实的 action items\n"
        "- 结合活跃任务和停滞任务，指出哪些任务需要立即关注\n"
        "- 输出 2-4 条洞察，每条用 - 开头，配简短说明\n\n"
        "今日工作总结：\n"
        f"{work_summary}\n\n"
        "活跃任务：\n"
        f"{active_text}\n\n"
        "停滞任务：\n"
        f"{stalled_text}"
        f"{memory_text}"
    )

    soul_prefix = ""
    soul = context.get("soul", "")
    if soul:
        soul_prefix = f"用户画像：\n{soul}\n\n"

    insights = call_deepseek(
        prompt=prompt,
        system=(
            f"{soul_prefix}"
            "你是用户的私人工作顾问。基于用户的工作内容和任务状态，"
            "给出有决策价值的洞察和建议。直接输出建议列表，不要寒暄。"
        ),
        max_tokens=512,
        config=engine.config,
    )
    return insights or "- 暂无洞察"


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------

def build_daily_insight(target_date: date, engine: VaultEngine) -> str:
    """Build a daily insight markdown report."""
    context = _gather_insight_context(target_date, engine)
    if context is None:
        return f"# 每日洞察 — {target_date.isoformat()}\n\n无数据"

    work_summary = _summarize_work(context, engine)
    insights = _generate_insights(work_summary, context, engine)
    allocation = compute_time_allocation(context["entries"])

    lines: list[str] = []
    lines.append(f"# 每日洞察 — {target_date.isoformat()}")
    lines.append("")

    lines.append("## 今日工作总结")
    lines.append("")
    lines.append(work_summary)
    lines.append("")

    lines.append("## 任务状态")
    lines.append("")
    active = context["active_todos"]
    stalled = context["stalled_todos"]
    if active:
        lines.append(f"**活跃任务** ({len(active)})")
        lines.append("")
        for t in active:
            due = f" | 截止: {t['due']}" if t["due"] else ""
            lines.append(f"- {t['text'][:80]}{due}")
        lines.append("")
    else:
        lines.append("暂无活跃任务")
        lines.append("")

    if stalled:
        lines.append(f"**停滞任务** ({len(stalled)}) ⚠")
        lines.append("")
        for s in stalled:
            lines.append(
                f"- {s['text'][:80]}（最后活动: {s.get('last_activity', '未知')}）"
            )
        lines.append("")

    lines.append("## 洞察与建议")
    lines.append("")
    lines.append(insights)
    lines.append("")

    lines.append("## 时间分布")
    lines.append("")
    if allocation:
        for cat, info in sorted(
            allocation.items(), key=lambda x: -x[1]["count"]
        ):
            lines.append(
                f"- **{cat}**: {info['count']}条 ({info['percent']}%)"
            )
    else:
        lines.append("暂无数据")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Persistence & scheduling
# ---------------------------------------------------------------------------

def save_daily_insight(target_date: date, engine: VaultEngine) -> str:
    """Generate and save daily insight report."""
    report = build_daily_insight(target_date, engine)

    filename = f"daily-{target_date.isoformat()}.md"
    fields = {"date": target_date.isoformat(), "type": "daily-insight"}
    content = build_frontmatter(fields, report)

    engine.write_resource(
        content=content,
        directory=INSIGHTS_DIR,
        filename=filename,
    )

    # Extract long-term memories from the insight report
    memories: list = []
    if report and "无数据" not in report:
        try:
            from .memory import extract_memories

            memories = extract_memories(report, target_date, engine)
        except Exception:
            pass

    # Trigger soul evolution if new memories were extracted
    if memories:
        try:
            from .soul import evolve_soul

            evolve_soul(memories, report, engine)
        except Exception:
            pass

    return report


def _insight_loop(engine: VaultEngine, running: threading.Event) -> None:
    """Background loop that generates daily insight at 20:00."""
    generated_today = False
    while running.is_set():
        now = datetime.now()
        current_time = now.time()
        target_time = dt_time(20, 0)

        if current_time >= target_time and not generated_today:
            try:
                save_daily_insight(now.date(), engine)
            except Exception:
                pass
            generated_today = True

        if current_time < dt_time(0, 1):
            generated_today = False

        if not running.is_set():
            break
        for _ in range(60):
            if not running.is_set():
                return
            _time.sleep(1)


def start_insight_thread(
    engine: VaultEngine,
) -> tuple[threading.Thread, threading.Event]:
    """Start background thread that generates daily insight at 20:00."""
    running = threading.Event()
    running.set()
    thread = threading.Thread(
        target=_insight_loop,
        args=(engine, running),
        daemon=True,
        name="insight",
    )
    thread.start()
    return thread, running
