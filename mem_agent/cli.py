"""CLI entry point for mem-agent — built with Typer."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

app = typer.Typer(
    name="mem",
    help="Personal Agent memory system — notes, todos, search, and recall.",
    no_args_is_help=True,
)
todo_app = typer.Typer(help="Manage todo items.")
terminal_app = typer.Typer(help="Terminal command monitoring.")
service_app = typer.Typer(help="Background service management.")
clipboard_app = typer.Typer(help="Clipboard monitoring.")
core_app = typer.Typer(help="Permanent memory (core/MEMORY.md) management.")
abstract_app = typer.Typer(help="Directory abstract (L0 index) management.")
janitor_app = typer.Typer(help="Automatic cleanup management.")
insight_app = typer.Typer(name="insight", help="Work insights and analysis.")
input_hook_app = typer.Typer(name="input-hook", help="Input method hook control.")
claudecode_app = typer.Typer(name="claudecode", help="Claude Code integration.")

app.add_typer(todo_app, name="todo")
app.add_typer(terminal_app, name="terminal")
app.add_typer(service_app, name="service")
app.add_typer(clipboard_app, name="clipboard")
app.add_typer(core_app, name="core")
app.add_typer(abstract_app, name="abstract")
app.add_typer(janitor_app, name="janitor")
app.add_typer(insight_app, name="insight")
app.add_typer(input_hook_app, name="input-hook")
app.add_typer(claudecode_app, name="claudecode")

console = Console()

# Default config path
DEFAULT_CONFIG = Path(__file__).parent.parent / "config" / "ov.conf"


def _init_engine(config: str | None = None) -> None:
    """Initialize the OpenViking engine."""
    from mem_agent.core.engine import get_engine

    config_path = config or str(DEFAULT_CONFIG)
    get_engine().initialize(config_path=config_path)


# ── Note ────────────────────────────────────────────────────────────────────

@app.command()
def note(
    text: Optional[str] = typer.Argument(None, help="Note text. Omit for interactive mode."),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to ov.conf"),
) -> None:
    """Record a note. Triggers automatic memory extraction."""
    _init_engine(config)
    from mem_agent.modules.note import add_note, interactive_note

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
    _init_engine(config)
    from mem_agent.modules.todo import add_todo

    add_todo(text, due=due, priority=priority)


@todo_app.command("ls")
def todo_ls(
    config: Optional[str] = typer.Option(None, "--config", "-c"),
) -> None:
    """List active todos."""
    _init_engine(config)
    from mem_agent.modules.todo import list_todos

    list_todos()


@todo_app.command("done")
def todo_done(
    todo_id: str = typer.Argument(..., help="Todo ID to mark as done"),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
) -> None:
    """Mark a todo as completed."""
    _init_engine(config)
    from mem_agent.modules.todo import complete_todo

    complete_todo(todo_id)


@todo_app.command("rm")
def todo_rm(
    todo_id: str = typer.Argument(..., help="Todo ID to delete"),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
) -> None:
    """Delete a todo."""
    _init_engine(config)
    from mem_agent.modules.todo import remove_todo

    remove_todo(todo_id)


# ── Search ──────────────────────────────────────────────────────────────────

@app.command()
def search(
    query: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(10, "--limit", "-n", help="Max results"),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
) -> None:
    """Search across all memories and resources."""
    _init_engine(config)
    from mem_agent.modules.recall import search_memories

    search_memories(query, limit=limit)


# ── Recall ──────────────────────────────────────────────────────────────────

@app.command()
def recall(
    week: bool = typer.Option(False, "--week", "-w", help="Show weekly recap"),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
) -> None:
    """Show today's memory summary, or weekly recap with --week."""
    _init_engine(config)

    if week:
        from mem_agent.modules.recall import recall_week

        recall_week()
    else:
        from mem_agent.modules.recall import recall_today

        recall_today()


# ── Terminal ───────────────────────────────────────────────────────────────

@terminal_app.command("start")
def terminal_start() -> None:
    """Install zsh hooks and start terminal monitoring."""
    from mem_agent.modules.terminal import install_hook

    install_hook()


@terminal_app.command("stop")
def terminal_stop() -> None:
    """Stop terminal monitoring."""
    from mem_agent.modules.terminal import uninstall_hook

    uninstall_hook()


@terminal_app.command("status")
def terminal_status() -> None:
    """Check terminal monitoring status."""
    from mem_agent.modules.terminal import status

    status()


# ── Clipboard ──────────────────────────────────────────────────────────────

@clipboard_app.command("status")
def clip_status() -> None:
    """Check clipboard monitoring status (queries the daemon)."""
    import httpx
    from mem_agent.service import SERVICE_HOST, SERVICE_PORT

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
    from mem_agent.service import start_service

    start_service()


@service_app.command("stop")
def svc_stop() -> None:
    """Stop the background service."""
    from mem_agent.service import stop_service

    stop_service()


@service_app.command("status")
def svc_status() -> None:
    """Check service status."""
    from mem_agent.service import service_status

    service_status()


# ── Compact ────────────────────────────────────────────────────────────────

@app.command()
def compact(
    month: bool = typer.Option(False, "--month", "-m", help="Generate monthly report instead of weekly"),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
) -> None:
    """Compress recent logs into weekly or monthly insights."""
    _init_engine(config)
    from datetime import date

    from mem_agent.modules.compact import compact_month, compact_week

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
    _init_engine(config)
    engine = _get_engine()

    content = engine.read_resource("viking://resources/core/MEMORY.md")
    if content:
        console.print(content)
    else:
        console.print("[dim]No permanent memory found. Use 'mem core edit' to create one.[/dim]")


