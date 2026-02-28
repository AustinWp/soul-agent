"""DeepSeek API call wrapper using OpenAI-compatible client."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


def call_deepseek(
    prompt: str,
    system: str = "",
    max_tokens: int = 512,
    config: dict | None = None,
) -> str:
    """Call DeepSeek chat API and return the response text.

    Uses openai.OpenAI with DeepSeek base_url.
    Returns empty string on any error.
    """
    from openai import OpenAI

    from .config import get_deepseek_api_key

    api_key = get_deepseek_api_key(config)
    if not api_key:
        return ""

    try:
        client = OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com",
        )

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            max_tokens=max_tokens,
        )

        return response.choices[0].message.content or ""
    except Exception:
        return ""
