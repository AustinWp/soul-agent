"""Tests for modules/soul.py — digital soul initialization, evolution, and context."""

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
    (vault / "core").mkdir(parents=True)

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

    eng.write_resource.side_effect = write_resource
    eng.list_resources.side_effect = list_resources
    eng.read_resource.side_effect = read_resource
    eng._vault = vault
    return eng


STRUCTURED_PRESET = """## 身份
全栈工程师，专注 Python 和 TypeScript

## 性格特质
追求简洁，偏好深度思考

## 工作风格
深度专注模式，讨厌打断

## 偏好与习惯
命令行工具，Vim 编辑器

## 核心价值观
代码质量优先，持续学习

## 近期关注
构建 soul-agent 数字灵魂系统"""


SAMPLE_SOUL_CONTENT = """---
type: soul
version: 1
last_evolved: 2026-02-28
evolution_count: 0
---
# 我的数字灵魂

## 身份
全栈工程师，专注 Python 和 TypeScript

## 性格特质
追求简洁，偏好深度思考

## 工作风格
深度专注模式，讨厌打断

## 偏好与习惯
命令行工具，Vim 编辑器

## 核心价值观
代码质量优先，持续学习

## 近期关注
构建 soul-agent 数字灵魂系统

## 成长轨迹
- 2026-02-28: 灵魂初始化"""


class TestInitSoul:
    @patch("soul_agent.modules.soul.call_deepseek")
    def test_init_soul_from_preset(self, mock_llm, engine):
        """Free-text preset → LLM formats into standard structure."""
        from soul_agent.modules.soul import init_soul

        mock_llm.return_value = (
            "## 身份\n全栈工程师\n\n"
            "## 性格特质\n追求简洁\n\n"
            "## 工作风格\n深度专注\n\n"
            "## 偏好与习惯\n命令行工具\n\n"
            "## 核心价值观\n代码质量优先\n\n"
            "## 近期关注\nsoul-agent 项目"
        )

        result = init_soul("我是一名全栈工程师，喜欢 Python", engine)

        assert "type: soul" in result
        assert "version: 1" in result
        assert "evolution_count: 0" in result
        assert "## 身份" in result
        assert "全栈工程师" in result
        assert "## 成长轨迹" in result
        assert "灵魂初始化" in result

        # Verify file was written
        vault = engine._vault
        soul_file = vault / "core" / "SOUL.md"
        assert soul_file.exists()

    def test_init_soul_structured(self, engine):
        """Already structured text → writes directly (no LLM call)."""
        from soul_agent.modules.soul import init_soul

        result = init_soul(STRUCTURED_PRESET, engine)

        assert "type: soul" in result
        assert "## 身份" in result
        assert "全栈工程师" in result
        assert "## 成长轨迹" in result
        assert "灵魂初始化" in result

    @patch("soul_agent.modules.soul.call_deepseek", return_value="")
    def test_init_soul_fallback(self, mock_llm, engine):
        """LLM fails → fallback puts preset in 身份 section."""
        from soul_agent.modules.soul import init_soul

        result = init_soul("我是工程师", engine)

        assert "## 身份" in result
        assert "我是工程师" in result
        assert "（待发现）" in result
        assert "## 成长轨迹" in result


class TestLoadSoul:
    def test_load_existing(self, engine):
        from soul_agent.modules.soul import load_soul

        vault = engine._vault
        (vault / "core" / "SOUL.md").write_text(SAMPLE_SOUL_CONTENT, encoding="utf-8")

        result = load_soul(engine)
        assert result is not None
        assert "我的数字灵魂" in result

    def test_load_missing(self, engine):
        from soul_agent.modules.soul import load_soul

        result = load_soul(engine)
        assert result is None


