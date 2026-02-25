"""Clipboard monitoring module — polls macOS pasteboard for changes."""

from __future__ import annotations

import hashlib
import subprocess
import threading
import time
from typing import TYPE_CHECKING

from rich.console import Console

if TYPE_CHECKING:
    from ..core.engine import MemEngine
    from ..core.queue import IngestQueue

console = Console()

# Module-level stats for status queries
clip_stats: dict[str, object] = {
    "active": False,
    "count": 0,
    "last_hash": "",
}

_POLL_INTERVAL = 3  # seconds
_MIN_LENGTH = 10
_MAX_LENGTH = 2000


def _get_clipboard_text() -> str:
    """Read current clipboard text via pbpaste."""
    try:
        result = subprocess.run(
            ["pbpaste"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        return result.stdout
    except Exception:
        return ""


def _hash_text(text: str) -> str:
    """SHA-256 hash for change detection."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _clipboard_loop(engine: MemEngine, running: threading.Event, ingest_queue: IngestQueue | None = None) -> None:
    """Poll clipboard and ingest new content into memory.

    When *ingest_queue* is provided, items are placed on the queue for
    classification instead of being ingested directly.
    """
    clip_stats["active"] = True
    clip_stats["last_hash"] = _hash_text(_get_clipboard_text())

    while running.is_set():
        time.sleep(_POLL_INTERVAL)
        try:
            text = _get_clipboard_text()
            if len(text) < _MIN_LENGTH:
                continue

            h = _hash_text(text)
            if h == clip_stats["last_hash"]:
                continue

            clip_stats["last_hash"] = h
            truncated = text[:_MAX_LENGTH]

            if ingest_queue is not None:
                from datetime import datetime

                from ..core.queue import IngestItem

                ingest_queue.put(IngestItem(text=truncated, source="clipboard", timestamp=datetime.now(), meta={}))
            else:
                engine.ingest_text(truncated, source="clipboard")

                # Dual-write: also append to daily log for lifecycle tracking
                try:
                    from .daily_log import append_daily_log

                    append_daily_log(truncated, "clipboard", engine)
                except Exception:
                    pass

            clip_stats["count"] = int(clip_stats["count"]) + 1
        except Exception:
            continue

    clip_stats["active"] = False


def start_clipboard_monitor(engine: MemEngine, ingest_queue: IngestQueue | None = None) -> tuple[threading.Thread, threading.Event]:
    """Start clipboard polling in a daemon thread.

    Returns (thread, running_event). Clear the event to stop the thread.
    When *ingest_queue* is provided, it is forwarded to the polling loop so
    clipboard contents are queued for classification.
    """
    running = threading.Event()
    running.set()
    thread = threading.Thread(
        target=_clipboard_loop,
        args=(engine, running, ingest_queue),
        daemon=True,
        name="clipboard-monitor",
    )
    thread.start()
    return thread, running
