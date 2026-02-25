"""Input method hook adapter — captures keystrokes via macOS CGEventTap."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.queue import IngestQueue

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEDICATED_APPS = {
    "com.apple.Terminal",
    "com.googlecode.iterm2",
    "io.alacritty",
    "com.github.wez.wezterm",
    "net.kovidgoyal.kitty",
    "co.zeit.hyper",
    "dev.warp.Warp-Stable",
    "com.microsoft.VSCode",
    "com.jetbrains.intellij",
    "com.jetbrains.pycharm",
}

# Module-level status
_hook_status: dict[str, object] = {
    "active": False,
    "keystrokes": 0,
    "flushes": 0,
    "last_flush": None,
}

_running_event: threading.Event | None = None
_thread: threading.Thread | None = None


# ---------------------------------------------------------------------------
# InputBuffer
# ---------------------------------------------------------------------------

class InputBuffer:
    """Accumulates keystroke text and flushes as ingest items.

    Parameters
    ----------
    queue:
        The ingest queue to push completed segments to.
    min_length:
        Minimum accumulated text length before a flush produces an item.
        Shorter segments are silently discarded.
    """

    def __init__(self, queue: IngestQueue, min_length: int = 10) -> None:
        self._queue = queue
        self._min_length = min_length
        self._buffer: list[str] = []
        self._length = 0
        self._lock = threading.Lock()

    def append(self, text: str) -> None:
        """Add text (one or more characters) to the buffer."""
        with self._lock:
            self._buffer.append(text)
            self._length += len(text)
            _hook_status["keystrokes"] = int(_hook_status.get("keystrokes", 0)) + len(text)

    def should_flush(self) -> bool:
        """Return True if the buffer has enough content to flush."""
        return self._length >= self._min_length

    def flush(self) -> None:
        """Flush the buffer.  If text length >= min_length, push to queue."""
        from ..core.queue import IngestItem

        with self._lock:
            if self._length < self._min_length:
                self._buffer.clear()
                self._length = 0
                return

            text = "".join(self._buffer)
            self._buffer.clear()
            self._length = 0

        self._queue.put(IngestItem(
            text=f"Typed text: {text}",
            source="input-method",
            timestamp=datetime.now(tz=timezone.utc),
            meta={"raw_length": len(text)},
        ))
        _hook_status["flushes"] = int(_hook_status.get("flushes", 0)) + 1
        _hook_status["last_flush"] = datetime.now(tz=timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# macOS helpers
# ---------------------------------------------------------------------------

def _get_frontmost_bundle_id() -> str:
    """Return the bundle identifier of the frontmost application.

    Uses AppKit's NSWorkspace.  Returns an empty string if AppKit is
    unavailable or the bundle ID cannot be determined.
    """
    try:
        from AppKit import NSWorkspace  # type: ignore[import-not-found]

        ws = NSWorkspace.sharedWorkspace()
        app = ws.frontmostApplication()
        return app.bundleIdentifier() or ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# CGEventTap loop
# ---------------------------------------------------------------------------

def _input_loop(queue: IngestQueue, running: threading.Event) -> None:
    """Run the CGEventTap event loop for keystroke capture.

    This function blocks until *running* is cleared.
    """
    try:
        import Quartz  # type: ignore[import-not-found]
    except ImportError:
        logger.warning("Quartz framework not available; input hook disabled.")
        return

    buf = InputBuffer(queue)
    _hook_status["active"] = True
    flush_interval = 5.0  # seconds
    last_flush_time = time.monotonic()

    def _callback(proxy, event_type, event, refcon):  # noqa: ANN001, ARG001
        nonlocal last_flush_time

        if not running.is_set():
            # Signal the run loop to stop
            Quartz.CFRunLoopStop(Quartz.CFRunLoopGetCurrent())
            return event

        # Only handle key-down events
        if event_type != Quartz.kCGEventKeyDown:
            return event

        # Skip if a dedicated app is focused
        bundle_id = _get_frontmost_bundle_id()
        if bundle_id in DEDICATED_APPS:
            return event

        # Extract typed characters
        try:
            chars = Quartz.CGEventKeyboardGetUnicodeString(
                event, 4, None, None
            )
            # CGEventKeyboardGetUnicodeString returns (length, buffer)
            # Fall back to NSEvent approach
        except Exception:
            chars = None

        if not chars:
            try:
                ns_event = Quartz.NSEvent.eventWithCGEvent_(event)
                chars = ns_event.characters()
            except Exception:
                chars = None

        if chars:
            buf.append(chars)

        # Periodic flush
        now = time.monotonic()
        if now - last_flush_time >= flush_interval:
            if buf.should_flush():
                buf.flush()
            last_flush_time = now

        return event

    # Create event tap
    mask = Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)
    tap = Quartz.CGEventTapCreate(
        Quartz.kCGSessionEventTap,
        Quartz.kCGHeadInsertEventTap,
        Quartz.kCGEventTapOptionListenOnly,
        mask,
        _callback,
        None,
    )

    if tap is None:
        logger.error("Failed to create CGEventTap. Check accessibility permissions.")
        _hook_status["active"] = False
        return

    run_loop_source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
    Quartz.CFRunLoopAddSource(
        Quartz.CFRunLoopGetCurrent(),
        run_loop_source,
        Quartz.kCFRunLoopCommonModes,
    )
    Quartz.CGEventTapEnable(tap, True)

    # Run until stopped
    while running.is_set():
        Quartz.CFRunLoopRunInMode(Quartz.kCFRunLoopDefaultMode, 1.0, False)

    # Final flush
    buf.flush()
    _hook_status["active"] = False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def start_input_hook(queue: IngestQueue) -> tuple[threading.Thread, threading.Event]:
    """Start the input hook in a daemon thread.

    Returns ``(thread, running_event)``.  Clear the event to stop.
    """
    global _running_event, _thread  # noqa: PLW0603

    running = threading.Event()
    running.set()
    _running_event = running

    thread = threading.Thread(
        target=_input_loop,
        args=(queue, running),
        daemon=True,
        name="input-hook",
    )
    thread.start()
    _thread = thread
    return thread, running


def stop_input_hook() -> None:
    """Stop the input hook if running."""
    global _running_event, _thread  # noqa: PLW0603

    if _running_event is not None:
        _running_event.clear()
    if _thread is not None:
        _thread.join(timeout=5)
        _thread = None
    _running_event = None
    _hook_status["active"] = False


def hook_status() -> dict:
    """Return a copy of the current hook status."""
    return dict(_hook_status)
