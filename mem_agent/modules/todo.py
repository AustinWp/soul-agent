"""Todo module — CRUD operations for tasks stored in viking://resources/todos/."""

from __future__ import annotations

import uuid
from datetime import datetime, date
from typing import Any

from rich.console import Console
from rich.table import Table

from ..core.engine import get_engine
from ..core.frontmatter import (
    add_lifecycle_fields,
    build_frontmatter,
    parse_frontmatter,
)

console = Console()

ACTIVE_DIR = "viking://resources/todos/active/"
DONE_DIR = "viking://resources/todos/done/"


def _build_todo_md(
    todo_id: str,
    text: str,
    due: str | None = None,
    priority: str = "normal",
) -> str:
    """Build a markdown document for a todo item with P1 lifecycle."""
    now = datetime.now().isoformat(timespec="seconds")
    fields: dict[str, str] = {
        "id": todo_id,
        "created": now,
    }
    if due:
        fields["due"] = due
    fields["priority_label"] = priority
    fields["status"] = "active"
    # Add lifecycle fields (P1 = 90 days TTL by default)
    fields = add_lifecycle_fields(fields, priority="P1", ttl_days=90)
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
    # Try parsing as ISO date
    try:
        return date.fromisoformat(lower).isoformat()
    except ValueError:
        return lower  # Return as-is if we can't parse


def add_todo(text: str, due: str | None = None, priority: str = "normal") -> str:
    """Create a new todo item. Returns the todo ID."""
    engine = get_engine()
    todo_id = uuid.uuid4().hex[:8]
    due_parsed = _parse_due(due)
    content = _build_todo_md(todo_id, text, due_parsed, priority)

    engine.write_resource(
        content=content,
        target_uri=ACTIVE_DIR,
        filename=f"{todo_id}.md",
    )

    console.print(f"[green]Todo added:[/green] {todo_id} — {text}")
    if due_parsed:
        console.print(f"  Due: {due_parsed}")
    return todo_id


def _parse_frontmatter(content: str) -> dict[str, str]:
    """Extract YAML frontmatter fields from markdown content.

    Delegates to the shared frontmatter parser but returns only the fields dict
    for backwards compatibility.
    """
    fields, _ = parse_frontmatter(content)
    return fields


def list_todos() -> list[dict[str, Any]]:
    """List all active todos."""
    engine = get_engine()
    todos: list[dict[str, Any]] = []

    try:
        entries = engine.client.ls(uri=ACTIVE_DIR, simple=True, recursive=True)
    except Exception:
        entries = []

    for entry in entries:
        name = entry if isinstance(entry, str) else entry.get("name", "")
        if not name.endswith(".md") or name.startswith("."):
            continue
        uri = f"{ACTIVE_DIR}{name}" if isinstance(entry, str) else entry.get("uri", "")
        try:
            content = engine.client.read(uri=uri)
            meta = _parse_frontmatter(content)
            body = content.split("---", 2)[-1].strip() if "---" in content else content
            todos.append({
                "id": meta.get("id", name.replace(".md", "")),
                "text": body,
                "due": meta.get("due", ""),
                "priority": meta.get("priority", "normal"),
                "created": meta.get("created", ""),
                "uri": uri,
            })
        except Exception:
            continue

    # Display
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

    try:
        entries = engine.client.ls(uri=ACTIVE_DIR, simple=True, recursive=True)
    except Exception:
        console.print(f"[red]Todo {todo_id} not found.[/red]")
        return False

    for entry in entries:
        name = entry if isinstance(entry, str) else entry.get("name", "")
        if todo_id in name:
            from_uri = f"{ACTIVE_DIR}{name}" if isinstance(entry, str) else entry.get("uri", "")
            to_uri = f"{DONE_DIR}{name}"
            try:
                engine.client.mv(from_uri=from_uri, to_uri=to_uri)
                console.print(f"[green]Todo {todo_id} marked as done.[/green]")
                return True
            except Exception as e:
                console.print(f"[red]Failed to complete todo: {e}[/red]")
                return False

    console.print(f"[red]Todo {todo_id} not found.[/red]")
    return False


def remove_todo(todo_id: str) -> bool:
    """Delete a todo entirely."""
    engine = get_engine()

    for base_dir in [ACTIVE_DIR, DONE_DIR]:
        try:
            entries = engine.client.ls(uri=base_dir, simple=True, recursive=True)
        except Exception:
            continue

        for entry in entries:
            name = entry if isinstance(entry, str) else entry.get("name", "")
            if todo_id in name:
                uri = f"{base_dir}{name}" if isinstance(entry, str) else entry.get("uri", "")
                try:
                    engine.client.rm(uri=uri)
                    console.print(f"[green]Todo {todo_id} deleted.[/green]")
                    return True
                except Exception as e:
                    console.print(f"[red]Failed to delete todo: {e}[/red]")
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
            engine.write_resource(content=new_content, target_uri=ACTIVE_DIR, filename=filename)
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
