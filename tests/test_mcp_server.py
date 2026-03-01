"""Tests for soul_agent/mcp_server.py — MCP server definitions and handlers."""

from __future__ import annotations


class TestMCPToolDefinitions:
    def test_tools_registered(self):
        from soul_agent.mcp_server import TOOL_DEFINITIONS

        names = [t["name"] for t in TOOL_DEFINITIONS]
        assert "soul_search" in names
        assert "soul_recall" in names
        assert "soul_insight" in names
        assert "soul_categories" in names
        assert "soul_todos" in names
        assert "soul_suggest" in names
        assert "soul_note" in names
        assert "soul_task_progress" in names

    def test_each_tool_has_description(self):
        from soul_agent.mcp_server import TOOL_DEFINITIONS

        for tool in TOOL_DEFINITIONS:
            assert "description" in tool
            assert len(tool["description"]) > 0

    def test_each_tool_has_input_schema(self):
        from soul_agent.mcp_server import TOOL_DEFINITIONS

        for tool in TOOL_DEFINITIONS:
            assert "inputSchema" in tool


class TestMCPResourceDefinitions:
    def test_resources_registered(self):
        from soul_agent.mcp_server import RESOURCE_DEFINITIONS

        uris = [r["uri"] for r in RESOURCE_DEFINITIONS]
        assert "soul://insight/today" in uris
        assert "soul://insight/week" in uris
        assert "soul://todos/active" in uris
        assert "soul://todos/stalled" in uris
        assert "soul://core/memory" in uris
        assert "soul://stats/categories" in uris

    def test_each_resource_has_name_and_description(self):
        from soul_agent.mcp_server import RESOURCE_DEFINITIONS

        for r in RESOURCE_DEFINITIONS:
            assert "name" in r
            assert "description" in r
