# Soul Agent

> A personal digital soul that captures, classifies, and reflects on your daily activity.

Soul Agent runs as a background daemon, continuously collecting signals from your clipboard, browser, file system, keyboard, and terminal. It classifies every input via LLM, writes structured logs to an Obsidian vault, and generates daily insights and suggestions.

## Architecture

```
Input Sources (5)         Classification          Storage (Obsidian Vault)
─────────────────        ──────────────          ──────────────────────
Clipboard ──┐                                    logs/YYYY-MM-DD.md
Browser ────┤            DeepSeek LLM            todos/active/*.md
FileWatch ──┼─→ IngestQueue ─→ Pipeline ─→       todos/done/*.md
Keystroke ──┤   (batch+dedup)  (classify)        insights/*.md
Terminal ───┘                                    core/MEMORY.md
```

- **Backend**: FastAPI daemon on `localhost:8330`
- **CLI**: `soul` command (Typer)
- **MCP Server**: Tool/resource interface for LLMs
- **LLM**: DeepSeek Chat API (OpenAI-compatible)
- **Storage**: Obsidian vault with Markdown + YAML frontmatter

## Features

- **5 input sources** — clipboard polling, browser history, file watcher, keystroke capture, terminal commands
- **LLM classification** — auto-categorizes every event into `coding` / `work` / `learning` / `communication` / `browsing` / `life`
- **Daily insights** — two-stage reports: semantic understanding + actionable suggestions
- **Todo tracking** — priority management with stall detection
- **Memory recall** — semantic search across your digital history
- **Weekly/monthly compaction** — aggregated summaries over time

## Quick Start

```bash
# Install
pip install -e .

# Start the daemon
soul service start

# Check status
soul service status

# Add a manual note
soul note "Finished the API redesign"

# View today's log
soul recall today

# Generate daily insight
soul insight
```

## Development

```bash
# Install in dev mode
pip install -e .

# Run tests
python -m pytest tests/ -v

# Run a specific test
python -m pytest tests/test_pipeline.py -v
```

## Configuration

Copy and edit `config/mem.json`:

```json
{
  "vault_path": "/path/to/your/obsidian/vault",
  "llm": {
    "provider": "openai",
    "model": "deepseek-chat",
    "api_key": "${DEEPSEEK_API_KEY}",
    "api_base": "https://api.deepseek.com/v1"
  }
}
```

Set your API key in `.env`:

```
DEEPSEEK_API_KEY=your-key-here
```

## License

MIT
