"""VaultEngine — Obsidian vault file I/O singleton."""

from __future__ import annotations

import atexit
import re
from pathlib import Path
from typing import Any

from .config import get_vault_path, load_config

# Vault subdirectories
VAULT_DIRS = [
    "logs",
    "todos/active",
    "todos/done",
    "insights",
    "memories",
    "core",
    "archive",
]


class VaultEngine:
    """Singleton wrapper for Obsidian vault file I/O."""

    _instance: VaultEngine | None = None
    _config: dict | None = None
    _vault_root: Path | None = None
    _initialized: bool = False

    def __new__(cls) -> VaultEngine:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def initialize(self, config_path: str | Path | None = None) -> None:
        """Load config, set vault root, create subdirectories."""
        if self._initialized:
            return

        self._config = load_config(config_path)
        self._vault_root = get_vault_path(self._config)
        self._ensure_directories()
        self._initialized = True
        atexit.register(self.close)

    def _ensure_directories(self) -> None:
        """Create vault subdirectories if they don't exist."""
        for subdir in VAULT_DIRS:
            (self._vault_root / subdir).mkdir(parents=True, exist_ok=True)

    @property
    def vault_root(self) -> Path:
        if self._vault_root is None:
            raise RuntimeError("VaultEngine not initialized. Call initialize() first.")
        return self._vault_root

    @property
    def config(self) -> dict:
        if self._config is None:
            raise RuntimeError("VaultEngine not initialized. Call initialize() first.")
        return self._config

    def read_resource(self, rel_path: str) -> str | None:
        """Read a file from the vault. Returns None if not found."""
        try:
            path = self.vault_root / rel_path
            if path.exists() and path.is_file():
                return path.read_text(encoding="utf-8")
            return None
        except Exception:
            return None

    def write_resource(self, content: str, directory: str, filename: str) -> None:
        """Write text content to a file in the vault."""
        dir_path = self.vault_root / directory
        dir_path.mkdir(parents=True, exist_ok=True)
        file_path = dir_path / filename
        file_path.write_text(content, encoding="utf-8")

    def list_resources(self, directory: str) -> list[str]:
        """List .md filenames under a vault directory."""
        try:
            dir_path = self.vault_root / directory
            if not dir_path.exists():
                return []
            return sorted(
                f.name for f in dir_path.glob("*.md") if f.is_file()
            )
        except Exception:
            return []

    def delete_resource(self, rel_path: str) -> bool:
        """Delete a file from the vault. Returns True on success."""
        try:
            path = self.vault_root / rel_path
            if path.exists():
                path.unlink()
                return True
            return False
        except Exception:
            return False

    def move_resource(self, from_rel: str, to_rel: str) -> bool:
        """Move a file within the vault. Returns True on success."""
        try:
            src = self.vault_root / from_rel
            dst = self.vault_root / to_rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dst)
            return True
        except Exception:
            return False

    def search(self, query: str, directory: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        """Keyword search across vault markdown files.

        Tokenizes the query, matches files containing all tokens,
        returns snippets with match context.
        """
        tokens = [t.lower() for t in re.split(r'\s+', query.strip()) if t]
        if not tokens:
            return []

        search_dirs: list[str]
        if directory:
            search_dirs = [directory]
        else:
            search_dirs = ["logs", "insights", "memories", "core", "todos/active", "todos/done", "archive"]

        results: list[dict[str, Any]] = []
        for subdir in search_dirs:
            dir_path = self.vault_root / subdir
            if not dir_path.exists():
                continue
            for md_file in dir_path.glob("*.md"):
                if not md_file.is_file():
                    continue
                try:
                    text = md_file.read_text(encoding="utf-8")
                except Exception:
                    continue
                lower_text = text.lower()
                if all(t in lower_text for t in tokens):
                    # Extract a snippet around the first match
                    snippet = _extract_snippet(text, tokens[0])
                    results.append({
                        "path": f"{subdir}/{md_file.name}",
                        "snippet": snippet,
                        "filename": md_file.name,
                    })
                    if len(results) >= limit:
                        return results

        return results

    def append_log(self, text: str, source: str = "note") -> None:
        """Convenience: delegate to daily_log.append_daily_log."""
        from ..modules.daily_log import append_daily_log
        append_daily_log(text, source, self)

    def close(self) -> None:
        """No-op for vault (no connections to close)."""
        self._initialized = False


def _extract_snippet(text: str, token: str, context_chars: int = 100) -> str:
    """Extract a snippet around the first occurrence of token."""
    lower = text.lower()
    idx = lower.find(token.lower())
    if idx == -1:
        return text[:200]
    start = max(0, idx - context_chars)
    end = min(len(text), idx + len(token) + context_chars)
    snippet = text[start:end].replace("\n", " ").strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return snippet


# Module-level singleton accessor
_engine = VaultEngine()


def get_engine() -> VaultEngine:
    return _engine
