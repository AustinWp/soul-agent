"""Configuration loading for soul-agent."""

from __future__ import annotations

import json
import os
from pathlib import Path


DEFAULT_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "soul.json"
_ENV_FILE = Path(__file__).parent.parent.parent / ".env"


def _load_dotenv() -> None:
    """Load .env file into os.environ if it exists (does not overwrite)."""
    if not _ENV_FILE.exists():
        return
    for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if value and not os.environ.get(key):
            os.environ[key] = value


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
    """Load and return the configuration with env vars expanded."""
    _load_dotenv()
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return _expand_env_vars(raw)


def get_vault_path(config: dict) -> Path:
    """Return the Obsidian vault path from config."""
    return Path(config["vault_path"])


def get_deepseek_api_key(config: dict | None = None) -> str:
    """Extract DeepSeek API key from config or environment."""
    _load_dotenv()
    if config:
        key = config.get("llm", {}).get("api_key", "")
        if key and not key.startswith("${"):
            return key
    return os.environ.get("DEEPSEEK_API_KEY", "")
