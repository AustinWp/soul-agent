"""File watcher adapter — monitors directories for changes using watchdog."""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.queue import IngestQueue

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

IGNORE_DIRS = frozenset({
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".eggs",
    "dist",
    "build",
    ".idea",
    ".vscode",
    "data",
    "vectordb",
    ".agfs",
    "logs",
})

IGNORE_FILES = frozenset({
    ".DS_Store",
    "Thumbs.db",
    ".gitkeep",
    "desktop.ini",
    "LOCK",
    "LOG",
    "MANIFEST",
    "CURRENT",
})

BINARY_EXTENSIONS = frozenset({
    ".pdf", ".zip", ".gz", ".tar", ".dmg", ".exe", ".bin", ".iso",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg", ".webp", ".tiff",
    ".mp3", ".mp4", ".avi", ".mov", ".mkv", ".wav", ".flac", ".ogg",
    ".woff", ".woff2", ".ttf", ".eot",
    ".pyc", ".pyo", ".so", ".dylib", ".dll", ".o", ".a",
    ".sqlite", ".db", ".tmp", ".lock",
})

DEFAULT_WATCH_DIRS = [
    str(Path.home() / "Desktop"),
    str(Path.home() / "Documents"),
    str(Path.home() / "Downloads"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _should_ignore(path: str | Path) -> bool:
    """Return True if the path should be ignored by the file watcher."""
    p = Path(path)
    name = p.name

    # Ignore specific file names
    if name in IGNORE_FILES:
        return True

    # Ignore hidden files (starting with .)
    if name.startswith(".") and name != ".env":
        return True

    # Ignore binary extensions
    if p.suffix.lower() in BINARY_EXTENSIONS:
        return True

    # Ignore paths containing ignored directory names
    parts = p.parts
    for part in parts:
        if part in IGNORE_DIRS:
            return True

    return False


def _extract_preview(path: str | Path, max_chars: int = 500) -> str:
    """Read the first *max_chars* characters from a text file.

    Returns an empty string if the file cannot be read (missing, binary, etc.).
    """
    try:
        p = Path(path)
        if not p.exists() or not p.is_file():
            return ""
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            return f.read(max_chars)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Watchdog handler
# ---------------------------------------------------------------------------

class _FileHandler:
    """Watchdog event handler that puts file events on the ingest queue."""

    def __init__(self, queue: IngestQueue) -> None:
        self._queue = queue

    def dispatch(self, event) -> None:  # noqa: ANN001
        """Called by watchdog for every filesystem event."""
        # Only handle file events, not directory events
        if getattr(event, "is_directory", False):
            return

        src_path = getattr(event, "src_path", None)
        if src_path is None:
            return

        if _should_ignore(src_path):
            return

        event_type = getattr(event, "event_type", "unknown")
        if event_type not in ("created", "modified", "moved"):
            return

        self._handle_file_event(src_path, event_type)

    def _handle_file_event(self, path: str, event_type: str) -> None:
        """Create an IngestItem for the file event."""
        from ..core.queue import IngestItem

        preview = _extract_preview(path)
        name = Path(path).name

        if preview:
            text = f"File {event_type}: {name}\n---\n{preview}"
        else:
            text = f"File {event_type}: {name}"

        self._queue.put(IngestItem(
            text=text,
            source="file",
            timestamp=datetime.now(tz=timezone.utc),
            meta={
                "path": str(path),
                "event_type": event_type,
                "filename": name,
            },
        ))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def start_file_watcher(
    queue: IngestQueue,
    watch_dirs: list[str] | None = None,
) -> tuple:
    """Start a watchdog Observer monitoring the given directories.

    Parameters
    ----------
    queue:
        The ingest queue to push file events into.
    watch_dirs:
        Directories to watch.  Defaults to ~/Desktop, ~/Documents, ~/Downloads.

    Returns ``(observer, stop_event)``.  Set stop_event to trigger shutdown.
    """
    from watchdog.observers import Observer

    dirs = watch_dirs or DEFAULT_WATCH_DIRS
    handler = _FileHandler(queue)
    stop_event = threading.Event()
    stop_event.set()

    observer = Observer()
    observer.daemon = True

    for d in dirs:
        if os.path.isdir(d):
            observer.schedule(handler, d, recursive=True)
            logger.info("Watching directory: %s", d)
        else:
            logger.debug("Skipping non-existent directory: %s", d)

    observer.start()
    return observer, stop_event
