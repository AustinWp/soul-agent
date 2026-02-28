"""MCP (Model Context Protocol) server for soul-agent.

Exposes memory tools and resources over the MCP protocol so that
LLM clients (Claude Desktop, etc.) can interact with the soul-agent
daemon running on localhost:8330.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

import httpx

# ── Constants ────────────────────────────────────────────────────────────────

DAEMON_URL = "http://127.0.0.1:8330"

# ── Tool definitions ─────────────────────────────────────────────────────────

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "mem_search",
        "description": "Search across all memories and resources by semantic query.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return.",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "mem_recall",
        "description": "Recall recent memory summaries for a given period.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["today", "week", "month"],
                    "description": "Time period to recall (today, week, or month).",
                },
            },
            "required": ["period"],
        },
    },
    {
        "name": "mem_insight",
        "description": "Retrieve the daily insight report for a specific date.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Date in ISO format (YYYY-MM-DD). Defaults to today.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "mem_categories",
        "description": "Show time-allocation categories for a period, optionally filtered by category.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["today", "week", "month"],
                    "description": "Time period for category breakdown.",
                },
                "category": {
                    "type": "string",
                    "description": "Optional category to filter by.",
                },
            },
            "required": ["period"],
        },
    },
    {
        "name": "mem_todos",
        "description": "List todo items filtered by status.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["active", "stalled", "all"],
                    "description": "Filter todos by status.",
                },
            },
            "required": ["status"],
        },
    },
    {
        "name": "mem_suggest",
        "description": "Get AI-powered suggestions based on recent memory patterns.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "focus": {
                    "type": "string",
                    "description": "Optional focus area for suggestions.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "mem_note",
        "description": "Record a new note into memory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The note text to record.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tags for the note.",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "mem_task_progress",
        "description": "Get progress and activity history for a specific todo item.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "todo_id": {
                    "type": "string",
                    "description": "The ID of the todo to check progress for.",
                },
            },
            "required": ["todo_id"],
        },
    },
]

# ── Resource definitions ─────────────────────────────────────────────────────

RESOURCE_DEFINITIONS: list[dict[str, Any]] = [
    {
        "uri": "mem://insight/today",
        "name": "Today's Insight",
        "description": "Daily insight report for today.",
    },
    {
        "uri": "mem://insight/week",
        "name": "Weekly Insight",
        "description": "Aggregated insight report for the current week.",
    },
    {
        "uri": "mem://todos/active",
        "name": "Active Todos",
        "description": "List of currently active todo items.",
    },
    {
        "uri": "mem://todos/stalled",
        "name": "Stalled Todos",
        "description": "Todo items that have not seen recent activity.",
    },
    {
        "uri": "mem://core/memory",
        "name": "Core Memory",
        "description": "Permanent core memory (MEMORY.md) contents.",
    },
    {
        "uri": "mem://stats/categories",
        "name": "Category Stats",
        "description": "Time-allocation category statistics.",
    },
]

# ── HTTP helper ──────────────────────────────────────────────────────────────


def _call_daemon(method: str, path: str, **kwargs: Any) -> dict | str:
    """Make an HTTP request to the soul-agent daemon.

    Returns the parsed JSON dict on success, or an error string on failure.
    """
    url = f"{DAEMON_URL}{path}"
    try:
        with httpx.Client(timeout=30) as client:
            response = client.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        return f"HTTP {exc.response.status_code}: {exc.response.text}"
    except httpx.ConnectError:
        return "Error: soul-agent daemon is not running. Start it with 'mem service start'."
    except Exception as exc:
        return f"Error: {exc}"


# ── Tool handler ─────────────────────────────────────────────────────────────


async def handle_tool_call(name: str, arguments: dict[str, Any]) -> str:
    """Dispatch an MCP tool call to the appropriate daemon endpoint.

    Returns the result as a JSON string for the MCP response.
    """
    if name == "mem_search":
        query = arguments.get("query", "")
        limit = arguments.get("limit", 10)
        result = _call_daemon("GET", "/search", params={"q": query, "limit": limit})

    elif name == "mem_recall":
        period = arguments.get("period", "today")
        if period == "today":
            target = date.today().isoformat()
        elif period == "week":
            target = (date.today() - timedelta(days=7)).isoformat()
        else:
            target = (date.today() - timedelta(days=30)).isoformat()
        result = _call_daemon(
            "GET", "/search", params={"q": f"recall since {target}", "limit": 20}
        )

    elif name == "mem_insight":
        target_date = arguments.get("date", date.today().isoformat())
        result = _call_daemon(
            "GET", f"/abstract/insights/daily-{target_date}.md"
        )

    elif name == "mem_categories":
        period = arguments.get("period", "today")
        category = arguments.get("category")
        params: dict[str, Any] = {"q": f"category breakdown {period}", "limit": 20}
        if category:
            params["q"] = f"category {category} {period}"
        result = _call_daemon("GET", "/search", params=params)

    elif name == "mem_todos":
        status = arguments.get("status", "active")
        if status == "all":
            result = _call_daemon("GET", "/todo/list")
        else:
            result = _call_daemon(
                "GET", "/search", params={"q": f"todo {status}", "limit": 50}
            )

    elif name == "mem_suggest":
        focus = arguments.get("focus", "")
        query = "suggest next actions"
        if focus:
            query = f"suggest next actions for {focus}"
        result = _call_daemon("GET", "/search", params={"q": query, "limit": 10})

    elif name == "mem_note":
        text = arguments.get("text", "")
        tags = arguments.get("tags", [])
        if tags:
            text = f"{text}\n\nTags: {', '.join(tags)}"
        result = _call_daemon("POST", "/note", json={"text": text})

    elif name == "mem_task_progress":
        todo_id = arguments.get("todo_id", "")
        result = _call_daemon(
            "GET", "/search", params={"q": f"todo progress {todo_id}", "limit": 10}
        )

    else:
        result = f"Unknown tool: {name}"

    if isinstance(result, dict):
        return json.dumps(result, indent=2)
    return result


# ── Resource handler ─────────────────────────────────────────────────────────


async def handle_resource_read(uri: str) -> str:
    """Dispatch an MCP resource read to the appropriate daemon endpoint.

    Returns the resource content as a string.
    """
    if uri == "mem://insight/today":
        target = date.today().isoformat()
        result = _call_daemon("GET", f"/abstract/insights/daily-{target}.md")

    elif uri == "mem://insight/week":
        result = _call_daemon(
            "GET", "/search", params={"q": "weekly insight recap", "limit": 20}
        )

    elif uri == "mem://todos/active":
        result = _call_daemon(
            "GET", "/search", params={"q": "todo active", "limit": 50}
        )

    elif uri == "mem://todos/stalled":
        result = _call_daemon(
            "GET", "/search", params={"q": "todo stalled", "limit": 50}
        )

    elif uri == "mem://core/memory":
        result = _call_daemon("GET", "/abstract/core/MEMORY.md")

    elif uri == "mem://stats/categories":
        result = _call_daemon(
            "GET", "/search", params={"q": "category stats breakdown", "limit": 20}
        )

    else:
        result = f"Unknown resource: {uri}"

    if isinstance(result, dict):
        return json.dumps(result, indent=2)
    return result


# ── MCP server entry point ───────────────────────────────────────────────────


def run_mcp_server() -> None:
    """Run the MCP server over stdio.

    This is the main entry point for MCP client integrations (e.g. Claude
    Desktop). It registers all tools and resources, then enters the stdio
    event loop.
    """
    import asyncio

    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    import mcp.types as types

    server = Server("soul-agent")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=t["name"],
                description=t["description"],
                inputSchema=t["inputSchema"],
            )
            for t in TOOL_DEFINITIONS
        ]

    @server.call_tool()
    async def call_tool(
        name: str, arguments: dict[str, Any] | None
    ) -> list[types.TextContent]:
        result = await handle_tool_call(name, arguments or {})
        return [types.TextContent(type="text", text=result)]

    @server.list_resources()
    async def list_resources() -> list[types.Resource]:
        return [
            types.Resource(
                uri=r["uri"],
                name=r["name"],
                description=r["description"],
            )
            for r in RESOURCE_DEFINITIONS
        ]

    @server.read_resource()
    async def read_resource(uri: str) -> str:
        return await handle_resource_read(str(uri))

    async def _run() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )

    asyncio.run(_run())


if __name__ == "__main__":
    run_mcp_server()
