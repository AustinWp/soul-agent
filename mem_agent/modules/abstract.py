"""Abstract module — L0 directory index layer with debounced refresh."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

from ..core.llm import call_deepseek

if TYPE_CHECKING:
    from ..core.engine import MemEngine

ABSTRACT_FILENAME = ".abstract"

_SYSTEM_PROMPT = (
    "You are a memory indexer. Given a list of files with preview snippets, "
    "generate a concise structured summary (~200 tokens) with: "
    "topics covered, file list with one-line descriptions, key terms, "
    "and last update timestamp. Output in markdown."
)


def refresh_abstract(directory_uri: str, engine: MemEngine) -> str:
    """Regenerate the .abstract index for a directory.

    Lists all .md files, reads first 200 chars of each, calls DeepSeek
    to generate a structured summary, writes it as .abstract.
    """
    entries = engine.list_resources(directory_uri)
    md_files = [e for e in entries if e.endswith(".md") and not e.startswith(".")]

    if not md_files:
        return ""

    # Build context from file previews
    previews: list[str] = []
    for name in md_files:
        uri = f"{directory_uri}{name}"
        content = engine.read_resource(uri)
        if content:
            preview = content[:200].replace("\n", " ")
            previews.append(f"- **{name}**: {preview}")

    prompt = (
        f"Directory: {directory_uri}\n"
        f"Files ({len(md_files)}):\n" + "\n".join(previews)
    )

    summary = call_deepseek(
        prompt=prompt,
        system=_SYSTEM_PROMPT,
        max_tokens=300,
        config=engine.config,
    )

    if not summary:
        # Fallback: simple file listing
        summary = f"# Index: {directory_uri}\n\nFiles: {', '.join(md_files)}"

    # Write .abstract to directory
    abstract_uri = f"{directory_uri}{ABSTRACT_FILENAME}"
    # Remove old abstract if exists
    engine.delete_resource(abstract_uri)
    engine.write_resource(
        content=summary,
        target_uri=directory_uri,
        filename=ABSTRACT_FILENAME,
    )

    return summary


def read_abstract(directory_uri: str, engine: MemEngine) -> str | None:
    """Read the .abstract index for a directory."""
    uri = f"{directory_uri}{ABSTRACT_FILENAME}"
    return engine.read_resource(uri)


class AbstractRefresher:
    """Debounced abstract refresher — batches rapid writes into single LLM calls.

    Directories are marked dirty on schedule(). A background thread checks
    every 30s and refreshes directories that have been dirty for over 60s.
    """

    def __init__(self, engine: MemEngine) -> None:
        self._engine = engine
        self._dirty: dict[str, float] = {}  # uri -> first_dirty_time
        self._lock = threading.Lock()
        self._running = threading.Event()
        self._thread: threading.Thread | None = None

    def schedule(self, directory_uri: str) -> None:
        """Mark a directory as needing abstract refresh."""
        with self._lock:
            if directory_uri not in self._dirty:
                self._dirty[directory_uri] = time.time()

    def _loop(self) -> None:
        """Background loop: check dirty dirs every 30s, refresh if stale > 60s."""
        while self._running.is_set():
            self._running.wait(timeout=30)
            if not self._running.is_set():
                break

            now = time.time()
            to_refresh: list[str] = []

            with self._lock:
                for uri, dirty_time in list(self._dirty.items()):
                    if now - dirty_time >= 60:
                        to_refresh.append(uri)
                        del self._dirty[uri]

            for uri in to_refresh:
                try:
                    refresh_abstract(uri, self._engine)
                except Exception:
                    pass

    def start(self) -> None:
        """Start the background refresher thread."""
        self._running.set()
        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name="abstract-refresher",
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the background refresher thread."""
        self._running.clear()
        if self._thread:
            self._thread.join(timeout=5)
