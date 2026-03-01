"""CLI entry point for soul-agent — built with Typer."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import httpx
import typer
from rich.console import Console

app = typer.Typer(
    name="soul",
    help="Personal digital soul — captures, classifies, and reflects on daily activity.",
    no_args_is_help=True,
)
todo_app = typer.Typer(help="Manage todo items.")
terminal_app = typer.Typer(help="Terminal command monitoring.")
service_app = typer.Typer(help="Background service management.")
clipboard_app = typer.Typer(help="Clipboard monitoring.")
core_app = typer.Typer(help="Permanent memory (core/MEMORY.md) management.")
insight_app = typer.Typer(name="insight", help="Work insights and analysis.")
input_hook_app = typer.Typer(name="input-hook", help="Input method hook control.")
memory_app = typer.Typer(name="memory", help="Long-term memory management.")
claudecode_app = typer.Typer(name="claudecode", help="Claude Code integration.")
soul_app = typer.Typer(name="soul", help="Digital soul (user profile) management.")

app.add_typer(todo_app, name="todo")
app.add_typer(terminal_app, name="terminal")
app.add_typer(service_app, name="service")
app.add_typer(clipboard_app, name="clipboard")
app.add_typer(core_app, name="core")
app.add_typer(insight_app, name="insight")
app.add_typer(input_hook_app, name="input-hook")
app.add_typer(memory_app, name="memory")
app.add_typer(claudecode_app, name="claudecode")
app.add_typer(soul_app, name="soul")

console = Console()

# Default config path
DEFAULT_CONFIG = Path(__file__).parent.parent / "config" / "soul.json"


def _init_engine(config: str | None = None) -> None:
    """Initialize the vault engine."""
    from soul_agent.core.vault import get_engine

    config_path = config or str(DEFAULT_CONFIG)
    get_engine().initialize(config_path=config_path)


def _service_is_running() -> bool:
    """Probe /health endpoint with 1s timeout."""
    try:
        resp = httpx.get(_api_url("/health"), timeout=1)
        return resp.status_code == 200
    except Exception:
        return False


def _api_url(path: str) -> str:
    """Build http://127.0.0.1:8330{path}."""
    return f"http://127.0.0.1:8330{path}"


# ── Note ────────────────────────────────────────────────────────────────────

@app.command()
def note(
    text: Optional[str] = typer.Argument(None, help="Note text. Omit for interactive mode."),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config"),
) -> None:
    """Record a note."""
    if text and _service_is_running():
        resp = httpx.post(_api_url("/note"), json={"text": text}, timeout=5)
        if resp.status_code == 200:
            console.print("[green]Note recorded (via service).[/green]")
        else:
            console.print(f"[red]Service error: {resp.status_code}[/red]")
        return

    _init_engine(config)
    from soul_agent.modules.note import add_note, interactive_note

    if text:
        add_note(text)
    else:
        interactive_note()


# ── Todo ────────────────────────────────────────────────────────────────────

@todo_app.command("add")
def todo_add(
    text: str = typer.Argument(..., help="Todo description"),
    due: Optional[str] = typer.Option(None, "--due", "-d", help="Due date (today, tomorrow, or YYYY-MM-DD)"),
    priority: str = typer.Option("normal", "--priority", "-p", help="Priority: low, normal, high"),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
) -> None:
    """Add a new todo item."""
    if _service_is_running():
        payload = {"text": text, "priority": priority}
        if due:
            payload["due"] = due
        resp = httpx.post(_api_url("/todo/add"), json=payload, timeout=5)
        data = resp.json()
        console.print(f"[green]Todo added (via service):[/green] {data.get('todo_id', '?')}")
        return

    _init_engine(config)
    from soul_agent.modules.todo import add_todo

    add_todo(text, due=due, priority=priority)


