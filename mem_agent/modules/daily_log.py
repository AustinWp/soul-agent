"""Daily log module — L2 explicit layer for time-ordered raw entries."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from ..core.frontmatter import add_lifecycle_fields, build_frontmatter, parse_frontmatter

if TYPE_CHECKING:
    from ..core.engine import MemEngine

LOGS_DIR = "viking://resources/logs/"


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
    uri = f"{LOGS_DIR}{filename}"
    now = datetime.now().strftime("%H:%M")
    cat_tag = f" [{category}]" if category else ""
    entry = f"[{now}] ({source}){cat_tag} {text}"

    existing = engine.read_resource(uri)

    if existing:
        fields, body = parse_frontmatter(existing)
        # Append new entry
        if body:
            body = body + "\n" + entry
        else:
            body = entry
        content = build_frontmatter(fields, body)
    else:
        # New daily log with P2 lifecycle
        fields = add_lifecycle_fields({"date": today}, priority="P2", ttl_days=30)
        content = build_frontmatter(fields, entry)

    # Delete old version if it exists, then write new
    if existing:
        engine.delete_resource(uri)

    engine.write_resource(
        content=content,
        target_uri=LOGS_DIR,
        filename=filename,
    )


def get_daily_log(target_date: date, engine: MemEngine) -> str | None:
    """Read a specific day's log. Returns None if not found."""
    filename = f"{target_date.isoformat()}.md"
    uri = f"{LOGS_DIR}{filename}"
    return engine.read_resource(uri)
