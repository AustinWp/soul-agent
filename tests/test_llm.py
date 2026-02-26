"""Tests for core/llm.py — DeepSeek API call wrapper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestCallDeepseek:
    @patch("openai.OpenAI")
    @patch("mem_agent.core.config.get_deepseek_api_key", return_value="sk-test")
    def test_basic_call(self, mock_key, mock_openai_cls):
        from mem_agent.core.llm import call_deepseek

        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "test response"
        mock_client.chat.completions.create.return_value = mock_response

        result = call_deepseek("hello", system="be helpful")

        assert result == "test response"
        mock_openai_cls.assert_called_once_with(
            api_key="sk-test",
            base_url="https://api.deepseek.com",
        )
        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    @patch("openai.OpenAI")
    @patch("mem_agent.core.config.get_deepseek_api_key", return_value="sk-test")
    def test_no_system_prompt(self, mock_key, mock_openai_cls):
        from mem_agent.core.llm import call_deepseek

        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "response"
        mock_client.chat.completions.create.return_value = mock_response

        call_deepseek("hello")

        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"

    @patch("mem_agent.core.config.get_deepseek_api_key", return_value="")
    def test_no_api_key_returns_empty(self, mock_key):
        from mem_agent.core.llm import call_deepseek

        result = call_deepseek("hello")
        assert result == ""

    @patch("openai.OpenAI")
    @patch("mem_agent.core.config.get_deepseek_api_key", return_value="sk-test")
    def test_api_error_returns_empty(self, mock_key, mock_openai_cls):
        from mem_agent.core.llm import call_deepseek

        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = Exception("API error")

        result = call_deepseek("hello")
        assert result == ""

    @patch("openai.OpenAI")
    @patch("mem_agent.core.config.get_deepseek_api_key", return_value="sk-test")
    def test_none_content_returns_empty(self, mock_key, mock_openai_cls):
        from mem_agent.core.llm import call_deepseek

        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = None
        mock_client.chat.completions.create.return_value = mock_response

        result = call_deepseek("hello")
        assert result == ""