@core_app.command("edit")
def core_edit(
    config: Optional[str] = typer.Option(None, "--config", "-c"),
) -> None:
    """Edit permanent memory with $EDITOR."""
    import os
    import tempfile

    _init_engine(config)
    engine = _get_engine()

    editor = os.environ.get("EDITOR", "vim")
    content = engine.read_resource("viking://resources/core/MEMORY.md") or ""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(content)
        tmp_path = f.name

    try:
        import subprocess

        subprocess.run([editor, tmp_path], check=True)
        new_content = Path(tmp_path).read_text(encoding="utf-8")
        if new_content != content:
            from mem_agent.core.frontmatter import add_lifecycle_fields, build_frontmatter, parse_frontmatter

            fields, body = parse_frontmatter(new_content)
            if "priority" not in fields:
                fields = add_lifecycle_fields(fields, priority="P0")
                new_content = build_frontmatter(fields, body)
            engine.delete_resource("viking://resources/core/MEMORY.md")
            engine.write_resource(
                content=new_content,
                target_uri="viking://resources/core/",
                filename="MEMORY.md",
            )
            console.print("[green]Permanent memory updated.[/green]")
        else:
            console.print("[dim]No changes made.[/dim]")
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ── Abstract ──────────────────────────────────────────────────────────────

@abstract_app.command("show")
def abstract_show(
    directory: str = typer.Argument(..., help="Directory name (e.g. logs, insights, core)"),
    refresh: bool = typer.Option(False, "--refresh", "-r", help="Force refresh before showing"),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
) -> None:
    """Show or refresh directory abstract (L0 index)."""
    _init_engine(config)
    from mem_agent.modules.abstract import read_abstract, refresh_abstract

    engine = _get_engine()
    uri = f"viking://resources/{directory}/"

    if refresh:
        console.print(f"[dim]Refreshing abstract for {directory}/...[/dim]")
        summary = refresh_abstract(uri, engine)
        console.print(summary or "[dim]No files found in directory.[/dim]")
    else:
        abstract = read_abstract(uri, engine)
        if abstract:
            console.print(abstract)
        else:
            console.print(f"[dim]No abstract for {directory}/. Use --refresh to generate.[/dim]")


# ── Janitor ───────────────────────────────────────────────────────────────

@janitor_app.command("run")
def janitor_run(
    config: Optional[str] = typer.Option(None, "--config", "-c"),
) -> None:
    """Run cleanup manually — archive expired resources."""
    _init_engine(config)
    from mem_agent.modules.janitor import run_janitor

    engine = _get_engine()
    result = run_janitor(engine)
    console.print(
        f"[green]Janitor complete:[/green] scanned {result['scanned']}, "
        f"archived {result['archived']}"
    )


@janitor_app.command("status")
def janitor_status() -> None:
    """Check janitor status (queries the daemon)."""
    import httpx
    from mem_agent.service import SERVICE_HOST, SERVICE_PORT

    try:
        resp = httpx.get(
            f"http://{SERVICE_HOST}:{SERVICE_PORT}/janitor/status",
            timeout=2,
        )
        data = resp.json()
        console.print(f"Last run: {data.get('last_run', 'never')}")
        console.print(f"Last archived: {data.get('last_archived', 0)}")
        console.print(f"Total archived: {data.get('total_archived', 0)}")
        console.print(f"Running: {'yes' if data.get('running') else 'no'}")
    except Exception:
        console.print("[dim]Janitor: daemon not reachable[/dim]")


# ── Insight ────────────────────────────────────────────────────────────────

@insight_app.command("today")
def insight_today(
    config: Optional[str] = typer.Option(None, "-c", "--config"),
) -> None:
    """Show today's daily insight report."""
    _init_engine(config)
    from datetime import date

    from mem_agent.modules.insight import build_daily_insight

    engine = _get_engine()
    report = build_daily_insight(date.today(), engine)
    console.print(report)


@insight_app.command("week")
def insight_week(
    config: Optional[str] = typer.Option(None, "-c", "--config"),
) -> None:
    """Show insights for the past week."""
    _init_engine(config)
    from datetime import date, timedelta

    from mem_agent.modules.insight import build_daily_insight

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
    _init_engine(config)
    from mem_agent.modules.todo import get_stalled_todos, list_todos

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
    _init_engine(config)
    from datetime import date

    from mem_agent.modules.insight import build_daily_insight

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
    """Start input method hook (requires daemon)."""
    console.print("[yellow]Input hook requires the daemon to be running.[/yellow]")
    console.print("Start with: mem service start")


@input_hook_app.command("stop")
def ihook_stop() -> None:
    """Stop input method hook."""
    import httpx

    try:
        httpx.post("http://127.0.0.1:8330/input-hook/stop", timeout=5)
        console.print("[green]Input hook stopped.[/green]")
    except Exception:
        console.print("[red]Could not reach daemon.[/red]")


@input_hook_app.command("status")
def ihook_status() -> None:
    """Check input hook status."""
    import httpx

    try:
        resp = httpx.get("http://127.0.0.1:8330/input-hook/status", timeout=5)
        console.print(resp.json())
    except Exception:
        console.print("[red]Daemon not running.[/red]")


# ── Claude Code ────────────────────────────────────────────────────────────

@claudecode_app.command("install")
def cc_install() -> None:
    """Install Claude Code hook into settings."""
    from mem_agent.modules.claude_code import install_hook

    install_hook()


@claudecode_app.command("uninstall")
def cc_uninstall() -> None:
    """Uninstall Claude Code hook from settings."""
    from mem_agent.modules.claude_code import uninstall_hook

    uninstall_hook()


def _get_engine():
    """Helper to get the initialized engine instance."""
    from mem_agent.core.engine import get_engine

    return get_engine()


if __name__ == "__main__":
    app()
