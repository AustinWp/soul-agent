"""Todo module — CRUD operations for tasks stored in vault/todos/."""

from __future__ import annotations

import uuid
from datetime import datetime, date
from typing import Any

from rich.console import Console
from rich.table import Table

from ..core.llm import call_deepseek
from ..core.vault import get_engine
from ..core.frontmatter import (
    build_frontmatter,
    parse_frontmatter,
)

console = Console()

ACTIVE_DIR = "todos/active"
DONE_DIR = "todos/done"


def _build_todo_md(
    todo_id: str,
    text: str,
    due: str | None = None,
    priority: str = "normal",
) -> str:
    """Build a markdown document for a todo item."""
    now = datetime.now().isoformat(timespec="seconds")
    fields: dict[str, str] = {
        "id": todo_id,
        "created": now,
    }
    if due:
        fields["due"] = due
    fields["priority_label"] = priority
    fields["status"] = "active"
    return build_frontmatter(fields, text)


def _parse_due(due_str: str | None) -> str | None:
    """Parse a human-friendly due string into ISO date."""
    if not due_str:
        return None
    lower = due_str.lower().strip()
    today = date.today()
    from datetime import timedelta
    if lower == "today":
        return today.isoformat()
    if lower == "tomorrow":
        return (today + timedelta(days=1)).isoformat()
    try:
        return date.fromisoformat(lower).isoformat()
    except ValueError:
        return lower


def add_todo(text: str, due: str | None = None, priority: str = "normal") -> str:
    """Create a new todo item. Returns the todo ID."""
    engine = get_engine()
    todo_id = uuid.uuid4().hex[:8]
    due_parsed = _parse_due(due)
    content = _build_todo_md(todo_id, text, due_parsed, priority)

    engine.write_resource(
        content=content,
        directory=ACTIVE_DIR,
        filename=f"{todo_id}.md",
    )

    console.print(f"[green]Todo added:[/green] {todo_id} — {text}")
    if due_parsed:
        console.print(f"  Due: {due_parsed}")
    return todo_id


def _parse_frontmatter(content: str) -> dict[str, str]:
    """Extract YAML frontmatter fields from markdown content."""
    fields, _ = parse_frontmatter(content)
    return fields


def list_todos() -> list[dict[str, Any]]:
    """List all active todos."""
    engine = get_engine()
    todos: list[dict[str, Any]] = []

    entries = engine.list_resources(ACTIVE_DIR)

    for name in entries:
        if not name.endswith(".md") or name.startswith("."):
            continue
        rel_path = f"{ACTIVE_DIR}/{name}"
        try:
            content = engine.read_resource(rel_path)
            if not content:
                continue
            meta = _parse_frontmatter(content)
            body = content.split("---", 2)[-1].strip() if "---" in content else content
            todos.append({
                "id": meta.get("id", name.replace(".md", "")),
                "text": body,
                "due": meta.get("due", ""),
                "priority": meta.get("priority_label", "normal"),
                "created": meta.get("created", ""),
            })
        except Exception:
            continue

    if not todos:
        console.print("[dim]No active todos.[/dim]")
        return todos

    table = Table(title="Active Todos")
    table.add_column("ID", style="cyan", width=10)
    table.add_column("Task", style="white")
    table.add_column("Due", style="yellow", width=12)
    table.add_column("Priority", style="magenta", width=10)

    for t in todos:
        table.add_row(t["id"], t["text"][:60], t["due"], t["priority"])

    console.print(table)
    return todos


def complete_todo(todo_id: str) -> bool:
    """Mark a todo as done by moving it from active/ to done/."""
    engine = get_engine()

    entries = engine.list_resources(ACTIVE_DIR)
    for name in entries:
        if todo_id in name:
            from_rel = f"{ACTIVE_DIR}/{name}"
            to_rel = f"{DONE_DIR}/{name}"
            if engine.move_resource(from_rel, to_rel):
                console.print(f"[green]Todo {todo_id} marked as done.[/green]")
                return True
            else:
                console.print(f"[red]Failed to complete todo.[/red]")
                return False

    console.print(f"[red]Todo {todo_id} not found.[/red]")
    return False


def remove_todo(todo_id: str) -> bool:
    """Delete a todo entirely."""
    engine = get_engine()

    for base_dir in [ACTIVE_DIR, DONE_DIR]:
        entries = engine.list_resources(base_dir)
        for name in entries:
            if todo_id in name:
                rel_path = f"{base_dir}/{name}"
                if engine.delete_resource(rel_path):
                    console.print(f"[green]Todo {todo_id} deleted.[/green]")
                    return True
                else:
                    console.print(f"[red]Failed to delete todo.[/red]")
                    return False

    console.print(f"[red]Todo {todo_id} not found.[/red]")
    return False