@todo_app.command("ls")
def todo_ls(
    config: Optional[str] = typer.Option(None, "--config", "-c"),
) -> None:
    """List active todos."""
    if _service_is_running():
        from rich.table import Table

        resp = httpx.get(_api_url("/todo/list"), timeout=5)
        data = resp.json()
        todos = data.get("todos", [])
        if not todos:
            console.print("[dim]No active todos.[/dim]")
            return

        table = Table(title="Active Todos")
        table.add_column("ID", style="cyan", width=10)
        table.add_column("Task", style="white")
        table.add_column("Due", style="yellow", width=12)
        table.add_column("Priority", style="magenta", width=10)

        for t in todos:
            table.add_row(
                t.get("id", ""),
                t.get("text", "")[:60],
                t.get("due", ""),
                t.get("priority", ""),
            )
        console.print(table)
        return

    _init_engine(config)
    from soul_agent.modules.todo import list_todos

    list_todos()


@todo_app.command("done")
def todo_done(
    todo_id: str = typer.Argument(..., help="Todo ID to mark as done"),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
) -> None:
    """Mark a todo as completed."""
    if _service_is_running():
        resp = httpx.post(_api_url("/todo/done"), json={"todo_id": todo_id}, timeout=5)
        data = resp.json()
        if data.get("success"):
            console.print(f"[green]Todo {todo_id} marked as done.[/green]")
        else:
            console.print(f"[red]Todo {todo_id} not found.[/red]")
        return

    _init_engine(config)
    from soul_agent.modules.todo import complete_todo

    complete_todo(todo_id)


@todo_app.command("rm")
def todo_rm(
    todo_id: str = typer.Argument(..., help="Todo ID to delete"),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
) -> None:
    """Delete a todo."""
    if _service_is_running():
        resp = httpx.post(_api_url("/todo/rm"), json={"todo_id": todo_id}, timeout=5)
        data = resp.json()
        if data.get("success"):
            console.print(f"[green]Todo {todo_id} deleted.[/green]")
        else:
            console.print(f"[red]Todo {todo_id} not found.[/red]")
        return

    _init_engine(config)
    from soul_agent.modules.todo import remove_todo

    remove_todo(todo_id)


# ── Search ──────────────────────────────────────────────────────────────────

@app.command()
def search(
    query: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(10, "--limit", "-n", help="Max results"),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
) -> None:
    """Search across all memories and resources."""
    if _service_is_running():
        from rich.panel import Panel
        from rich.text import Text

        resp = httpx.get(_api_url("/search"), params={"q": query, "limit": limit}, timeout=10)
        data = resp.json()
        items = data.get("results", [])

        if not items:
            console.print("[dim]No results found.[/dim]")
            return

        console.print(f"\n[bold]Found {len(items)} results for:[/bold] {query}\n")
        for i, item in enumerate(items, 1):
            header = f"[{i}] {item.get('filename', '')}"
            snippet = item.get("snippet", "") or "[no content]"
            path = item.get("path", "")
            panel = Panel(
                Text(snippet[:300]),
                title=header,
                subtitle=path,
                border_style="green",
            )
            console.print(panel)
        return

    _init_engine(config)
    from soul_agent.modules.recall import search_memories

    search_memories(query, limit=limit)


# ── Recall ──────────────────────────────────────────────────────────────────

@app.command()
def recall(
    week: bool = typer.Option(False, "--week", "-w", help="Show weekly recap"),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
) -> None:
    """Show today's memory summary, or weekly recap with --week."""
    if _service_is_running():
        scope = "week" if week else "today"
        resp = httpx.get(_api_url("/recall"), params={"scope": scope}, timeout=15)
        data = resp.json().get("data", {})
        if week:
            console.print(f"\n[bold]Weekly Recall — {data.get('week_start', '')}[/bold]\n")
            for item in data.get("items", [])[:15]:
                if item:
                    console.print(f"  - {str(item)[:120]}")
        else:
            console.print(f"\n[bold]Daily Recall — {data.get('date', '')}[/bold]\n")
            for mem in data.get("memories", [])[:10]:
                if mem:
                    console.print(f"  - {str(mem)[:120]}")
        return

    _init_engine(config)

    if week:
        from soul_agent.modules.recall import recall_week

        recall_week()
    else:
        from soul_agent.modules.recall import recall_today

        recall_today()


# ── Terminal ───────────────────────────────────────────────────────────────

