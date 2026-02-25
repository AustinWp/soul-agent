"""Tests for core/frontmatter.py — parse, build, lifecycle utilities."""

from __future__ import annotations

from datetime import date, timedelta

import pytest


class TestParseFrontmatter:
    def test_parse_basic(self):
        from mem_agent.core.frontmatter import parse_frontmatter

        content = "---\nid: abc\npriority: high\n---\nsome body"
        fields, body = parse_frontmatter(content)
        assert fields["id"] == "abc"
        assert fields["priority"] == "high"
        assert body == "some body"

    def test_parse_no_frontmatter(self):
        from mem_agent.core.frontmatter import parse_frontmatter

        fields, body = parse_frontmatter("just plain text")
        assert fields == {}
        assert body == "just plain text"

    def test_parse_empty_body(self):
        from mem_agent.core.frontmatter import parse_frontmatter

        content = "---\nkey: value\n---\n"
        fields, body = parse_frontmatter(content)
        assert fields["key"] == "value"
        assert body == ""

    def test_parse_multiline_body(self):
        from mem_agent.core.frontmatter import parse_frontmatter

        content = "---\nid: 1\n---\nline one\nline two\nline three"
        fields, body = parse_frontmatter(content)
        assert fields["id"] == "1"
        assert "line one" in body
        assert "line three" in body

    def test_parse_colon_in_value(self):
        from mem_agent.core.frontmatter import parse_frontmatter

        content = "---\nurl: http://example.com\n---\nbody"
        fields, body = parse_frontmatter(content)
        assert fields["url"] == "http://example.com"


class TestBuildFrontmatter:
    def test_build_basic(self):
        from mem_agent.core.frontmatter import build_frontmatter

        result = build_frontmatter({"id": "abc", "status": "active"}, "hello")
        assert result.startswith("---\n")
        assert "id: abc" in result
        assert "status: active" in result
        assert result.endswith("hello")

    def test_build_empty_body(self):
        from mem_agent.core.frontmatter import build_frontmatter

        result = build_frontmatter({"key": "val"})
        assert "key: val" in result
        assert result.endswith("---")

    def test_roundtrip(self):
        from mem_agent.core.frontmatter import build_frontmatter, parse_frontmatter

        original_fields = {"id": "test", "priority": "P1"}
        original_body = "This is the body text."

        content = build_frontmatter(original_fields, original_body)
        parsed_fields, parsed_body = parse_frontmatter(content)

        assert parsed_fields == original_fields
        assert parsed_body == original_body


class TestLifecycleFields:
    def test_add_p1_default(self):
        from mem_agent.core.frontmatter import add_lifecycle_fields

        fields = add_lifecycle_fields({}, priority="P1")
        assert fields["priority"] == "P1"
        assert "expire" in fields
        expected = (date.today() + timedelta(days=90)).isoformat()
        assert fields["expire"] == expected

    def test_add_p0_no_expire(self):
        from mem_agent.core.frontmatter import add_lifecycle_fields

        fields = add_lifecycle_fields({}, priority="P0")
        assert fields["priority"] == "P0"
        assert "expire" not in fields

    def test_add_p2_default(self):
        from mem_agent.core.frontmatter import add_lifecycle_fields

        fields = add_lifecycle_fields({}, priority="P2")
        assert fields["priority"] == "P2"
        expected = (date.today() + timedelta(days=30)).isoformat()
        assert fields["expire"] == expected

    def test_custom_ttl(self):
        from mem_agent.core.frontmatter import add_lifecycle_fields

        fields = add_lifecycle_fields({}, priority="P1", ttl_days=7)
        expected = (date.today() + timedelta(days=7)).isoformat()
        assert fields["expire"] == expected

    def test_preserves_existing_fields(self):
        from mem_agent.core.frontmatter import add_lifecycle_fields

        fields = add_lifecycle_fields({"id": "abc"}, priority="P1")
        assert fields["id"] == "abc"
        assert fields["priority"] == "P1"


class TestIsExpired:
    def test_expired(self):
        from mem_agent.core.frontmatter import is_expired

        yesterday = (date.today() - timedelta(days=1)).isoformat()
        assert is_expired({"priority": "P2", "expire": yesterday}) is True

    def test_not_expired(self):
        from mem_agent.core.frontmatter import is_expired

        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        assert is_expired({"priority": "P2", "expire": tomorrow}) is False

    def test_p0_never_expires(self):
        from mem_agent.core.frontmatter import is_expired

        yesterday = (date.today() - timedelta(days=1)).isoformat()
        assert is_expired({"priority": "P0", "expire": yesterday}) is False

    def test_no_expire_field(self):
        from mem_agent.core.frontmatter import is_expired

        assert is_expired({"priority": "P1"}) is False

    def test_invalid_expire(self):
        from mem_agent.core.frontmatter import is_expired

        assert is_expired({"expire": "not-a-date"}) is False


class TestClassificationFields:
    def test_build_with_classification(self):
        from mem_agent.core.frontmatter import build_frontmatter

        fields = {"priority": "P2", "category": "coding", "tags": "python,bugfix", "importance": "4"}
        result = build_frontmatter(fields, "body text")
        assert "category: coding" in result
        assert "tags: python,bugfix" in result

    def test_add_classification_fields(self):
        from mem_agent.core.frontmatter import add_classification_fields

        fields = {"priority": "P2"}
        result = add_classification_fields(fields, category="coding", tags=["python", "bugfix"], importance=4)
        assert result["category"] == "coding"
        assert result["tags"] == "python,bugfix"
        assert result["importance"] == "4"

    def test_add_classification_defaults(self):
        from mem_agent.core.frontmatter import add_classification_fields

        result = add_classification_fields({})
        assert result["category"] == "work"
        assert result["tags"] == ""
        assert result["importance"] == "3"

    def test_parse_tags_helper(self):
        from mem_agent.core.frontmatter import parse_tags

        assert parse_tags("python,bugfix,api") == ["python", "bugfix", "api"]
        assert parse_tags("") == []
        assert parse_tags("single") == ["single"]


class TestActivityLog:
    def test_add_activity_entry(self):
        from mem_agent.core.frontmatter import add_activity_entry

        result = add_activity_entry({}, "2026-02-25", "note")
        assert "2026-02-25" in result["activity_log"]
        assert result["last_activity"] == "2026-02-25"

    def test_add_activity_entry_existing(self):
        from mem_agent.core.frontmatter import add_activity_entry

        fields = {"activity_log": "2026-02-24:1:clipboard", "last_activity": "2026-02-24"}
        result = add_activity_entry(fields, "2026-02-25", "note")
        assert "2026-02-24" in result["activity_log"]
        assert "2026-02-25" in result["activity_log"]
        assert result["last_activity"] == "2026-02-25"

    def test_parse_activity_log(self):
        from mem_agent.core.frontmatter import parse_activity_log

        entries = parse_activity_log("2026-02-24:3:note,clipboard|2026-02-25:1:terminal")
        assert len(entries) == 2
        assert entries[0]["date"] == "2026-02-24"
        assert entries[0]["count"] == 3
        assert entries[0]["sources"] == ["note", "clipboard"]
