"""Daily log module — L2 explicit layer for time-ordered raw entries."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING

from ..core.frontmatter import add_lifecycle_fields, build_frontmatter, parse_frontmatter

if TYPE_CHECKING:
    from ..core.engine import MemEngine

LOGS_DIR = "viking://resources/logs/"


def _find_daily_log_uri(target_date: date, engine: MemEngine) -> str | None:
    """Find the actual URI for a daily log, handling OpenViking versioned names.

    OpenViking may create versioned resources like ``2026-02-25_1/``,
    ``2026-02-25_2/`` etc.  This helper finds the latest version.
    """
    date_str = target_date.isoformat()
    pattern = re.compile(re.escape(date_str) + r"(?:_(\d+))?$")

    try:
        resources = engine.list_resources(LOGS_DIR)
    except Exception:
        return None

    best_uri = None
    best_version = -1
    for name in resources:
        clean = name.rstrip("/")
        m = pattern.match(clean)
        if m:
            version = int(m.group(1)) if m.group(1) else 0
            if version > best_version:
                best_version = version
                best_uri = f"{LOGS_DIR}{clean}/{date_str}.md"

    return best_uri


def append_daily_log(
    text: str,
    source: str,
    engine: MemEngine,
    category: str = "",
    tags: list[str] | None = None,
    importance: int = 3,
) -> None:
    """Append a timestamped entry to today's daily log.

    Creates the log file with P2 frontmatter if it doesn't exist.
    """
    today = date.today().isoformat()
    filename = f"{today}.md"
    now = datetime.now().strftime("%H:%M")
    cat_tag = f" [{category}]" if category else ""
    entry = f"[{now}] ({source}){cat_tag} {text}"

    # Try to find existing log (handles versioned names)
    existing_uri = _find_daily_log_uri(date.today(), engine)
    existing = None
    if existing_uri:
        existing = engine.read_resource(existing_uri)

    if existing:
        fields, body = parse_frontmatter(existing)
        # Append new entry
        if body:
            body = body + "\n" + entry
        else:
            body = entry
        content = build_frontmatter(fields, body)
        # Delete old version, then write new
        try:
            engine.delete_resource(existing_uri)
        except Exception:
            pass
    else:
        # New daily log with P2 lifecycle
        fields = add_lifecycle_fields({"date": today}, priority="P2", ttl_days=30)
        content = build_frontmatter(fields, entry)

    engine.write_resource(
        content=content,
        target_uri=LOGS_DIR,
        filename=filename,
    )


def get_daily_log(target_date: date, engine: MemEngine) -> str | None:
    """Read a specific day's log. Returns None if not found."""
    uri = _find_daily_log_uri(target_date, engine)
    if uri:
        return engine.read_resource(uri)
    return None
