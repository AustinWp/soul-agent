"""Tests for mem_agent/mcp_server.py — MCP server definitions and handlers."""

from __future__ import annotations


class TestMCPToolDefinitions:
    def test_tools_registered(self):
        from mem_agent.mcp_server import TOOL_DEFINITIONS

        names = [t["name"] for t in TOOL_DEFINITIONS]
        assert "mem_search" in names
        assert "mem_recall" in names
        assert "mem_insight" in names
        assert "mem_categories" in names
        assert "mem_todos" in names
        assert "mem_suggest" in names
        assert "mem_note" in names
        assert "mem_task_progress" in names

    def test_each_tool_has_description(self):
        from mem_agent.mcp_server import TOOL_DEFINITIONS

        for tool in TOOL_DEFINITIONS:
            assert "description" in tool
            assert len(tool["description"]) > 0

    def test_each_tool_has_input_schema(self):
        from mem_agent.mcp_server import TOOL_DEFINITIONS

        for tool in TOOL_DEFINITIONS:
            assert "inputSchema" in tool


class TestMCPResourceDefinitions:
    def test_resources_registered(self):
        from mem_agent.mcp_server import RESOURCE_DEFINITIONS

        uris = [r["uri"] for r in RESOURCE_DEFINITIONS]
        assert "mem://insight/today" in uris
        assert "mem://insight/week" in uris
        assert "mem://todos/active" in uris
        assert "mem://todos/stalled" in uris
        assert "mem://core/memory" in uris
        assert "mem://stats/categories" in uris

    def test_each_resource_has_name_and_description(self):
        from mem_agent.mcp_server import RESOURCE_DEFINITIONS

        for r in RESOURCE_DEFINITIONS:
            assert "name" in r
            assert "description" in r
