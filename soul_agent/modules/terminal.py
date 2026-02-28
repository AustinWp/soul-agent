"""Terminal monitoring module — zsh hook management."""

from __future__ import annotations

from pathlib import Path

import httpx
from rich.console import Console

from ..service import SERVICE_HOST, SERVICE_PORT

console = Console()

HOOK_SCRIPT = Path(__file__).parent.parent / "hooks" / "zsh_hook.sh"
ZSHRC = Path.home() / ".zshrc"
HOOK_MARKER = "# soul-agent terminal hook"


def _source_line() -> str:
    return f'{HOOK_MARKER}\nsource "{HOOK_SCRIPT}"'


def install_hook() -> None:
    """Append the zsh hook source line to ~/.zshrc."""
    if not HOOK_SCRIPT.exists():
        console.print("[red]Hook script not found:[/red] " + str(HOOK_SCRIPT))
        return

    zshrc_text = ZSHRC.read_text() if ZSHRC.exists() else ""

    if HOOK_MARKER in zshrc_text:
        console.print("[yellow]Hook already installed in ~/.zshrc[/yellow]")
        return

    with ZSHRC.open("a") as f:
        f.write(f"\n{_source_line()}\n")

    console.print("[green]Hook installed.[/green] Run [bold]source ~/.zshrc[/bold] to activate.")


def uninstall_hook() -> None:
    """Remove the hook lines from ~/.zshrc."""
    if not ZSHRC.exists():
        console.print("[dim]~/.zshrc not found, nothing to remove.[/dim]")
        return

    lines = ZSHRC.read_text().splitlines()
    filtered = []
    skip_next = False
    for line in lines:
        if HOOK_MARKER in line:
            skip_next = True
            continue
        if skip_next and "zsh_hook.sh" in line:
            skip_next = False
            continue
        skip_next = False
        filtered.append(line)

    ZSHRC.write_text("\n".join(filtered) + "\n")
    console.print("[green]Hook removed from ~/.zshrc.[/green]")


def status() -> None:
    """Check if the hook is installed and if the daemon is reachable."""
    # Check hook installation
    zshrc_text = ZSHRC.read_text() if ZSHRC.exists() else ""
    hook_installed = HOOK_MARKER in zshrc_text

    if hook_installed:
        console.print("[green]Hook: installed[/green]")
    else:
        console.print("[dim]Hook: not installed[/dim]")

    # Check daemon reachability
    try:
        resp = httpx.get(f"http://{SERVICE_HOST}:{SERVICE_PORT}/health", timeout=2)
        if resp.status_code == 200:
            console.print("[green]Daemon: reachable[/green]")
        else:
            console.print(f"[yellow]Daemon: responded with {resp.status_code}[/yellow]")
    except Exception:
        console.print("[dim]Daemon: not reachable[/dim]")
