"""Tests for modules/memory.py — long-term memory extraction."""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def engine(tmp_path):
    """Create a mock engine with a real tmp_path vault."""
    eng = MagicMock()
    eng.config = {}
    vault = tmp_path / "vault"
    vault.mkdir()
    memories_dir = vault / "memories"
    memories_dir.mkdir()

    def write_resource(content, directory, filename):
        d = vault / directory
        d.mkdir(parents=True, exist_ok=True)
        (d / filename).write_text(content, encoding="utf-8")

    def list_resources(directory):
        d = vault / directory
        if not d.exists():
            return []
        return sorted(f.name for f in d.glob("*.md") if f.is_file())

    def read_resource(rel_path):
        p = vault / rel_path
        if p.exists():
            return p.read_text(encoding="utf-8")
        return None

    def search(query, directory=None, limit=10):
        return []

    eng.write_resource.side_effect = write_resource
    eng.list_resources.side_effect = list_resources
    eng.read_resource.side_effect = read_resource
    eng.search.side_effect = search
    eng._vault = vault
    return eng


SAMPLE_REPORT = """# 每日洞察 — 2026-02-28

## 今日工作总结

- 完成了 soul-agent 长期记忆模块的设计和实现
- 调试了 pipeline 分类问题
- 阅读了关于知识图谱的论文

## 任务状态

**活跃任务** (2)

- 实现长期记忆沉淀 | 截止: 2026-03-01
- 优化分类器准确率

## 洞察与建议

- 连续编码超过 3 小时后效率显著下降，需要主动休息
- 知识图谱可能对记忆检索有帮助，建议深入研究
- 分类器的准确率问题可能和训练数据偏向有关

## 时间分布

- **coding**: 15条 (60%)
- **learning**: 5条 (20%)
- **work**: 5条 (20%)
"""


class TestParseLlmResponse:
    def test_valid_json(self):
        from soul_agent.modules.memory import _parse_llm_response

        response = json.dumps([
            {"text": "用户偏好深色主题", "category": "preference", "importance": 4, "tags": "ui,theme"},
            {"text": "每天下午效率最高", "category": "pattern", "importance": 3, "tags": "productivity"},
        ])
        result = _parse_llm_response(response)
        assert len(result) == 2
        assert result[0]["text"] == "用户偏好深色主题"
        assert result[0]["category"] == "preference"
        assert result[0]["importance"] == 4

    def test_json_in_code_block(self):
        from soul_agent.modules.memory import _parse_llm_response

        response = '```json\n[{"text": "测试记忆", "category": "learning", "importance": 3, "tags": "test"}]\n```'
        result = _parse_llm_response(response)
        assert len(result) == 1
        assert result[0]["text"] == "测试记忆"

    def test_invalid_category_falls_back(self):
        from soul_agent.modules.memory import _parse_llm_response

        response = json.dumps([
            {"text": "some memory", "category": "invalid_cat", "importance": 3, "tags": ""},
        ])
        result = _parse_llm_response(response)
        assert len(result) == 1
        assert result[0]["category"] == "learning"

    def test_invalid_importance_falls_back(self):
        from soul_agent.modules.memory import _parse_llm_response

        response = json.dumps([
            {"text": "some memory", "category": "pattern", "importance": 10, "tags": ""},
        ])
        result = _parse_llm_response(response)
        assert result[0]["importance"] == 3

    def test_empty_text_skipped(self):
        from soul_agent.modules.memory import _parse_llm_response

        response = json.dumps([
            {"text": "", "category": "pattern", "importance": 3, "tags": ""},
            {"text": "valid", "category": "pattern", "importance": 3, "tags": ""},
        ])
        result = _parse_llm_response(response)
        assert len(result) == 1

    def test_caps_at_five(self):
        from soul_agent.modules.memory import _parse_llm_response

        items = [{"text": f"memory {i}", "category": "learning", "importance": 3, "tags": ""} for i in range(10)]
        response = json.dumps(items)
        result = _parse_llm_response(response)
        assert len(result) == 5

    def test_garbage_input(self):
        from soul_agent.modules.memory import _parse_llm_response

        result = _parse_llm_response("this is not json at all")
        assert result == []


class TestDeduplication:
    def test_no_existing(self):
        from soul_agent.modules.memory import _deduplicate

        candidates = [
            {"text": "用户偏好 Vim 编辑器", "category": "preference", "importance": 4, "tags": ""},
        ]
        result = _deduplicate(candidates, [])
        assert len(result) == 1

    def test_removes_duplicate(self):
        from soul_agent.modules.memory import _deduplicate

        existing = ["用户偏好 Vim 编辑器进行代码编辑"]
        candidates = [
            {"text": "用户偏好 Vim 编辑器", "category": "preference", "importance": 4, "tags": ""},
            {"text": "连续编码后效率下降需要休息", "category": "pattern", "importance": 3, "tags": ""},
        ]
        result = _deduplicate(candidates, existing)
        # First one has high overlap with existing, second is new
        assert any("休息" in m["text"] for m in result)

    def test_is_duplicate_high_overlap(self):
        from soul_agent.modules.memory import _is_duplicate

        # Use space-separated tokens for reliable overlap detection
        assert _is_duplicate(
            "user prefers vim editor for coding",
            ["user prefers vim editor for daily coding work"],
        ) is True

    def test_is_not_duplicate_low_overlap(self):
        from soul_agent.modules.memory import _is_duplicate

        assert _is_duplicate(
            "likes morning coffee routine",
            ["user prefers vim editor for daily coding work"],
        ) is False


