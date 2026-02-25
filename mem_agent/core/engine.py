"""OpenViking client singleton wrapper."""

from __future__ import annotations

import atexit
from pathlib import Path
from typing import Any

import openviking as ov

from .config import get_data_dir, load_config

# Custom viking:// directories we manage
CUSTOM_DIRS = [
    "viking://resources/todos/active/",
    "viking://resources/todos/done/",
    "viking://resources/terminal/",
    "viking://resources/core/",
    "viking://resources/insights/",
    "viking://resources/logs/",
    "viking://resources/archive/",
    "viking://resources/classified/",
]


class MemEngine:
    """Singleton wrapper around SyncOpenViking."""

    _instance: MemEngine | None = None
    _client: ov.SyncOpenViking | None = None
    _config: dict | None = None
    _initialized: bool = False

    def __new__(cls) -> MemEngine:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def initialize(self, config_path: str | Path | None = None) -> None:
        """Initialize the OpenViking client and ensure custom directories exist."""
        if self._initialized:
            return

        self._config = load_config(config_path)  # env vars expanded
        data_dir = get_data_dir()

        # Write a resolved config (env vars expanded) for OpenViking to read
        import json
        import os
        import tempfile

        resolved_dir = data_dir / "config"
        resolved_dir.mkdir(parents=True, exist_ok=True)
        resolved_path = resolved_dir / "ov_resolved.json"
        resolved_path.write_text(
            json.dumps(self._config, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.environ["OPENVIKING_CONFIG_FILE"] = str(resolved_path)

        self._client = ov.SyncOpenViking(path=str(data_dir))
        self._client.initialize()
        self._ensure_directories()
        self._initialized = True
        atexit.register(self.close)

    def _ensure_directories(self) -> None:
        """Create custom viking:// directories if they don't exist."""
        for uri in CUSTOM_DIRS:
            try:
                self._client.mkdir(uri=uri)
            except Exception:
                pass  # Directory may already exist

    @property
    def client(self) -> ov.SyncOpenViking:
        if self._client is None:
            raise RuntimeError("MemEngine not initialized. Call initialize() first.")
        return self._client

    @property
    def config(self) -> dict:
        if self._config is None:
            raise RuntimeError("MemEngine not initialized. Call initialize() first.")
        return self._config

    def ingest_text(self, text: str, source: str = "note") -> dict[str, Any]:
        """Ingest text via a session to trigger memory extraction.

        Creates a temporary session, adds the text as a user message,
        generates an assistant acknowledgment, commits, and returns the result.
        """
        from openviking.message.part import TextPart

        session = self.client.session()
        session.add_message("user", [TextPart(text=text)])
        session.add_message(
            "assistant",
            [TextPart(text=f"[{source}] Recorded: {text[:100]}...")],
        )
        result = session.commit()
        return result

    def search(self, query: str, target_uri: str | None = None, limit: int = 10) -> Any:
        """Semantic search across the viking filesystem."""
        kwargs: dict[str, Any] = {"query": query, "limit": limit}
        if target_uri:
            kwargs["target_uri"] = target_uri
        return self.client.find(**kwargs)

    def read_resource(self, uri: str) -> str | None:
        """Read a viking:// resource. Returns None if not found."""
        try:
            return self.client.read(uri=uri)
        except Exception:
            return None

    def list_resources(self, uri: str) -> list[str]:
        """List entries under a viking:// directory. Returns names list."""
        try:
            entries = self.client.ls(uri=uri, simple=True, recursive=True)
            result = []
            for entry in entries:
                name = entry if isinstance(entry, str) else entry.get("name", "")
                if name:
                    result.append(name)
            return result
        except Exception:
            return []

    def write_resource(self, content: str, target_uri: str, filename: str) -> dict:
        """Write text content to a viking:// path via a temp file.

        Uses the specified filename so OpenViking receives the correct name.
        """
        import os
        import tempfile

        tmp_dir = tempfile.mkdtemp()
        tmp_path = os.path.join(tmp_dir, filename)

        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(content)

            result = self.client.add_resource(
                path=tmp_path,
                target=target_uri,
                wait=False,
            )
            return result
        finally:
            Path(tmp_path).unlink(missing_ok=True)
            Path(tmp_dir).rmdir()

    def delete_resource(self, uri: str) -> bool:
        """Delete a viking:// resource. Returns True on success."""
        try:
            self.client.rm(uri=uri)
            return True
        except Exception:
            return False

    def move_resource(self, from_uri: str, to_uri: str) -> bool:
        """Move a viking:// resource. Returns True on success."""
        try:
            self.client.mv(from_uri=from_uri, to_uri=to_uri)
            return True
        except Exception:
            return False

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
            self._initialized = False


# Module-level singleton accessor
_engine = MemEngine()


def get_engine() -> MemEngine:
    return _engine
