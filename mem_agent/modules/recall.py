"""Recall module — memory search and retrieval."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from ..core.engine import get_engine

console = Console()


def search_memories(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Semantic search across all memories and resources."""
    engine = get_engine()
    results = engine.search(query=query, limit=limit)

    items: list[dict[str, Any]] = []

    # Process resource results
    if hasattr(results, "resources") and results.resources:
        for ctx in results.resources:
            items.append({
                "type": "resource",
                "uri": getattr(ctx, "uri", ""),
                "score": getattr(ctx, "score", 0),
                "abstract": getattr(ctx, "abstract", ""),
            })

    # Process memory results
    if hasattr(results, "memories") and results.memories:
        for ctx in results.memories:
            items.append({
                "type": "memory",
                "uri": getattr(ctx, "uri", ""),
                "score": getattr(ctx, "score", 0),
                "abstract": getattr(ctx, "abstract", ""),
            })

    if not items:
        console.print("[dim]No results found.[/dim]")
        return items

    console.print(f"\n[bold]Found {len(items)} results for:[/bold] {query}\n")

    for i, item in enumerate(items, 1):
        score_str = f"{item['score']:.3f}" if isinstance(item["score"], float) else str(item["score"])
        header = f"[{i}] {item['type'].upper()} (score: {score_str})"
        abstract = item["abstract"] or "[no abstract]"
        uri = item["uri"]

        panel = Panel(
            Text(abstract[:300]),
            title=header,
            subtitle=uri,
            border_style="blue" if item["type"] == "memory" else "green",
        )
        console.print(panel)

    return items


def recall_today() -> dict[str, Any]:
    """Show a summary of today's memories and todos.

    Layered retrieval: L0 abstract -> L2 daily log -> semantic search fallback.
    """
    engine = get_engine()
    from datetime import date

    from .abstract import read_abstract
    from .daily_log import LOGS_DIR, get_daily_log

    today = date.today()
    today_str = today.isoformat()
    summary: dict[str, Any] = {"date": today_str, "memories": [], "todos": []}

    console.print(f"\n[bold]Daily Recall — {today_str}[/bold]\n")

    # L0: Check logs directory abstract for quick overview
    abstract = read_abstract(LOGS_DIR, engine)
    if abstract:
        console.print("[bold]Logs Overview (L0):[/bold]")
        console.print(f"  {abstract[:200]}")
        console.print()

    # L2: Read today's daily log directly
    daily_log = get_daily_log(today, engine)
    if daily_log:
        console.print("[bold]Today's Log:[/bold]")
        for line in daily_log.split("\n")[:15]:
            line = line.strip()
            if line and not line.startswith("---"):
                console.print(f"  {line[:120]}")
        summary["memories"].append(daily_log)
        console.print()

    # Fallback: semantic search
    if not daily_log:
        results = engine.search(query=f"today {today_str}", limit=20)
        memories = []
        if hasattr(results, "memories") and results.memories:
            for ctx in results.memories:
                memories.append(getattr(ctx, "abstract", ""))
        if hasattr(results, "resources") and results.resources:
            for ctx in results.resources:
                memories.append(getattr(ctx, "abstract", ""))

        summary["memories"] = memories

        if memories:
            console.print("[bold]Memories:[/bold]")
            for m in memories[:10]:
                if m:
                    console.print(f"  - {m[:120]}")
        else:
            console.print("[dim]No memories recorded today.[/dim]")

    # Show active todos
    console.print()
    from .todo import list_todos
    todos = list_todos()
    summary["todos"] = todos

    return summary


def recall_week() -> dict[str, Any]:
    """Show a summary of this week's activity.

    Layered retrieval: L1 weekly insight -> L0 abstract -> semantic search fallback.
    """
    from datetime import date, timedelta

    from .abstract import read_abstract
    from .compact import INSIGHTS_DIR, _week_label

    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    label = _week_label(today)

    console.print(f"\n[bold]Weekly Recall — {week_start.isoformat()} to {today.isoformat()}[/bold]\n")

    engine = get_engine()

    # L1: Check for existing weekly report
    weekly_uri = f"{INSIGHTS_DIR}{label}.md"
    weekly_report = engine.read_resource(weekly_uri)
    if weekly_report:
        console.print(f"[bold]Weekly Report ({label}):[/bold]")
        # Skip frontmatter for display
        from ..core.frontmatter import parse_frontmatter

        _, body = parse_frontmatter(weekly_report)
        for line in (body or weekly_report).split("\n")[:20]:
            console.print(f"  {line}")
        return {"week_start": week_start.isoformat(), "items": [weekly_report]}

    # L0: Check insights directory abstract
    abstract = read_abstract(INSIGHTS_DIR, engine)
    if abstract:
        console.print("[bold]Insights Overview (L0):[/bold]")
        console.print(f"  {abstract[:200]}")
        console.print()

    # Fallback: semantic search
    results = engine.search(query=f"this week activities from {week_start} to {today}", limit=30)

    items = []
    if hasattr(results, "memories") and results.memories:
        for ctx in results.memories:
            items.append(getattr(ctx, "abstract", ""))
    if hasattr(results, "resources") and results.resources:
        for ctx in results.resources:
            items.append(getattr(ctx, "abstract", ""))

    if items:
        console.print("[bold]This week's highlights:[/bold]")
        for item in items[:15]:
            if item:
                console.print(f"  - {item[:120]}")
    else:
        console.print("[dim]No significant memories this week.[/dim]")

    return {"week_start": week_start.isoformat(), "items": items}
