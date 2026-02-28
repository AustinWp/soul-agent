"""DeepSeek API call wrapper using OpenAI-compatible client."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# Proxy env vars that interfere with OpenAI SDK (e.g. SOCKS proxy)
_PROXY_VARS = ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY")


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

    # Temporarily clear proxy env vars to avoid SOCKS/HTTP proxy interference
    saved = {k: os.environ.pop(k) for k in _PROXY_VARS if k in os.environ}
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
    finally:
        os.environ.update(saved)
