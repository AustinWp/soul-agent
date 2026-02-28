"""Compact module — weekly and monthly report generation."""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

from ..core.frontmatter import build_frontmatter
from ..core.llm import call_deepseek
from .daily_log import LOGS_DIR, get_daily_log

if TYPE_CHECKING:
    from ..core.vault import VaultEngine

INSIGHTS_DIR = "insights"

WEEKLY_PROMPT = """\
You are a personal memory analyst. Given the following daily logs and context
from a week, produce a structured weekly report in markdown with these sections:

## Key Activities
- Bullet list of main things done

## Decisions Made
- Important choices and their rationale

## Ongoing Threads
- Work in progress, unresolved items

## Patterns & Observations
- Recurring themes, habits, or notable trends

Be concise. ~300 tokens max. Focus on signal, not noise.
"""

MONTHLY_PROMPT = """\
You are a personal memory analyst. Given the following weekly reports for a month,
produce a structured monthly summary in markdown with these sections:

## Month Overview
- High-level summary (2-3 sentences)

## Key Accomplishments
- Major completions and milestones

## Themes
- Recurring topics and focus areas

## Looking Forward
- Open threads and upcoming priorities

Be concise. ~400 tokens max.
"""


def _week_label(target_date: date) -> str:
    """Return ISO week label like '2026-W08'."""
    iso = target_date.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _month_label(target_date: date) -> str:
    """Return month label like '2026-02'."""
    return target_date.strftime("%Y-%m")


def compact_week(target_date: date, engine: VaultEngine) -> str:
    """Generate a weekly report from daily logs.

    Collects daily logs for the week, calls DeepSeek to produce a
    structured weekly insight. Writes to insights/YYYY-Www.md.
    """
    # Find week boundaries (Monday to Sunday)
    weekday = target_date.weekday()
    week_start = target_date - timedelta(days=weekday)
    week_end = week_start + timedelta(days=6)

    # Collect daily logs for the week
    logs: list[str] = []
    for i in range(7):
        day = week_start + timedelta(days=i)
        log = get_daily_log(day, engine)
        if log:
            logs.append(f"### {day.isoformat()}\n{log}")

    # Collect completed todos for the week
    todo_context = ""
    try:
        done_entries = engine.list_resources("todos/done")
        done_items = []
        for name in done_entries:
            if name.endswith(".md"):
                content = engine.read_resource(f"todos/done/{name}")
                if content:
                    done_items.append(content[:100])
        if done_items:
            todo_context = "\n\n### Completed Todos\n" + "\n".join(
                f"- {t}" for t in done_items[:10]
            )
    except Exception:
        pass

    if not logs:
        return ""

    # Build prompt
    context = "\n\n".join(logs) + todo_context
    prompt = (
        f"Week: {week_start.isoformat()} to {week_end.isoformat()}\n\n"
        f"{context}"
    )

    report = call_deepseek(
        prompt=prompt,
        system=WEEKLY_PROMPT,
        max_tokens=500,
        config=engine.config,
    )

    if not report:
        # Fallback: simple concatenation
        report = f"# Week {_week_label(target_date)}\n\n" + "\n\n".join(logs)

    # Write report
    label = _week_label(target_date)
    fields = {"type": "weekly-report", "week": label}
    content = build_frontmatter(fields, report)
    filename = f"{label}.md"

    # Remove old version if exists
    engine.delete_resource(f"{INSIGHTS_DIR}/{filename}")

    engine.write_resource(
        content=content,
        directory=INSIGHTS_DIR,
        filename=filename,
    )

    return report


def compact_month(target_date: date, engine: VaultEngine) -> str:
    """Generate a monthly report by aggregating weekly reports.

    Reads all weekly reports for the month, calls DeepSeek to produce
    a monthly summary. Writes to insights/YYYY-MM.md.
    """
    month_label = _month_label(target_date)
    year = target_date.year
    month = target_date.month

    # Collect weekly reports for this month
    weekly_reports: list[str] = []
    entries = engine.list_resources(INSIGHTS_DIR)
    for name in entries:
        if name.startswith(f"{year}-W") and name.endswith(".md"):
            content = engine.read_resource(f"{INSIGHTS_DIR}/{name}")
            if content:
                weekly_reports.append(f"### {name.replace('.md', '')}\n{content}")

    # Also collect daily logs for the month as fallback context
    daily_context: list[str] = []
    if not weekly_reports:
        day = date(year, month, 1)
        while day.month == month:
            log = get_daily_log(day, engine)
            if log:
                daily_context.append(f"### {day.isoformat()}\n{log[:200]}")
            try:
                day = day + timedelta(days=1)
            except (ValueError, OverflowError):
                break

    if not weekly_reports and not daily_context:
        return ""

    context = "\n\n".join(weekly_reports) if weekly_reports else "\n\n".join(daily_context)
    prompt = f"Month: {month_label}\n\n{context}"

    report = call_deepseek(
        prompt=prompt,
        system=MONTHLY_PROMPT,
        max_tokens=600,
        config=engine.config,
    )

    if not report:
        report = f"# Month {month_label}\n\n" + context

    # Write report
    fields = {"type": "monthly-report", "month": month_label}
    content = build_frontmatter(fields, report)
    filename = f"{month_label}.md"

    engine.delete_resource(f"{INSIGHTS_DIR}/{filename}")

    engine.write_resource(
        content=content,
        directory=INSIGHTS_DIR,
        filename=filename,
    )

    return report
