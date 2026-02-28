"""Note module — ingests text into daily log and optional classification queue."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.console import Console

from ..core.vault import get_engine

if TYPE_CHECKING:
    from ..core.queue import IngestQueue

console = Console()


def add_note(text: str, ingest_queue: IngestQueue | None = None) -> dict[str, Any]:
    """Record a note.

    Appends to the daily log. When *ingest_queue* is provided, the note
    is placed on the queue for classification instead.
    """
    if ingest_queue is not None:
        from datetime import datetime

        from ..core.queue import IngestItem

        ingest_queue.put(IngestItem(text=text, source="note", timestamp=datetime.now(), meta={}))
        console.print("[green]Note queued for classification.[/green]")
        return {"status": "queued"}

    engine = get_engine()
    engine.append_log(text, source="note")

    console.print("[green]Note recorded.[/green]")
    return {"status": "ok"}


def interactive_note() -> dict[str, Any] | None:
    """Enter interactive mode for writing a longer note.

    Reads multi-line input until an empty line is entered.
    """
    console.print("[dim]Enter your note (empty line to finish):[/dim]")
    lines: list[str] = []
    while True:
        try:
            line = input("> ")
        except (EOFError, KeyboardInterrupt):
            break
        if not line and lines:
            break
        lines.append(line)

    if not lines:
        console.print("[yellow]No input provided.[/yellow]")
        return None

    text = "\n".join(lines)
    return add_note(text)
