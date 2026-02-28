# soul-agent

Personal digital soul — captures, classifies, and reflects on daily activity.

## Vision

构建一个与用户同步的数字灵魂：基于每天的所有输入给出洞察和建议，跟进待办和在研项目。

## Architecture

```
输入源 (5路)              分类引擎              存储 (Obsidian Vault)
─────────────            ────────              ──────────────────
Clipboard ──┐                                  logs/YYYY-MM-DD.md
Browser ────┤            DeepSeek LLM          todos/active/*.md
FileWatch ──┼─→ IngestQueue ─→ Pipeline ─→     todos/done/*.md
Keystroke ──┤   (batch+dedup)  (classify)      insights/*.md
ClaudeCode ─┘                                  core/MEMORY.md
```

- **后台服务**: FastAPI daemon on `localhost:8330`, 7个 daemon 线程
- **CLI**: `soul` 命令 (Typer), 通过 HTTP 调用 service 或直连 vault
- **MCP Server**: 为 LLM 提供 tool/resource 接口
- **LLM**: DeepSeek Chat API (OpenAI-compatible)
- **存储**: Obsidian vault, markdown + YAML frontmatter

## Key Paths

| What | Path |
|------|------|
| Vault | `/Users/austin/Desktop/我的知识库/数字灵魂` |
| Config | `config/mem.json` |
| PID/Logs | `~/.soul-agent/` |
| CLI entry | `soul_agent/cli.py` → `pyproject.toml [project.scripts] soul` |
| Service | `soul_agent/service.py` (FastAPI, port 8330) |
| Core engine | `soul_agent/core/vault.py` (VaultEngine singleton) |
| Queue/Pipeline | `soul_agent/core/queue.py` → `soul_agent/modules/pipeline.py` |
| Classification | `soul_agent/modules/classifier.py` |

## Module Map

| Module | Role |
|--------|------|
| `daily_log` | 时间序列日志, 带内存缓存 |
| `note` | 手动记录入口 |
| `todo` | 待办 CRUD + 优先级 + 停滞检测 |
| `clipboard` | macOS 剪贴板轮询 (3s) |
| `browser` | Chrome/Safari 历史轮询 (5min) |
| `filewatcher` | Desktop/Documents/Downloads 文件变动 |
| `input_hook` | macOS CGEventTap 键盘捕获 |
| `classifier` | LLM 批量分类 (6 categories) |
| `pipeline` | 分类 → 日志 → 动作分发 |
| `insight` | 两阶段日报 (语义理解 + 深度建议) |
| `compact` | 周报/月报聚合 |
| `recall` | 记忆检索 + 今日/本周回顾 |
| `terminal` | 终端命令捕获 |
| `claude_code` | Claude Code hook 集成 |

## Categories

`coding` | `work` | `learning` | `communication` | `browsing` | `life`

## Development

```bash
# Install
pip install -e .

# Run tests
python -m pytest tests/ -v

# Start service
soul service start

# Check status
soul service status
```

## Conventions

- Python 3.10+, type hints throughout
- Modules are stateless functions + module-level state dicts (no classes except VaultEngine)
- Frontmatter (YAML) for metadata on all vault files
- Thread-safe: `threading.Lock` guards shared state
- Graceful LLM fallback: all LLM calls have rule-based fallback on API failure
- Tests use tmp_path fixtures, mock LLM calls
- Chinese language for user-facing insight/report content
