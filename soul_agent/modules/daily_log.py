"""Daily log module — time-ordered raw entries stored in vault/logs/."""

from __future__ import annotations

import threading
from datetime import date, datetime
from typing import TYPE_CHECKING

from ..core.frontmatter import build_frontmatter, parse_frontmatter

if TYPE_CHECKING:
    from ..core.vault import VaultEngine

LOGS_DIR = "logs"

# In-memory cache for today's log to avoid repeated reads
_log_lock = threading.Lock()
_today_cache: dict[str, str] = {}  # date_str -> accumulated body text
_today_fields: dict[str, dict] = {}  # date_str -> frontmatter fields


def clear_daily_log_cache() -> None:
    """Clear the in-memory daily log cache. Used for testing."""
    _today_cache.clear()
    _today_fields.clear()


def _seed_cache(today: str, engine: VaultEngine) -> None:
    """Load today's log from storage into memory cache on first access."""
    if today in _today_cache:
        return

    rel_path = f"{LOGS_DIR}/{today}.md"
    content = engine.read_resource(rel_path)
    if content:
        fields, body = parse_frontmatter(content)
        _today_fields[today] = fields
        _today_cache[today] = body or ""
        return

    # No existing log — initialize empty
    _today_fields[today] = {"date": today}
    _today_cache[today] = ""


def append_daily_log(
    text: str,
    source: str,
    engine: VaultEngine,
    category: str = "",
    tags: list[str] | None = None,
    importance: int = 3,
) -> None:
    """Append a timestamped entry to today's daily log."""
    today = date.today().isoformat()
    filename = f"{today}.md"
    now = datetime.now().strftime("%H:%M")
    cat_tag = f" [{category}]" if category else ""
    entry = f"[{now}] ({source}){cat_tag} {text}"

    with _log_lock:
        _seed_cache(today, engine)

        if _today_cache[today]:
            _today_cache[today] += "\n" + entry
        else:
            _today_cache[today] = entry

        content = build_frontmatter(_today_fields[today], _today_cache[today])

        engine.write_resource(
            content=content,
            directory=LOGS_DIR,
            filename=filename,
        )


def get_daily_log(target_date: date, engine: VaultEngine) -> str | None:
    """Read a specific day's log. Returns None if not found."""
    today_str = target_date.isoformat()

    # For today, use the in-memory cache if available
    with _log_lock:
        if today_str in _today_cache and _today_cache[today_str]:
            return build_frontmatter(_today_fields[today_str], _today_cache[today_str])

    # For past days, read from storage
    rel_path = f"{LOGS_DIR}/{today_str}.md"
    return engine.read_resource(rel_path)