class TestGetSoulContext:
    def test_returns_summary_without_growth_log(self, engine):
        """Context should include first 6 sections but NOT growth log."""
        from soul_agent.modules.soul import get_soul_context

        vault = engine._vault
        (vault / "core" / "SOUL.md").write_text(SAMPLE_SOUL_CONTENT, encoding="utf-8")

        result = get_soul_context(engine)
        assert "【身份】" in result
        assert "【性格特质】" in result
        assert "【工作风格】" in result
        assert "成长轨迹" not in result
        assert "灵魂初始化" not in result

    def test_returns_empty_when_no_soul(self, engine):
        from soul_agent.modules.soul import get_soul_context

        result = get_soul_context(engine)
        assert result == ""

    def test_skips_empty_sections(self, engine):
        """Sections with （待发现） should be excluded."""
        from soul_agent.modules.soul import get_soul_context

        content = (
            "---\ntype: soul\nversion: 1\nlast_evolved: 2026-02-28\nevolution_count: 0\n---\n"
            "# 我的数字灵魂\n\n"
            "## 身份\n工程师\n\n"
            "## 性格特质\n（待发现）\n\n"
            "## 工作风格\n深度专注\n\n"
            "## 偏好与习惯\n（待发现）\n\n"
            "## 核心价值观\n（待发现）\n\n"
            "## 近期关注\nsoul-agent\n\n"
            "## 成长轨迹\n- 2026-02-28: 初始化"
        )
        vault = engine._vault
        (vault / "core" / "SOUL.md").write_text(content, encoding="utf-8")

        result = get_soul_context(engine)
        assert "【身份】" in result
        assert "【工作风格】" in result
        assert "【近期关注】" in result
        assert "性格特质" not in result
        assert "偏好与习惯" not in result


class TestEvolveSoul:
    @patch("soul_agent.modules.soul.call_deepseek")
    def test_evolve_with_changes(self, mock_llm, engine):
        """LLM returns updates → sections are merged correctly."""
        from soul_agent.modules.soul import evolve_soul

        vault = engine._vault
        (vault / "core" / "SOUL.md").write_text(SAMPLE_SOUL_CONTENT, encoding="utf-8")

        mock_llm.return_value = json.dumps({
            "近期关注": "构建 soul-agent 灵魂系统，探索知识图谱",
            "工作风格": "深度专注模式，倾向长时间编码后集中休息",
        })

        memories = [
            {"text": "连续编码3小时后效率下降"},
            {"text": "对知识图谱产生兴趣"},
        ]

        result = evolve_soul(memories, "今日洞察报告...", engine)
        assert result is True

        # Verify the soul was updated
        updated = (vault / "core" / "SOUL.md").read_text(encoding="utf-8")
        assert "探索知识图谱" in updated
        assert "长时间编码后集中休息" in updated
        assert "evolution_count: 1" in updated
        # Growth log should have new entry
        assert "演进" in updated

    @patch("soul_agent.modules.soul.call_deepseek")
    def test_evolve_no_changes(self, mock_llm, engine):
        """LLM returns empty → no write, returns False."""
        from soul_agent.modules.soul import evolve_soul

        vault = engine._vault
        (vault / "core" / "SOUL.md").write_text(SAMPLE_SOUL_CONTENT, encoding="utf-8")

        mock_llm.return_value = json.dumps({})

        result = evolve_soul(
            [{"text": "普通日常"}],
            "平淡的一天",
            engine,
        )
        assert result is False

        # Verify the soul was NOT updated
        content = (vault / "core" / "SOUL.md").read_text(encoding="utf-8")
        assert "evolution_count: 0" in content

    @patch("soul_agent.modules.soul.call_deepseek", return_value="")
    def test_evolve_fallback_preserves_soul(self, mock_llm, engine):
        """LLM fails → soul is not modified."""
        from soul_agent.modules.soul import evolve_soul

        vault = engine._vault
        (vault / "core" / "SOUL.md").write_text(SAMPLE_SOUL_CONTENT, encoding="utf-8")

        result = evolve_soul(
            [{"text": "some memory"}],
            "some report",
            engine,
        )
        assert result is False

        # Soul should remain unchanged
        content = (vault / "core" / "SOUL.md").read_text(encoding="utf-8")
        assert content == SAMPLE_SOUL_CONTENT

    def test_evolve_no_soul(self, engine):
        """No SOUL.md exists → returns False."""
        from soul_agent.modules.soul import evolve_soul

        result = evolve_soul(
            [{"text": "memory"}],
            "report",
            engine,
        )
        assert result is False