class TestFallbackExtract:
    def test_extracts_from_insight_section(self):
        from soul_agent.modules.memory import _fallback_extract

        result = _fallback_extract(SAMPLE_REPORT)
        assert len(result) >= 1
        assert all(m["category"] == "learning" for m in result)
        assert all(m["importance"] == 3 for m in result)

    def test_empty_report(self):
        from soul_agent.modules.memory import _fallback_extract

        result = _fallback_extract("")
        assert result == []


class TestExtractMemories:
    @patch("soul_agent.modules.memory.call_deepseek")
    def test_extract_and_save(self, mock_llm, engine):
        from soul_agent.modules.memory import extract_memories

        mock_llm.return_value = json.dumps([
            {"text": "编码3小时后需要休息", "category": "pattern", "importance": 4, "tags": "productivity,rest"},
            {"text": "知识图谱值得研究", "category": "learning", "importance": 3, "tags": "research"},
        ])

        result = extract_memories(SAMPLE_REPORT, date(2026, 2, 28), engine)
        assert len(result) == 2
        assert result[0]["text"] == "编码3小时后需要休息"

        # Check files were written
        vault = engine._vault
        files = sorted((vault / "memories").glob("*.md"))
        assert len(files) == 2
        assert files[0].name == "2026-02-28-1.md"
        assert files[1].name == "2026-02-28-2.md"

        # Verify frontmatter
        content = files[0].read_text(encoding="utf-8")
        assert "type: memory" in content
        assert "source_date: 2026-02-28" in content
        assert "category: pattern" in content
        assert "importance: 4" in content

    @patch("soul_agent.modules.memory.call_deepseek", return_value="")
    def test_fallback_when_llm_fails(self, mock_llm, engine):
        from soul_agent.modules.memory import extract_memories

        result = extract_memories(SAMPLE_REPORT, date(2026, 2, 28), engine)
        # Should use fallback extraction
        assert len(result) >= 1

    def test_skips_empty_report(self, engine):
        from soul_agent.modules.memory import extract_memories

        result = extract_memories("", date(2026, 2, 28), engine)
        assert result == []

    def test_skips_no_data_report(self, engine):
        from soul_agent.modules.memory import extract_memories

        result = extract_memories("# 每日洞察\n\n无数据", date(2026, 2, 28), engine)
        assert result == []

    @patch("soul_agent.modules.memory.call_deepseek")
    def test_dedup_against_existing(self, mock_llm, engine):
        from soul_agent.modules.memory import extract_memories

        # Write an existing memory first
        vault = engine._vault
        existing = (
            "---\ntype: memory\nsource_date: 2026-02-27\n"
            "category: pattern\nimportance: 4\ntags: productivity\n---\n"
            "编码3小时后需要休息提高效率"
        )
        (vault / "memories" / "2026-02-27-1.md").write_text(existing, encoding="utf-8")

        mock_llm.return_value = json.dumps([
            {"text": "编码3小时后需要休息", "category": "pattern", "importance": 4, "tags": "rest"},
            {"text": "知识图谱值得深入研究", "category": "learning", "importance": 3, "tags": "research"},
        ])

        result = extract_memories(SAMPLE_REPORT, date(2026, 2, 28), engine)
        # First one should be deduped, second is new
        texts = [m["text"] for m in result]
        assert "知识图谱值得深入研究" in texts


class TestLoadHighImportance:
    def test_loads_high_importance(self, engine):
        from soul_agent.modules.memory import load_high_importance_memories

        vault = engine._vault
        for i, (imp, text) in enumerate([
            (5, "关键决策"),
            (4, "重要模式"),
            (2, "低优先级"),
        ], start=1):
            content = (
                f"---\ntype: memory\nsource_date: 2026-02-28\n"
                f"category: pattern\nimportance: {imp}\ntags: test\n---\n{text}"
            )
            (vault / "memories" / f"2026-02-28-{i}.md").write_text(content, encoding="utf-8")

        result = load_high_importance_memories(engine, min_importance=4)
        assert len(result) == 2
        texts = [m["text"] for m in result]
        assert "关键决策" in texts
        assert "重要模式" in texts
        assert "低优先级" not in texts


class TestListAllMemories:
    def test_lists_all(self, engine):
        from soul_agent.modules.memory import list_all_memories

        vault = engine._vault
        content = (
            "---\ntype: memory\nsource_date: 2026-02-28\n"
            "category: learning\nimportance: 3\ntags: test\n---\n"
            "some memory"
        )
        (vault / "memories" / "2026-02-28-1.md").write_text(content, encoding="utf-8")

        result = list_all_memories(engine)
        assert len(result) == 1
        assert result[0]["text"] == "some memory"
        assert result[0]["category"] == "learning"
        assert result[0]["filename"] == "2026-02-28-1.md"