def update_todo_activity(todo_id: str, source: str, engine: Any = None) -> bool:
    """Record activity on an existing todo."""
    if engine is None:
        engine = get_engine()
    from ..core.frontmatter import add_activity_entry
    from datetime import date as _date

    for filename in engine.list_resources(ACTIVE_DIR):
        rel_path = f"{ACTIVE_DIR}/{filename}"
        content = engine.read_resource(rel_path)
        if content is None:
            continue
        fields, body = parse_frontmatter(content)
        if fields.get("id", "")[:8] == todo_id[:8]:
            today = _date.today().isoformat()
            add_activity_entry(fields, today, source)
            new_content = build_frontmatter(fields, body)
            engine.delete_resource(rel_path)
            engine.write_resource(content=new_content, directory=ACTIVE_DIR, filename=filename)
            return True
    return False


def get_stalled_todos(engine: Any = None, stale_days: int = 3) -> list[dict[str, Any]]:
    """Find active todos with no recent activity."""
    if engine is None:
        engine = get_engine()
    from datetime import date as _date, timedelta

    cutoff = (_date.today() - timedelta(days=stale_days)).isoformat()
    stalled = []
    for filename in engine.list_resources(ACTIVE_DIR):
        rel_path = f"{ACTIVE_DIR}/{filename}"
        content = engine.read_resource(rel_path)
        if content is None:
            continue
        fields, body = parse_frontmatter(content)
        last = fields.get("last_activity", "")
        if last and last <= cutoff:
            stalled.append({
                "id": fields.get("id", ""),
                "text": body.strip(),
                "last_activity": last,
            })
    return stalled


def suggest_merges(dry_run: bool = True) -> list[dict[str, Any]]:
    """Use LLM to find semantically similar todos that can be merged.

    Returns a list of merge suggestions, each containing:
    - "keep": the todo to keep (id + text)
    - "remove": list of todos to merge into it
    - "merged_text": suggested merged description
    """
    engine = get_engine()
    todos: list[dict[str, Any]] = []
    for name in engine.list_resources(ACTIVE_DIR):
        if not name.endswith(".md") or name.startswith("."):
            continue
        content = engine.read_resource(f"{ACTIVE_DIR}/{name}")
        if not content:
            continue
        fields, body = parse_frontmatter(content)
        todos.append({
            "id": fields.get("id", name.replace(".md", "")),
            "text": body.strip(),
        })

    if len(todos) < 2:
        console.print("[dim]Not enough todos to merge.[/dim]")
        return []

    todo_lines = "\n".join(f"- [{t['id']}] {t['text']}" for t in todos)
    prompt = (
        "以下是用户的待办列表。找出语义上重复或可以合并的条目。\n"
        "对每组可合并的条目，输出一个 JSON 对象包含：\n"
        '- "keep_id": 保留的待办 ID\n'
        '- "remove_ids": 要合并删除的待办 ID 列表\n'
        '- "merged_text": 合并后的描述文本\n\n'
        "如果没有可合并的，返回空数组 []。\n"
        "只返回 JSON 数组，不要 markdown 代码块。\n\n"
        f"待办列表：\n{todo_lines}"
    )

    import json
    raw = call_deepseek(prompt, system="你是一个任务管理助手。", max_tokens=512)
    if not raw or not raw.strip():
        console.print("[dim]No merge suggestions.[/dim]")
        return []

    # Parse response
    text = raw.strip()
    import re
    fence = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        suggestions = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        console.print("[dim]Could not parse merge suggestions.[/dim]")
        return []

    if not isinstance(suggestions, list) or not suggestions:
        console.print("[dim]No merge suggestions found.[/dim]")
        return []

    # Display suggestions
    for i, s in enumerate(suggestions, 1):
        keep_id = s.get("keep_id", "?")
        remove_ids = s.get("remove_ids", [])
        merged = s.get("merged_text", "")
        console.print(f"\n[bold]Merge #{i}:[/bold]")
        console.print(f"  Keep: [cyan]{keep_id}[/cyan]")
        console.print(f"  Remove: [red]{', '.join(remove_ids)}[/red]")
        console.print(f"  Merged: [green]{merged}[/green]")

    if not dry_run:
        for s in suggestions:
            remove_ids = s.get("remove_ids", [])
            for rid in remove_ids:
                remove_todo(rid)
        console.print(f"\n[green]Executed {len(suggestions)} merges.[/green]")

    return suggestions