class TestMergeSections:
    def test_merge_updates_correct_sections(self):
        from soul_agent.modules.soul import _merge_sections

        body = (
            "# 我的数字灵魂\n\n"
            "## 身份\n工程师\n\n"
            "## 性格特质\n追求简洁\n\n"
            "## 工作风格\n深度专注\n\n"
            "## 偏好与习惯\n命令行工具\n\n"
            "## 核心价值观\n代码质量\n\n"
            "## 近期关注\nsoul-agent\n\n"
            "## 成长轨迹\n- 2026-02-28: 初始化"
        )

        updates = {"近期关注": "知识图谱研究"}
        result = _merge_sections(body, updates, date(2026, 3, 1))

        assert "知识图谱研究" in result
        assert "工程师" in result  # unchanged
        assert "追求简洁" in result  # unchanged
        assert "2026-03-01" in result  # growth log entry
        assert "近期关注更新" in result

    def test_growth_log_appended(self):
        """Growth log should accumulate, not replace."""
        from soul_agent.modules.soul import _merge_sections

        body = (
            "# 我的数字灵魂\n\n"
            "## 身份\n工程师\n\n"
            "## 性格特质\n追求简洁\n\n"
            "## 工作风格\n深度专注\n\n"
            "## 偏好与习惯\n命令行\n\n"
            "## 核心价值观\n质量\n\n"
            "## 近期关注\nsoul-agent\n\n"
            "## 成长轨迹\n- 2026-02-28: 初始化\n- 2026-03-01: 演进 — 近期关注更新"
        )

        updates = {"身份": "高级全栈工程师"}
        result = _merge_sections(body, updates, date(2026, 3, 2))

        # Both old entries and new one should be present
        assert "2026-02-28: 初始化" in result
        assert "2026-03-01: 演进" in result
        assert "2026-03-02: 演进 — 身份更新" in result

    def test_merge_ignores_growth_log_in_updates(self):
        """Updates dict should not overwrite growth log."""
        from soul_agent.modules.soul import _merge_sections

        body = (
            "# 我的数字灵魂\n\n"
            "## 身份\n工程师\n\n"
            "## 性格特质\n简洁\n\n"
            "## 工作风格\n专注\n\n"
            "## 偏好与习惯\n命令行\n\n"
            "## 核心价值观\n质量\n\n"
            "## 近期关注\nsoul-agent\n\n"
            "## 成长轨迹\n- 2026-02-28: 初始化"
        )

        updates = {"成长轨迹": "should be ignored", "身份": "新身份"}
        result = _merge_sections(body, updates, date(2026, 3, 1))

        assert "should be ignored" not in result
        assert "2026-02-28: 初始化" in result  # original preserved


class TestParseSections:
    def test_parses_correctly(self):
        from soul_agent.modules.soul import _parse_sections

        body = (
            "# Title\n\n"
            "## Section A\nContent A line 1\nContent A line 2\n\n"
            "## Section B\nContent B\n"
        )
        sections = _parse_sections(body)
        assert "Section A" in sections
        assert "Content A line 1" in sections["Section A"]
        assert "Content A line 2" in sections["Section A"]
        assert "Section B" in sections
        assert "Content B" in sections["Section B"]

    def test_empty_body(self):
        from soul_agent.modules.soul import _parse_sections

        assert _parse_sections("") == {}
        assert _parse_sections("# Just a title") == {}


