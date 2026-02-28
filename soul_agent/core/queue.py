"""Ingest queue with data models for the classification pipeline.

Provides IngestItem / ClassifiedItem dataclasses and a thread-safe
IngestQueue that supports batching and deduplication.
"""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class IngestItem:
    """Raw item captured from any source before classification."""

    text: str
    source: str  # "note"|"clipboard"|"terminal"|"browser"|"file"|"claude-code"|"input-method"
    timestamp: datetime
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ClassifiedItem(IngestItem):
    """IngestItem after passing through the LLM classifier."""

    category: str = ""
    tags: list[str] = field(default_factory=list)
    importance: int = 3
    summary: str = ""
    action_type: str | None = None
    action_detail: str | None = None
    related_todo_id: str | None = None


# ---------------------------------------------------------------------------
# IngestQueue
# ---------------------------------------------------------------------------

def _text_hash(text: str) -> str:
    """Return a short SHA-256 hex digest for dedup purposes."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class IngestQueue:
    """Thread-safe batching queue with deduplication.

    Parameters
    ----------
    batch_size:
        Number of items that triggers an immediate batch release.
    flush_interval:
        Seconds to wait before flushing whatever is in the queue
        (even if *batch_size* has not been reached).
    dedup_window:
        Seconds during which identical text hashes are silently dropped.
    """

    def __init__(
        self,
        batch_size: int = 10,
        flush_interval: float = 5.0,
        dedup_window: float = 60.0,
    ) -> None:
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._dedup_window = dedup_window

        self._queue: list[IngestItem] = []
        self._lock = threading.Lock()
        self._batch_ready = threading.Event()

        # dedup: hash -> timestamp of last seen
        self._seen: dict[str, float] = {}

    # -- public API ---------------------------------------------------------

    def put(self, item: IngestItem) -> bool:
        """Add *item* to the queue.

        Returns ``True`` if the item was accepted, ``False`` if it was
        deduplicated (same text hash seen within *dedup_window*).
        """
        h = _text_hash(item.text)
        now = time.monotonic()

        with self._lock:
            # Expire old dedup entries while we hold the lock.
            self._purge_seen(now)

            if h in self._seen:
                return False

            self._seen[h] = now
            self._queue.append(item)

            if len(self._queue) >= self._batch_size:
                self._batch_ready.set()

        return True

    def pending_count(self) -> int:
        """Return the number of items currently waiting in the queue."""
        with self._lock:
            return len(self._queue)

    def get_batch(self, timeout: float | None = None) -> list[IngestItem]:
        """Block until a batch is ready and return it.

        A batch is released when either:
        * ``batch_size`` items have accumulated, **or**
        * ``flush_interval`` seconds have elapsed since the call (and the
          queue is non-empty).

        *timeout* caps the total wait time.  If it expires and items are
        present they are returned; if the queue is empty an empty list is
        returned.
        """
        deadline = time.monotonic() + (timeout if timeout is not None else 1e9)

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break

            wait_time = min(remaining, self._flush_interval)
            triggered = self._batch_ready.wait(timeout=wait_time)

            with self._lock:
                if triggered or len(self._queue) > 0:
                    batch = list(self._queue)
                    self._queue.clear()
                    self._batch_ready.clear()
                    if batch:
                        return batch

            # If we get here, the event timed out and queue was empty.
            # Loop to re-check against the outer deadline.

        # Final drain on overall timeout expiry.
        with self._lock:
            batch = list(self._queue)
            self._queue.clear()
            self._batch_ready.clear()
        return batch

    # -- internal -----------------------------------------------------------

    def _purge_seen(self, now: float) -> None:
        """Remove dedup entries older than *dedup_window*."""
        cutoff = now - self._dedup_window
        expired = [h for h, ts in self._seen.items() if ts < cutoff]
        for h in expired:
            del self._seen[h]
