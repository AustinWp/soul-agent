"""Shared frontmatter utilities — parse, build, and lifecycle management."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any


# Default TTL mapping: P0 = permanent, P1 = 90 days, P2 = 30 days
PRIORITY_TTL: dict[str, int | None] = {
    "P0": None,
    "P1": 90,
    "P2": 30,
}


def parse_frontmatter(content: str) -> tuple[dict[str, str], str]:
    """Parse YAML frontmatter from markdown content.

    Returns (fields_dict, body_text).
    If no frontmatter is found, returns ({}, full_content).
    """
    if not content.startswith("---"):
        return {}, content

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content

    meta: dict[str, str] = {}
    for line in parts[1].strip().split("\n"):
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()

    body = parts[2].strip()
    return meta, body


def build_frontmatter(fields: dict[str, str], body: str = "") -> str:
    """Build a markdown document with YAML frontmatter.

    Returns the full markdown string with --- delimiters.
    """
    lines = ["---"]
    for key, value in fields.items():
        lines.append(f"{key}: {value}")
    lines.append("---")
    if body:
        lines.append(body)
    return "\n".join(lines)


def add_lifecycle_fields(
    fields: dict[str, str],
    priority: str = "P1",
    ttl_days: int | None = None,
) -> dict[str, str]:
    """Add priority and expire fields to frontmatter.

    If ttl_days is None, uses the default from PRIORITY_TTL.
    P0 resources never expire (no expire field set).
    """
    fields = dict(fields)  # copy
    fields["priority"] = priority

    if ttl_days is None:
        ttl_days = PRIORITY_TTL.get(priority)

    if ttl_days is not None:
        expire_date = date.today() + timedelta(days=ttl_days)
        fields["expire"] = expire_date.isoformat()

    return fields


def is_expired(fields: dict[str, str]) -> bool:
    """Check if a resource has passed its expiration date.

    Returns False if no expire field or if priority is P0.
    """
    if fields.get("priority") == "P0":
        return False

    expire_str = fields.get("expire", "")
    if not expire_str:
        return False

    try:
        expire_date = date.fromisoformat(expire_str)
        return date.today() > expire_date
    except ValueError:
        return False


def add_classification_fields(
    fields: dict[str, str],
    category: str = "work",
    tags: list[str] | None = None,
    importance: int = 3,
) -> dict[str, str]:
    """Add classification fields to frontmatter."""
    fields["category"] = category
    fields["tags"] = ",".join(tags) if tags else ""
    fields["importance"] = str(importance)
    return fields


def parse_tags(raw: str) -> list[str]:
    """Parse comma-separated tags string into list."""
    if not raw or not raw.strip():
        return []
    return [t.strip() for t in raw.split(",") if t.strip()]


def add_activity_entry(
    fields: dict[str, str], date_str: str, source: str
) -> dict[str, str]:
    """Append an activity entry to the activity_log field.

    Format: date:count:sources|date:count:sources
    """
    existing = fields.get("activity_log", "")
    entries = _parse_activity_raw(existing)
    found = False
    for entry in entries:
        if entry["date"] == date_str:
            entry["count"] += 1
            if source not in entry["sources"]:
                entry["sources"].append(source)
            found = True
            break
    if not found:
        entries.append({"date": date_str, "count": 1, "sources": [source]})
    fields["activity_log"] = _serialize_activity(entries)
    fields["last_activity"] = date_str
    return fields


def parse_activity_log(raw: str) -> list[dict]:
    """Parse activity_log string into list of dicts."""
    return _parse_activity_raw(raw)


def _parse_activity_raw(raw: str) -> list[dict]:
    if not raw or not raw.strip():
        return []
    entries = []
    for part in raw.split("|"):
        part = part.strip()
        if not part:
            continue
        segments = part.split(":")
        if len(segments) >= 3:
            entries.append({
                "date": segments[0],
                "count": int(segments[1]),
                "sources": [s for s in segments[2].split(",") if s],
            })
    return entries


def _serialize_activity(entries: list[dict]) -> str:
    parts = []
    for e in entries:
        sources = ",".join(e["sources"])
        parts.append(f"{e['date']}:{e['count']}:{sources}")
    return "|".join(parts)