class TestParseEvolveResponse:
    def test_valid_json(self):
        from soul_agent.modules.soul import _parse_evolve_response

        response = json.dumps({"近期关注": "新内容", "身份": "更新身份"})
        result = _parse_evolve_response(response)
        assert result == {"近期关注": "新内容", "身份": "更新身份"}

    def test_json_in_code_block(self):
        from soul_agent.modules.soul import _parse_evolve_response

        response = '```json\n{"近期关注": "新内容"}\n```'
        result = _parse_evolve_response(response)
        assert result == {"近期关注": "新内容"}

    def test_empty_object(self):
        from soul_agent.modules.soul import _parse_evolve_response

        result = _parse_evolve_response("{}")
        assert result == {}

    def test_rejects_growth_log(self):
        from soul_agent.modules.soul import _parse_evolve_response

        response = json.dumps({"成长轨迹": "不应该被接受", "身份": "valid"})
        result = _parse_evolve_response(response)
        assert "成长轨迹" not in result
        assert result == {"身份": "valid"}

    def test_rejects_unknown_sections(self):
        from soul_agent.modules.soul import _parse_evolve_response

        response = json.dumps({"unknown_section": "value", "身份": "valid"})
        result = _parse_evolve_response(response)
        assert "unknown_section" not in result
        assert result == {"身份": "valid"}

    def test_garbage_input(self):
        from soul_agent.modules.soul import _parse_evolve_response

        result = _parse_evolve_response("this is not json")
        assert result == {}


class TestChatWithSoul:
    @patch("soul_agent.modules.soul.call_deepseek")
    def test_chat_with_soul(self, mock_llm, engine):
        """Chat injects soul + memories + insight into prompt."""
        from soul_agent.modules.soul import chat_with_soul

        vault = engine._vault

        # Set up soul
        (vault / "core" / "SOUL.md").write_text(SAMPLE_SOUL_CONTENT, encoding="utf-8")

        # Set up a memory
        (vault / "memories").mkdir(parents=True, exist_ok=True)
        mem_content = (
            "---\ntype: memory\nsource_date: 2026-02-28\n"
            "category: pattern\nimportance: 4\ntags: focus\n---\n"
            "连续编码3小时后效率明显下降"
        )
        (vault / "memories" / "2026-02-28-1.md").write_text(mem_content, encoding="utf-8")

        # Set up an insight
        (vault / "insights").mkdir(parents=True, exist_ok=True)
        insight_content = (
            "---\ntype: insight\ndate: 2026-02-28\n---\n"
            "# 每日洞察\n今天主要在做 soul-agent 灵魂系统开发。"
        )
        (vault / "insights" / "daily-2026-02-28.md").write_text(insight_content, encoding="utf-8")

        mock_llm.return_value = "你最近应该关注 soul-agent 的完善，同时注意每3小时休息一次。"

        answer = chat_with_soul("我最近应该优先关注什么？", engine)

        assert "soul-agent" in answer
        assert "3小时" in answer

        # Verify prompt includes soul, memory, and insight
        call_args = mock_llm.call_args
        prompt = call_args.kwargs.get("prompt", "") or call_args[0][0]
        assert "灵魂画像" in prompt
        assert "连续编码3小时" in prompt
        assert "灵魂系统开发" in prompt

    @patch("soul_agent.modules.soul.call_deepseek")
    def test_chat_no_soul(self, mock_llm, engine):
        """No soul → still works with memories/insight, no soul section in prompt."""
        from soul_agent.modules.soul import chat_with_soul

        mock_llm.return_value = "基于现有信息，建议你先建立灵魂画像。"

        answer = chat_with_soul("你觉得我是什么样的人？", engine)

        assert "灵魂画像" in answer
        # Verify prompt does NOT include soul context
        call_args = mock_llm.call_args
        prompt = call_args.kwargs.get("prompt", "") or call_args[0][0]
        assert "【灵魂画像】" not in prompt

    @patch("soul_agent.modules.soul.call_deepseek", return_value="")
    def test_chat_llm_failure(self, mock_llm, engine):
        """LLM fails → returns fallback text."""
        from soul_agent.modules.soul import chat_with_soul

        vault = engine._vault
        (vault / "core" / "SOUL.md").write_text(SAMPLE_SOUL_CONTENT, encoding="utf-8")

        answer = chat_with_soul("测试问题", engine)

        assert "LLM 暂时不可用" in answer
        assert "灵魂摘要" in answer

    @patch("soul_agent.modules.soul.call_deepseek", return_value="")
    def test_chat_llm_failure_no_soul(self, mock_llm, engine):
        """LLM fails and no soul → specific fallback message."""
        from soul_agent.modules.soul import chat_with_soul

        answer = chat_with_soul("测试问题", engine)

        assert "LLM 暂时不可用" in answer
        assert "mem soul init" in answer
