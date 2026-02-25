"""Browser history adapter — reads Chrome and Safari SQLite databases."""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.queue import IngestQueue

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHROME_DB = Path.home() / "Library/Application Support/Google/Chrome/Default/History"
SAFARI_DB = Path.home() / "Library/Safari/History.db"

POLL_INTERVAL = 300  # seconds between polls

SKIP_PREFIXES = (
    "chrome://",
    "chrome-extension://",
    "about:",
    "blob:",
    "data:",
    "devtools://",
    "edge://",
    "file://",
    "chrome-search://",
    "safari-resource://",
)

BINARY_EXTENSIONS = frozenset({
    ".pdf", ".zip", ".gz", ".tar", ".dmg", ".exe", ".bin",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg", ".webp",
    ".mp3", ".mp4", ".avi", ".mov", ".mkv", ".wav", ".flac",
    ".woff", ".woff2", ".ttf", ".eot",
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _should_skip_url(url: str) -> bool:
    """Return True if the URL should be filtered out."""
    if not url:
        return True
    lower = url.lower()
    if any(lower.startswith(p) for p in SKIP_PREFIXES):
        return True
    # Skip binary file downloads
    path = lower.split("?")[0].split("#")[0]
    ext = os.path.splitext(path)[1]
    if ext in BINARY_EXTENSIONS:
        return True
    return False


def _copy_db(db_path: str | Path) -> str | None:
    """Copy browser SQLite DB to a temp file (browsers hold WAL locks).

    Returns the temp file path, or None if the DB does not exist.
    """
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    try:
        tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        tmp.close()
        shutil.copy2(str(db_path), tmp.name)
        return tmp.name
    except Exception:
        logger.debug("Failed to copy browser DB %s", db_path, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Chrome
# ---------------------------------------------------------------------------

# Chrome uses a Windows FILETIME epoch: microseconds since 1601-01-01.
# Unix epoch offset in microseconds.
_CHROME_EPOCH_OFFSET = 11_644_473_600_000_000


def _chrome_ts_to_unix(chrome_ts: int) -> float:
    """Convert Chrome visit_time (microseconds since 1601) to Unix timestamp."""
    return (chrome_ts - _CHROME_EPOCH_OFFSET) / 1_000_000


def read_chrome_history(db_path: str | Path | None = None, since_timestamp: float = 0) -> list[dict]:
    """Read Chrome browsing history.

    Parameters
    ----------
    db_path:
        Path to the Chrome History SQLite file.  Defaults to the standard
        macOS location.  The file is copied to a temp location before reading.
    since_timestamp:
        Unix timestamp; only visits after this time are returned.

    Returns a list of ``{url, title, visit_time}`` dicts.
    """
    source = db_path or CHROME_DB
    tmp_path = _copy_db(source)
    if tmp_path is None:
        return []

    results: list[dict] = []
    try:
        # Convert since_timestamp to Chrome epoch
        chrome_since = int(since_timestamp * 1_000_000) + _CHROME_EPOCH_OFFSET if since_timestamp else 0
        conn = sqlite3.connect(tmp_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            """
            SELECT u.url, u.title, v.visit_time
            FROM visits v
            JOIN urls u ON v.url = u.id
            WHERE v.visit_time > ?
            ORDER BY v.visit_time DESC
            """,
            (chrome_since,),
        )
        for row in cursor:
            url = row["url"]
            if _should_skip_url(url):
                continue
            results.append({
                "url": url,
                "title": row["title"] or "",
                "visit_time": _chrome_ts_to_unix(row["visit_time"]),
            })
        conn.close()
    except Exception:
        logger.debug("Error reading Chrome history", exc_info=True)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    return results


# ---------------------------------------------------------------------------
# Safari
# ---------------------------------------------------------------------------

# Safari stores timestamps as seconds since 2001-01-01 (Core Data epoch).
_SAFARI_EPOCH_OFFSET = 978_307_200  # seconds between 1970-01-01 and 2001-01-01


def _safari_ts_to_unix(safari_ts: float) -> float:
    """Convert Safari visit_time to Unix timestamp."""
    return safari_ts + _SAFARI_EPOCH_OFFSET


def read_safari_history(db_path: str | Path | None = None, since_timestamp: float = 0) -> list[dict]:
    """Read Safari browsing history.

    Parameters
    ----------
    db_path:
        Path to the Safari History.db file.
    since_timestamp:
        Unix timestamp; only visits after this time are returned.

    Returns a list of ``{url, title, visit_time}`` dicts.
    """
    source = db_path or SAFARI_DB
    tmp_path = _copy_db(source)
    if tmp_path is None:
        return []

    results: list[dict] = []
    try:
        safari_since = (since_timestamp - _SAFARI_EPOCH_OFFSET) if since_timestamp else 0
        conn = sqlite3.connect(tmp_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            """
            SELECT hi.url, hv.title, hv.visit_time
            FROM history_visits hv
            JOIN history_items hi ON hv.history_item = hi.id
            WHERE hv.visit_time > ?
            ORDER BY hv.visit_time DESC
            """,
            (safari_since,),
        )
        for row in cursor:
            url = row["url"]
            if _should_skip_url(url):
                continue
            results.append({
                "url": url,
                "title": row["title"] or "",
                "visit_time": _safari_ts_to_unix(row["visit_time"]),
            })
        conn.close()
    except Exception:
        logger.debug("Error reading Safari history", exc_info=True)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    return results


# ---------------------------------------------------------------------------
# Background loop
# ---------------------------------------------------------------------------

def _browser_loop(queue: IngestQueue, running: threading.Event) -> None:
    """Poll browser histories and push new visits to the ingest queue."""
    from ..core.queue import IngestItem

    last_chrome_ts: float = time.time()
    last_safari_ts: float = time.time()

    while running.is_set():
        try:
            # Chrome
            chrome_items = read_chrome_history(since_timestamp=last_chrome_ts)
            for item in chrome_items:
                text = f"Visited: {item['title']} — {item['url']}"
                queue.put(IngestItem(
                    text=text,
                    source="browser",
                    timestamp=datetime.fromtimestamp(item["visit_time"], tz=timezone.utc),
                    meta={"url": item["url"], "title": item["title"], "browser": "chrome"},
                ))
            if chrome_items:
                last_chrome_ts = max(i["visit_time"] for i in chrome_items)

            # Safari
            safari_items = read_safari_history(since_timestamp=last_safari_ts)
            for item in safari_items:
                text = f"Visited: {item['title']} — {item['url']}"
                queue.put(IngestItem(
                    text=text,
                    source="browser",
                    timestamp=datetime.fromtimestamp(item["visit_time"], tz=timezone.utc),
                    meta={"url": item["url"], "title": item["title"], "browser": "safari"},
                ))
            if safari_items:
                last_safari_ts = max(i["visit_time"] for i in safari_items)

        except Exception:
            logger.debug("Error in browser poll loop", exc_info=True)

        # Sleep in small increments so we can respond to shutdown quickly
        for _ in range(int(POLL_INTERVAL)):
            if not running.is_set():
                break
            time.sleep(1)


def start_browser_monitor(queue: IngestQueue) -> tuple[threading.Thread, threading.Event]:
    """Start browser history polling in a daemon thread.

    Returns ``(thread, running_event)``.  Clear the event to stop.
    """
    running = threading.Event()
    running.set()
    thread = threading.Thread(
        target=_browser_loop,
        args=(queue, running),
        daemon=True,
        name="browser-monitor",
    )
    thread.start()
    return thread, running
