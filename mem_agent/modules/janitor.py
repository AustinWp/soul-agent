"""Janitor module — automatic cleanup daemon for expired resources."""

from __future__ import annotations

import threading
from datetime import datetime
from typing import TYPE_CHECKING, Any

from .lifecycle import archive_resource, scan_all_expired

if TYPE_CHECKING:
    from ..core.engine import MemEngine

# Module-level stats for status queries
janitor_stats: dict[str, Any] = {
    "last_run": None,
    "last_archived": 0,
    "total_archived": 0,
    "running": False,
}


def run_janitor(engine: MemEngine) -> dict[str, Any]:
    """Run a single janitor pass: scan expired resources and archive them.

    Returns stats dict with scan results.
    """
    expired = scan_all_expired(engine)
    archived = 0

    for item in expired:
        if archive_resource(item["uri"], engine):
            archived += 1

    now = datetime.now().isoformat(timespec="seconds")
    janitor_stats["last_run"] = now
    janitor_stats["last_archived"] = archived
    janitor_stats["total_archived"] = int(janitor_stats["total_archived"]) + archived

    return {
        "scanned": len(expired),
        "archived": archived,
        "timestamp": now,
    }


def _janitor_loop(engine: MemEngine, running: threading.Event) -> None:
    """Background janitor loop — runs hourly, responds to shutdown signal."""
    janitor_stats["running"] = True

    while not running.wait(timeout=3600):
        try:
            run_janitor(engine)
        except Exception:
            pass

    janitor_stats["running"] = False


def start_janitor_thread(
    engine: MemEngine,
) -> tuple[threading.Thread, threading.Event]:
    """Start the janitor daemon thread.

    Returns (thread, stop_event). Set the event to stop the thread.
    Uses Event.wait(timeout) so shutdown is immediate rather than waiting
    up to an hour.
    """
    stop_event = threading.Event()
    thread = threading.Thread(
        target=_janitor_loop,
        args=(engine, stop_event),
        daemon=True,
        name="janitor",
    )
    thread.start()
    return thread, stop_event
