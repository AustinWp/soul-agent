"""Recall module — memory search and retrieval."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from ..core.vault import get_engine

console = Console()


def search_memories(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Keyword search across all vault files."""
    engine = get_engine()
    results = engine.search(query=query, limit=limit)

    if not results:
        console.print("[dim]No results found.[/dim]")
        return results

    console.print(f"\n[bold]Found {len(results)} results for:[/bold] {query}\n")

    for i, item in enumerate(results, 1):
        header = f"[{i}] {item.get('filename', '')}"
        snippet = item.get("snippet", "[no content]")
        path = item.get("path", "")

        panel = Panel(
            Text(snippet[:300]),
            title=header,
            subtitle=path,
            border_style="green",
        )
        console.print(panel)

    return results


def recall_today() -> dict[str, Any]:
    """Show a summary of today's memories and todos."""
    engine = get_engine()
    from datetime import date

    from .daily_log import get_daily_log

    today = date.today()
    today_str = today.isoformat()
    summary: dict[str, Any] = {"date": today_str, "memories": [], "todos": []}

    console.print(f"\n[bold]Daily Recall — {today_str}[/bold]\n")

    # Read today's daily log
    daily_log = get_daily_log(today, engine)
    if daily_log:
        console.print("[bold]Today's Log:[/bold]")
        for line in daily_log.split("\n")[:15]:
            line = line.strip()
            if line and not line.startswith("---"):
                console.print(f"  {line[:120]}")
        summary["memories"].append(daily_log)
        console.print()
    else:
        # Fallback: keyword search
        results = engine.search(query=today_str, limit=20)
        memories = [r.get("snippet", "") for r in results if r.get("snippet")]
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
    """Show a summary of this week's activity."""
    from datetime import date, timedelta

    from .compact import INSIGHTS_DIR, _week_label

    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    label = _week_label(today)

    console.print(f"\n[bold]Weekly Recall — {week_start.isoformat()} to {today.isoformat()}[/bold]\n")

    engine = get_engine()

    # Check for existing weekly report
    weekly_path = f"{INSIGHTS_DIR}/{label}.md"
    weekly_report = engine.read_resource(weekly_path)
    if weekly_report:
        console.print(f"[bold]Weekly Report ({label}):[/bold]")
        from ..core.frontmatter import parse_frontmatter

        _, body = parse_frontmatter(weekly_report)
        for line in (body or weekly_report).split("\n")[:20]:
            console.print(f"  {line}")
        return {"week_start": week_start.isoformat(), "items": [weekly_report]}

    # Fallback: keyword search
    results = engine.search(
        query=f"{week_start.isoformat()} {today.isoformat()}",
        limit=30,
    )
    items = [r.get("snippet", "") for r in results if r.get("snippet")]

    if items:
        console.print("[bold]This week's highlights:[/bold]")
        for item in items[:15]:
            if item:
                console.print(f"  - {item[:120]}")
    else:
        console.print("[dim]No significant memories this week.[/dim]")

    return {"week_start": week_start.isoformat(), "items": items}
