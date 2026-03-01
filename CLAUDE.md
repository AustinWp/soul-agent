# soul-agent

个人数字灵魂 — 捕获、分类并反思每日活动。

## 愿景

构建一个与用户同步的数字灵魂：基于每天的所有输入给出洞察和建议，跟进待办和在研项目。

## 架构

```
输入源 (5路)              分类引擎              存储 (Obsidian Vault)
─────────────            ────────              ──────────────────
Clipboard ──┐                                  logs/YYYY-MM-DD.md
Browser ────┤            DeepSeek LLM          todos/active/*.md
FileWatch ──┼─→ IngestQueue ─→ Pipeline ─→     todos/done/*.md
Keystroke ──┤   (batch+dedup)  (classify)      insights/*.md
ClaudeCode ─┘                                  core/MEMORY.md
```

- **后台服务**: FastAPI daemon，监听 `localhost:8330`，7 个 daemon 线程
- **CLI**: `soul` 命令 (Typer)，通过 HTTP 调用 service 或直连 vault
- **MCP Server**: 为 LLM 提供 tool/resource 接口（tool 前缀 `soul_`，资源 URI 前缀 `soul://`）
- **LLM**: DeepSeek Chat API (OpenAI 兼容)
- **存储**: Obsidian vault，markdown + YAML frontmatter
- **自启动**: LaunchAgent plist，通过 `soul service install/uninstall` 管理

## 关键路径

| 内容 | 路径 |
|------|------|
| Vault | `/Users/austin/Desktop/我的知识库/数字灵魂` |
| 配置文件 | `config/soul.json` |
| PID/日志 | `~/.soul-agent/` |
| CLI 入口 | `soul_agent/cli.py` → `pyproject.toml [project.scripts] soul` |
| 服务 | `soul_agent/service.py` (FastAPI, 端口 8330) |
| 核心引擎 | `soul_agent/core/vault.py` (VaultEngine 单例) |
| 队列/管线 | `soul_agent/core/queue.py` → `soul_agent/modules/pipeline.py` |
| 分类器 | `soul_agent/modules/classifier.py` |
| LaunchAgent 模板 | `soul_agent/launchd/com.soul-agent.daemon.plist` |

## 模块一览

| 模块 | 作用 |
|--------|------|
| `daily_log` | 时间序列日志，带内存缓存 |
| `note` | 手动记录入口 |
| `todo` | 待办 CRUD + 优先级 + 停滞检测 |
| `clipboard` | macOS 剪贴板轮询 (3s) |
| `browser` | Chrome/Safari 历史轮询 (5min) |
| `filewatcher` | Desktop/Documents/Downloads 文件变动 |
| `input_hook` | macOS CGEventTap 键盘捕获 |
| `classifier` | LLM 批量分类 (6 个类别) |
| `pipeline` | 分类 → 日志 → 动作分发 |
| `insight` | 两阶段日报 (语义理解 + 深度建议) |
| `compact` | 周报/月报聚合 |
| `recall` | 记忆检索 + 今日/本周回顾 |
| `terminal` | 终端命令捕获 |
| `claude_code` | Claude Code hook 集成 |

## 分类类别

`coding` | `work` | `learning` | `communication` | `browsing` | `life`

## 开发

```bash
# 安装
pip install -e .

# 运行测试
python -m pytest tests/ -v

# 启动服务
soul service start

# 查看状态
soul service status

# 安装开机自启
soul service install

# 卸载开机自启
soul service uninstall
```

## Shell Hook 环境变量

zsh hook 和 quick_note 脚本使用以下环境变量（前缀均为 `SOUL_AGENT_`）：

- `SOUL_AGENT_URL` — 服务地址（默认 `http://localhost:8330`）
- `SOUL_AGENT_ENABLED` — 是否启用 hook

## 开发约定

- Python 3.10+，全程使用类型注解
- 模块为无状态函数 + 模块级状态字典（仅 VaultEngine 使用类）
- 所有 vault 文件使用 Frontmatter (YAML) 元数据
- 线程安全：`threading.Lock` 保护共享状态
- LLM 优雅降级：所有 LLM 调用在 API 失败时有基于规则的兜底
- 测试使用 `tmp_path` fixture，mock LLM 调用
- 面向用户的洞察/报告内容使用中文