@terminal_app.command("start")
def terminal_start() -> None:
    """Install zsh hooks and start terminal monitoring."""
    from soul_agent.modules.terminal import install_hook

    install_hook()


@terminal_app.command("stop")
def terminal_stop() -> None:
    """Stop terminal monitoring."""
    from soul_agent.modules.terminal import uninstall_hook

    uninstall_hook()


@terminal_app.command("status")
def terminal_status() -> None:
    """Check terminal monitoring status."""
    from soul_agent.modules.terminal import status

    status()


# ── Clipboard ──────────────────────────────────────────────────────────────

@clipboard_app.command("status")
def clip_status() -> None:
    """Check clipboard monitoring status (queries the daemon)."""
    from soul_agent.service import SERVICE_HOST, SERVICE_PORT

    try:
        resp = httpx.get(
            f"http://{SERVICE_HOST}:{SERVICE_PORT}/clipboard/status",
            timeout=2,
        )
        data = resp.json()
        if data.get("active"):
            console.print(f"[green]Clipboard monitor: active[/green] (clips captured: {data.get('clips_captured', 0)})")
        else:
            console.print("[dim]Clipboard monitor: inactive[/dim]")
    except Exception:
        console.print("[dim]Clipboard monitor: daemon not reachable[/dim]")


# ── Service ────────────────────────────────────────────────────────────────

@service_app.command("start")
def svc_start() -> None:
    """Start the background service."""
    from soul_agent.service import start_service

    start_service()


@service_app.command("stop")
def svc_stop() -> None:
    """Stop the background service."""
    from soul_agent.service import stop_service

    stop_service()


@service_app.command("status")
def svc_status() -> None:
    """Check service status."""
    from soul_agent.service import service_status

    service_status()


@service_app.command("install")
def svc_install() -> None:
    """Install LaunchAgent so soul-agent starts automatically on login."""
    import shutil
    import sys

    plist_template = Path(__file__).parent / "launchd" / "com.soul-agent.daemon.plist"
    if not plist_template.exists():
        console.print("[red]Plist template not found.[/red]")
        return

    target_dir = Path.home() / "Library" / "LaunchAgents"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "com.soul-agent.daemon.plist"

    python_path = sys.executable
    working_dir = str(Path(__file__).parent.parent.resolve())
    log_dir = str(Path.home() / ".soul-agent")
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    content = plist_template.read_text(encoding="utf-8")
    content = content.replace("__PYTHON_PATH__", python_path)
    content = content.replace("__WORKING_DIR__", working_dir)
    content = content.replace("__LOG_DIR__", log_dir)

    # Inject environment variables from .env if it exists
    env_file = Path(working_dir) / ".env"
    if env_file.exists():
        env_lines = []
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if key and value:
                env_lines.append(f"        <key>{key}</key>\n        <string>{value}</string>")
        if env_lines:
            # Insert env vars into EnvironmentVariables dict before closing </dict>
            env_block = "\n".join(env_lines)
            content = content.replace(
                "        <key>PATH</key>",
                env_block + "\n        <key>PATH</key>",
            )

    target.write_text(content, encoding="utf-8")
    console.print(f"[green]LaunchAgent installed:[/green] {target}")

    import subprocess

    subprocess.run(["launchctl", "load", str(target)], check=False)
    console.print("[green]LaunchAgent loaded. soul-agent will start on login.[/green]")


@service_app.command("uninstall")
def svc_uninstall() -> None:
    """Uninstall LaunchAgent (stops auto-start on login)."""
    import subprocess

    target = Path.home() / "Library" / "LaunchAgents" / "com.soul-agent.daemon.plist"
    if not target.exists():
        console.print("[dim]LaunchAgent not installed.[/dim]")
        return

    subprocess.run(["launchctl", "unload", str(target)], check=False)
    target.unlink(missing_ok=True)
    console.print("[green]LaunchAgent uninstalled.[/green]")


# ── Compact ────────────────────────────────────────────────────────────────

