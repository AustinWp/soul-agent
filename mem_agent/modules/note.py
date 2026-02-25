"""Note module — ingests text into OpenViking sessions for automatic memory extraction."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.console import Console

from ..core.engine import get_engine

if TYPE_CHECKING:
    from ..core.queue import IngestQueue

console = Console()


def add_note(text: str, ingest_queue: IngestQueue | None = None) -> dict[str, Any]:
    """Record a note. Creates a session, commits it, and triggers memory extraction.

    Also appends to the daily log (L2 layer) for structured lifecycle management.
    Returns the commit result from OpenViking.

    When *ingest_queue* is provided, the note is placed on the queue for
    classification instead of being ingested directly.
    """
    if ingest_queue is not None:
        from datetime import datetime

        from ..core.queue import IngestItem

        ingest_queue.put(IngestItem(text=text, source="note", timestamp=datetime.now(), meta={}))
        console.print("[green]Note queued for classification.[/green]")
        return {"status": "queued"}

    engine = get_engine()
    result = engine.ingest_text(text, source="note")

    # Dual-write: also append to daily log for lifecycle tracking
    from .daily_log import append_daily_log

    try:
        append_daily_log(text, "note", engine)
    except Exception:
        pass  # Don't fail the note if daily log write fails

    console.print(f"[green]Note recorded.[/green] Memory extraction triggered.")
    return result


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
