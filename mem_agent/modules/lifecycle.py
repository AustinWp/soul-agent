"""Lifecycle module — P0/P1/P2 priority tagging, expiry scanning, and archival."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from ..core.frontmatter import (
    add_lifecycle_fields,
    build_frontmatter,
    is_expired,
    parse_frontmatter,
)

if TYPE_CHECKING:
    from ..core.engine import MemEngine

ARCHIVE_DIR = "viking://resources/archive/"

# Directories to scan for expired resources
SCAN_DIRS = [
    "viking://resources/logs/",
    "viking://resources/insights/",
    "viking://resources/todos/active/",
    "viking://resources/todos/done/",
]


def tag_resource(
    uri: str,
    priority: str,
    ttl_days: int | None,
    engine: MemEngine,
) -> bool:
    """Read a resource, add/update lifecycle frontmatter, write it back.

    Returns True on success.
    """
    content = engine.read_resource(uri)
    if content is None:
        return False

    fields, body = parse_frontmatter(content)
    fields = add_lifecycle_fields(fields, priority=priority, ttl_days=ttl_days)
    new_content = build_frontmatter(fields, body)

    # Determine directory and filename from URI
    parts = uri.rsplit("/", 1)
    if len(parts) != 2:
        return False
    target_dir = parts[0] + "/"
    filename = parts[1]

    engine.delete_resource(uri)
    engine.write_resource(content=new_content, target_uri=target_dir, filename=filename)
    return True


def scan_expired(base_uri: str, engine: MemEngine) -> list[dict[str, Any]]:
    """Scan a directory for expired resources.

    Returns list of dicts with uri, filename, priority, expire date.
    """
    expired: list[dict[str, Any]] = []
    entries = engine.list_resources(base_uri)

    for name in entries:
        if not name.endswith(".md") or name.startswith("."):
            continue

        uri = f"{base_uri}{name}"
        content = engine.read_resource(uri)
        if content is None:
            continue

        fields, _ = parse_frontmatter(content)
        if is_expired(fields):
            expired.append({
                "uri": uri,
                "filename": name,
                "priority": fields.get("priority", ""),
                "expire": fields.get("expire", ""),
            })

    return expired


def scan_all_expired(engine: MemEngine) -> list[dict[str, Any]]:
    """Scan all managed directories for expired resources."""
    all_expired: list[dict[str, Any]] = []
    for directory in SCAN_DIRS:
        all_expired.extend(scan_expired(directory, engine))
    return all_expired


def archive_resource(uri: str, engine: MemEngine) -> bool:
    """Move an expired resource to the archive directory.

    Prefixes the filename with the original directory name to avoid collisions.
    """
    content = engine.read_resource(uri)
    if content is None:
        return False

    # Extract original directory and filename
    # e.g. viking://resources/logs/2026-01-01.md -> logs_2026-01-01.md
    path_part = uri.replace("viking://resources/", "")
    archive_name = path_part.replace("/", "_")

    engine.write_resource(
        content=content,
        target_uri=ARCHIVE_DIR,
        filename=archive_name,
    )
    engine.delete_resource(uri)
    return True