@app.command()
def compact(
    month: bool = typer.Option(False, "--month", "-m", help="Generate monthly report instead of weekly"),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
) -> None:
    """Compress recent logs into weekly or monthly insights."""
    if _service_is_running():
        scope = "month" if month else "week"
        resp = httpx.post(_api_url("/compact"), json={"scope": scope}, timeout=30)
        data = resp.json()
        report = data.get("report", "")
        label = "Monthly" if month else "Weekly"
        if report:
            console.print(f"[green]{label} report generated (via service).[/green]")
            console.print(report[:500])
        else:
            console.print(f"[dim]No data available for {label.lower()} report.[/dim]")
        return

    _init_engine(config)
    from datetime import date

    from soul_agent.modules.compact import compact_month, compact_week

    engine = _get_engine()
    today = date.today()
    if month:
        report = compact_month(today, engine)
        label = "Monthly"
    else:
        report = compact_week(today, engine)
        label = "Weekly"

    if report:
        console.print(f"[green]{label} report generated.[/green]")
        console.print(report[:500])
    else:
        console.print(f"[dim]No data available for {label.lower()} report.[/dim]")


# ── Core (permanent memory) ───────────────────────────────────────────────

@core_app.command("show")
def core_show(
    config: Optional[str] = typer.Option(None, "--config", "-c"),
) -> None:
    """Display permanent memory (core/MEMORY.md)."""
    if _service_is_running():
        resp = httpx.get(_api_url("/core"), timeout=5)
        data = resp.json()
        content = data.get("content", "")
        if content:
            console.print(content)
        else:
            console.print("[dim]No permanent memory found. Use 'soul core edit' to create one.[/dim]")
        return

    _init_engine(config)
    engine = _get_engine()

    content = engine.read_resource("core/MEMORY.md")
    if content:
        console.print(content)
    else:
        console.print("[dim]No permanent memory found. Use 'soul core edit' to create one.[/dim]")


@core_app.command("edit")
def core_edit(
    config: Optional[str] = typer.Option(None, "--config", "-c"),
) -> None:
    """Edit permanent memory with $EDITOR."""
    import os
    import tempfile

    if _service_is_running():
        resp = httpx.get(_api_url("/core"), timeout=5)
        content = resp.json().get("content", "")

        editor = os.environ.get("EDITOR", "vim")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(content)
            tmp_path = f.name

        try:
            import subprocess

            subprocess.run([editor, tmp_path], check=True)
            new_content = Path(tmp_path).read_text(encoding="utf-8")
            if new_content != content:
                httpx.post(_api_url("/core"), json={"content": new_content}, timeout=5)
                console.print("[green]Permanent memory updated (via service).[/green]")
            else:
                console.print("[dim]No changes made.[/dim]")
        finally:
            Path(tmp_path).unlink(missing_ok=True)
        return

    _init_engine(config)
    engine = _get_engine()

    editor = os.environ.get("EDITOR", "vim")
    content = engine.read_resource("core/MEMORY.md") or ""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(content)
        tmp_path = f.name

    try:
        import subprocess

        subprocess.run([editor, tmp_path], check=True)
        new_content = Path(tmp_path).read_text(encoding="utf-8")
        if new_content != content:
            engine.write_resource(
                content=new_content,
                directory="core",
                filename="MEMORY.md",
            )
            console.print("[green]Permanent memory updated.[/green]")
        else:
            console.print("[dim]No changes made.[/dim]")
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ── Insight ────────────────────────────────────────────────────────────────

@insight_app.command("today")
def insight_today(
    config: Optional[str] = typer.Option(None, "-c", "--config"),
) -> None:
    """Show today's daily insight report."""
    if _service_is_running():
        resp = httpx.get(_api_url("/insight"), params={"date": "today"}, timeout=15)
        data = resp.json()
        console.print(data.get("report", "[dim]No insight available.[/dim]"))
        return

    _init_engine(config)
    from datetime import date

    from soul_agent.modules.insight import build_daily_insight

    engine = _get_engine()
    report = build_daily_insight(date.today(), engine)
    console.print(report)


