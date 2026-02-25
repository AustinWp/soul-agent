"""Insight engine — daily work analysis and recommendations."""

from __future__ import annotations

import re
import threading
from collections import Counter
from datetime import date, datetime, time as dt_time
from typing import TYPE_CHECKING, Any

from ..core.frontmatter import (
    add_lifecycle_fields,
    build_frontmatter,
    parse_frontmatter,
    parse_tags,
)
from ..core.llm import call_deepseek
from .daily_log import LOGS_DIR, get_daily_log
from .todo import ACTIVE_DIR, DONE_DIR, get_stalled_todos

if TYPE_CHECKING:
    from ..core.engine import MemEngine

INSIGHTS_DIR = "viking://resources/insights/"

# Matches: [HH:MM] (source) [category] text  OR  [HH:MM] (source) text
ENTRY_PATTERN = re.compile(
    r"\[(\d{2}:\d{2})\]\s+\(([^)]+)\)\s+(?:\[([^\]]+)\]\s+)?(.*)"
)


def parse_daily_log_entries(log_content: str) -> list[dict]:
    """Parse daily log body into structured entries.

    Each entry: {"time", "source", "category", "text", "tags"}
    Handles both classified [HH:MM] (source) [category] text
    and unclassified [HH:MM] (source) text formats.
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
            # Extract inline tags from text (e.g., #python, #refactor)
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
    """Count entries per category, compute percentages.

    Returns {category: {"count": N, "percent": P, "entries": [times]}}
    """
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


def _get_task_summary(engine: MemEngine) -> dict[str, Any]:
    """Gather task overview: active count, done today, stalled."""
    active_files = []
    done_files = []
    try:
        active_files = engine.list_resources(ACTIVE_DIR)
    except Exception:
        pass
    try:
        done_files = engine.list_resources(DONE_DIR)
    except Exception:
        pass

    stalled = []
    try:
        stalled = get_stalled_todos(engine, stale_days=3)
    except Exception:
        pass

    return {
        "active_count": len(active_files),
        "done_today_count": len(done_files),
        "stalled": stalled,
    }


def build_daily_insight(target_date: date, engine: MemEngine) -> str:
    """Build a daily insight markdown report.

    Sections: 时间分配, 任务追踪, 今日核心话题, 工作建议
    """
    log_content = get_daily_log(target_date, engine)

    if not log_content:
        return f"# 每日洞察 — {target_date.isoformat()}\n\n无数据"

    entries = parse_daily_log_entries(log_content)
    if not entries:
        return f"# 每日洞察 — {target_date.isoformat()}\n\n无数据"

    allocation = compute_time_allocation(entries)
    top_tags = get_top_tags(entries, n=10)
    task_summary = _get_task_summary(engine)

    # Build report sections
    lines: list[str] = []
    lines.append(f"# 每日洞察 — {target_date.isoformat()}")
    lines.append("")

    # Section 1: 时间分配
    lines.append("## 时间分配")
    lines.append("")
    for cat, info in sorted(allocation.items(), key=lambda x: -x[1]["count"]):
        lines.append(
            f"- **{cat}**: {info['count']}条 ({info['percent']}%)"
        )
    lines.append("")

    # Section 2: 任务追踪
    lines.append("## 任务追踪")
    lines.append("")
    lines.append(f"- 活跃任务: {task_summary['active_count']}")
    lines.append(f"- 今日完成: {task_summary['done_today_count']}")
    if task_summary["stalled"]:
        lines.append(f"- 停滞任务: {len(task_summary['stalled'])}")
        for s in task_summary["stalled"]:
            lines.append(f"  - {s['id']}: {s['text'][:50]}")
    lines.append("")

    # Section 3: 今日核心话题
    lines.append("## 今日核心话题")
    lines.append("")
    if top_tags:
        for tag, count in top_tags:
            lines.append(f"- #{tag} ({count})")
    else:
        # Summarize categories as topics
        for cat in sorted(allocation.keys()):
            lines.append(f"- {cat}")
    lines.append("")

    # Section 4: 工作建议 (LLM-generated)
    lines.append("## 工作建议")
    lines.append("")

    summary_text = "\n".join(
        f"[{e['time']}] ({e['source']}) [{e['category']}] {e['text']}"
        for e in entries
    )
    prompt = (
        f"以下是 {target_date.isoformat()} 的工作日志摘要:\n\n"
        f"{summary_text}\n\n"
        f"时间分配: {', '.join(f'{c}: {a['count']}条' for c, a in allocation.items())}\n"
        f"活跃任务: {task_summary['active_count']}, 停滞任务: {len(task_summary['stalled'])}\n\n"
        "请给出 2-3 条简短的工作建议，用中文，markdown 列表格式。"
    )
    advice = call_deepseek(
        prompt=prompt,
        system="你是一个高效工作助手，根据用户的工作日志给出简短实用的建议。",
        max_tokens=512,
        config=engine.config,
    )
    if advice:
        lines.append(advice)
    else:
        lines.append("- 暂无建议")
    lines.append("")

    return "\n".join(lines)


def save_daily_insight(target_date: date, engine: MemEngine) -> str:
    """Generate and save daily insight report.

    Saves to viking://resources/insights/daily-YYYY-MM-DD.md with P1 frontmatter.
    Returns the report text.
    """
    report = build_daily_insight(target_date, engine)

    filename = f"daily-{target_date.isoformat()}.md"
    fields = add_lifecycle_fields(
        {"date": target_date.isoformat(), "type": "daily-insight"},
        priority="P1",
        ttl_days=90,
    )
    content = build_frontmatter(fields, report)

    engine.write_resource(
        content=content,
        target_uri=INSIGHTS_DIR,
        filename=filename,
    )

    return report


def _insight_loop(engine: MemEngine, running: threading.Event) -> None:
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

        # Reset flag at midnight
        if current_time < dt_time(0, 1):
            generated_today = False

        # Check every 60 seconds
        running.wait(timeout=0) if not running.is_set() else None
        if not running.is_set():
            break
        # Sleep in small increments so we can respond to shutdown
        for _ in range(60):
            if not running.is_set():
                return
            running.wait(timeout=1)
            if not running.is_set():
                return


def start_insight_thread(
    engine: MemEngine,
) -> tuple[threading.Thread, threading.Event]:
    """Start background thread that generates daily insight at 20:00.

    Returns (thread, running_event). Clear the event to stop.
    """
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
