"""Configuration loading for mem-agent."""

from __future__ import annotations

import json
import os
from pathlib import Path


DEFAULT_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "ov.conf"
DATA_DIR = Path.home() / ".mem-agent" / "data"


def _expand_env_vars(obj: dict | list | str) -> dict | list | str:
    """Recursively expand ${VAR} references in config values."""
    if isinstance(obj, str):
        for key, value in os.environ.items():
            obj = obj.replace(f"${{{key}}}", value)
        return obj
    if isinstance(obj, dict):
        return {k: _expand_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env_vars(item) for item in obj]
    return obj


def load_config(config_path: str | Path | None = None) -> dict:
    """Load and return the OpenViking configuration with env vars expanded."""
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return _expand_env_vars(raw)


def get_data_dir() -> Path:
    """Return (and create) the local data directory for OpenViking storage."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def get_deepseek_api_key(config: dict | None = None) -> str:
    """Extract DeepSeek API key from config or environment."""
    if config:
        key = config.get("vlm", {}).get("api_key", "")
        if key and not key.startswith("${"):
            return key
    return os.environ.get("DEEPSEEK_API_KEY", "")