@insight_app.command("week")
def insight_week(
    config: Optional[str] = typer.Option(None, "-c", "--config"),
) -> None:
    """Show insights for the past week."""
    if _service_is_running():
        from datetime import date, timedelta

        for i in range(6, -1, -1):
            d = date.today() - timedelta(days=i)
            resp = httpx.get(_api_url("/insight"), params={"date": d.isoformat()}, timeout=15)
            data = resp.json()
            report = data.get("report", "")
            if report and "\u65e0\u6570\u636e" not in report:
                console.print(f"\n{'=' * 60}")
                console.print(report)
        return

    _init_engine(config)
    from datetime import date, timedelta

    from soul_agent.modules.insight import build_daily_insight

    engine = _get_engine()
    for i in range(6, -1, -1):
        d = date.today() - timedelta(days=i)
        report = build_daily_insight(d, engine)
        if report and "\u65e0\u6570\u636e" not in report:
            console.print(f"\n{'=' * 60}")
            console.print(report)


@insight_app.command("tasks")
def insight_tasks(
    config: Optional[str] = typer.Option(None, "-c", "--config"),
) -> None:
    """Show active and stalled tasks."""
    if _service_is_running():
        from rich.table import Table

        resp = httpx.get(_api_url("/todo/list"), timeout=5)
        todos = resp.json().get("todos", [])

        console.print("\n[bold]Active Todos:[/bold]")
        if todos:
            table = Table(title="Active Todos")
            table.add_column("ID", style="cyan", width=10)
            table.add_column("Task", style="white")
            table.add_column("Due", style="yellow", width=12)
            table.add_column("Priority", style="magenta", width=10)
            for t in todos:
                table.add_row(
                    t.get("id", ""),
                    t.get("text", "")[:60],
                    t.get("due", ""),
                    t.get("priority", ""),
                )
            console.print(table)
        else:
            console.print("[dim]No active todos.[/dim]")

        resp2 = httpx.get(_api_url("/todo/stalled"), timeout=5)
        stalled = resp2.json().get("stalled", [])
        if stalled:
            console.print(f"\n[bold yellow]Stalled ({len(stalled)}):[/bold yellow]")
            for t in stalled:
                console.print(f"  \u26a0 {t.get('text', '')} (last: {t.get('last_activity', '')})")
        return

    _init_engine(config)
    from soul_agent.modules.todo import get_stalled_todos, list_todos

    engine = _get_engine()
    console.print("\n[bold]Active Todos:[/bold]")
    list_todos()
    stalled = get_stalled_todos(engine)
    if stalled:
        console.print(f"\n[bold yellow]Stalled ({len(stalled)}):[/bold yellow]")
        for t in stalled:
            console.print(f"  \u26a0 {t['text']} (last: {t['last_activity']})")


@insight_app.command("suggest")
def insight_suggest(
    config: Optional[str] = typer.Option(None, "-c", "--config"),
) -> None:
    """Show work suggestions based on today's activity."""
    if _service_is_running():
        resp = httpx.get(_api_url("/suggest"), timeout=15)
        data = resp.json()
        suggestions = data.get("suggestions", "")
        if "\u5de5\u4f5c\u5efa\u8bae" in suggestions:
            idx = suggestions.index("\u5de5\u4f5c\u5efa\u8bae")
            console.print(suggestions[idx:])
        else:
            console.print("[yellow]No suggestions available yet.[/yellow]")
        return

    _init_engine(config)
    from datetime import date

    from soul_agent.modules.insight import build_daily_insight

    engine = _get_engine()
    report = build_daily_insight(date.today(), engine)
    if "\u5de5\u4f5c\u5efa\u8bae" in report:
        idx = report.index("\u5de5\u4f5c\u5efa\u8bae")
        console.print(report[idx:])
    else:
        console.print("[yellow]No suggestions available yet.[/yellow]")


# ── Input Hook ─────────────────────────────────────────────────────────────

@input_hook_app.command("start")
def ihook_start() -> None:
    """Start input hook in foreground (captures keystrokes, sends to service)."""
    if not _service_is_running():
        console.print("[yellow]Service not running. Start it first: soul service start[/yellow]")
        return
    from soul_agent.modules.input_hook import run_standalone

    run_standalone()


@input_hook_app.command("stop")
def ihook_stop() -> None:
    """Stop input method hook."""
    try:
        httpx.post("http://127.0.0.1:8330/input-hook/stop", timeout=5)
        console.print("[green]Input hook stopped.[/green]")
    except Exception:
        console.print("[red]Could not reach daemon.[/red]")


@input_hook_app.command("status")
def ihook_status() -> None:
    """Check input hook status."""
    try:
        resp = httpx.get("http://127.0.0.1:8330/input-hook/status", timeout=5)
        console.print(resp.json())
    except Exception:
        console.print("[red]Daemon not running.[/red]")


# ── Memory ─────────────────────────────────────────────────────────────────

@memory_app.command("ls")
def memory_ls(
    importance: Optional[int] = typer.Option(None, "--importance", "-i", help="Filter by minimum importance (1-5)"),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
) -> None:
    """List all long-term memory fragments."""
    if _service_is_running():
        from rich.table import Table

        params: dict = {}
        if importance is not None:
            params["importance"] = importance
        resp = httpx.get(_api_url("/memories"), params=params, timeout=5)
        data = resp.json()
        memories = data.get("memories", [])
        if not memories:
            console.print("[dim]No memories found.[/dim]")
            return

        table = Table(title="Long-term Memories")
        table.add_column("Date", style="cyan", width=12)
        table.add_column("Cat", style="magenta", width=12)
        table.add_column("Imp", style="yellow", width=5)
        table.add_column("Memory", style="white")

        for m in memories:
            table.add_row(
                m.get("source_date", ""),
                m.get("category", ""),
                str(m.get("importance", "")),
                m.get("text", "")[:80],
            )
        console.print(table)
        return

    _init_engine(config)
    from rich.table import Table

    from soul_agent.modules.memory import list_all_memories

    engine = _get_engine()
    memories = list_all_memories(engine)
    if importance is not None:
        memories = [m for m in memories if m["importance"] >= importance]

    if not memories:
        console.print("[dim]No memories found.[/dim]")
        return

    table = Table(title="Long-term Memories")
    table.add_column("Date", style="cyan", width=12)
    table.add_column("Cat", style="magenta", width=12)
    table.add_column("Imp", style="yellow", width=5)
    table.add_column("Memory", style="white")

    for m in memories:
        table.add_row(
            m.get("source_date", ""),
            m.get("category", ""),
            str(m.get("importance", "")),
            m.get("text", "")[:80],
        )
    console.print(table)


@memory_app.command("search")
def memory_search(
    query: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(10, "--limit", "-n", help="Max results"),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
) -> None:
    """Search long-term memories."""
    if _service_is_running():
        from rich.panel import Panel
        from rich.text import Text

        resp = httpx.get(_api_url("/memories/search"), params={"q": query, "limit": limit}, timeout=10)
        data = resp.json()
        items = data.get("results", [])

        if not items:
            console.print("[dim]No memories found.[/dim]")
            return

        console.print(f"\n[bold]Found {len(items)} memories for:[/bold] {query}\n")
        for i, item in enumerate(items, 1):
            snippet = item.get("snippet", "") or "[no content]"
            panel = Panel(
                Text(snippet[:300]),
                title=f"[{i}] {item.get('filename', '')}",
                border_style="blue",
            )
            console.print(panel)
        return

    _init_engine(config)
    from rich.panel import Panel
    from rich.text import Text

    from soul_agent.modules.memory import search_memories_by_query

    engine = _get_engine()
    results = search_memories_by_query(query, engine, limit=limit)

    if not results:
        console.print("[dim]No memories found.[/dim]")
        return

    console.print(f"\n[bold]Found {len(results)} memories for:[/bold] {query}\n")
    for i, item in enumerate(results, 1):
        snippet = item.get("snippet", "") or "[no content]"
        panel = Panel(
            Text(snippet[:300]),
            title=f"[{i}] {item.get('filename', '')}",
            border_style="blue",
        )
        console.print(panel)


# ── Claude Code ────────────────────────────────────────────────────────────

@claudecode_app.command("install")
def cc_install() -> None:
    """Install Claude Code hook into settings."""
    from soul_agent.modules.claude_code import install_hook

    install_hook()


@claudecode_app.command("uninstall")
def cc_uninstall() -> None:
    """Uninstall Claude Code hook from settings."""
    from soul_agent.modules.claude_code import uninstall_hook

    uninstall_hook()


# ── Soul ──────────────────────────────────────────────────────────────────

@soul_app.command("show")
def soul_show(
    config: Optional[str] = typer.Option(None, "--config", "-c"),
) -> None:
    """Display current digital soul profile."""
    if _service_is_running():
        resp = httpx.get(_api_url("/soul"), timeout=5)
        data = resp.json()
        content = data.get("content", "")
        if content:
            console.print(content)
        else:
            console.print("[dim]No soul found. Use 'soul soul init' to create one.[/dim]")
        return

    _init_engine(config)
    from soul_agent.modules.soul import load_soul

    engine = _get_engine()
    content = load_soul(engine)
    if content:
        console.print(content)
    else:
        console.print("[dim]No soul found. Use 'soul soul init' to create one.[/dim]")


@soul_app.command("init")
def soul_init(
    preset: Optional[str] = typer.Argument(None, help="Self-description text for soul initialization."),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
) -> None:
    """Initialize digital soul from a self-description."""
    if not preset:
        preset = typer.prompt("Describe yourself (identity, traits, preferences)")

    if _service_is_running():
        resp = httpx.post(_api_url("/soul/init"), json={"preset": preset}, timeout=15)
        data = resp.json()
        if data.get("status") == "ok":
            console.print("[green]Soul initialized (via service).[/green]")
        else:
            console.print(f"[red]Error: {data}[/red]")
        return

    _init_engine(config)
    from soul_agent.modules.soul import init_soul

    engine = _get_engine()
    init_soul(preset, engine)
    console.print("[green]Soul initialized.[/green]")


@soul_app.command("chat")
def soul_chat(
    question: Optional[str] = typer.Argument(None, help="Question to ask your digital soul."),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
) -> None:
    """Chat with your digital soul — ask questions and get personalized answers."""
    if not question:
        question = typer.prompt("Ask your soul")

    if _service_is_running():
        resp = httpx.post(_api_url("/soul/chat"), json={"question": question}, timeout=30)
        data = resp.json()
        answer = data.get("answer", "")
        if answer:
            console.print(f"\n{answer}\n")
        else:
            console.print("[red]No answer returned.[/red]")
        return

    _init_engine(config)
    from soul_agent.modules.soul import chat_with_soul

    engine = _get_engine()
    answer = chat_with_soul(question, engine)
    console.print(f"\n{answer}\n")


@soul_app.command("evolve")
def soul_evolve(
    config: Optional[str] = typer.Option(None, "--config", "-c"),
) -> None:
    """Manually trigger soul evolution based on recent memories and insights."""
    if _service_is_running():
        resp = httpx.post(_api_url("/soul/evolve"), timeout=30)
        data = resp.json()
        if data.get("evolved"):
            console.print("[green]Soul evolved.[/green]")
        else:
            console.print("[dim]No evolution needed (or no soul/data found).[/dim]")
        return

    _init_engine(config)
    from datetime import date

    from soul_agent.modules.memory import load_high_importance_memories
    from soul_agent.modules.soul import evolve_soul, load_soul

    engine = _get_engine()

    if not load_soul(engine):
        console.print("[yellow]No soul found. Use 'soul soul init' first.[/yellow]")
        return

    # Gather recent memories as evolution input
    memories = load_high_importance_memories(engine, min_importance=3, limit=10)

    # Try to load today's insight report
    from soul_agent.modules.insight import INSIGHTS_DIR

    today = date.today()
    insight_path = f"{INSIGHTS_DIR}/daily-{today.isoformat()}.md"
    report = engine.read_resource(insight_path) or ""

    evolved = evolve_soul(memories, report, engine)
    if evolved:
        console.print("[green]Soul evolved.[/green]")
    else:
        console.print("[dim]No evolution needed.[/dim]")


def _get_engine():
    """Helper to get the initialized engine instance."""
    from soul_agent.core.vault import get_engine

    return get_engine()


if __name__ == "__main__":
    app()
