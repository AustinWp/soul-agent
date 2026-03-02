# Soul Agent

> 你的数字灵魂 — 捕获、分类、反思每日活动，给出洞察与建议。

Soul Agent 作为后台守护进程运行，持续从剪贴板、浏览器、文件系统、键盘输入、终端命令和 Claude Code 六个来源采集信号。通过 LLM 对每条输入进行分类，将结构化日志写入 Obsidian vault，并生成每日洞察和行动建议。

## 架构

```
输入源 (6路)              分类引擎              存储 (Obsidian Vault)
─────────────            ────────              ──────────────────
Clipboard ──┐                                  logs/YYYY-MM-DD.md
Browser ────┤                                  todos/active/*.md
FileWatch ──┤            DeepSeek LLM          todos/done/*.md
Keystroke ──┼─→ IngestQueue ─→ Pipeline ─→     insights/*.md
Terminal ───┤   (batch+dedup)  (classify)      memory/*.md
ClaudeCode ─┘                                  core/MEMORY.md
```

### 组件

| 组件 | 说明 |
|------|------|
| **FastAPI 守护进程** | 监听 `localhost:8330`，7 个 daemon 线程 |
| **CLI** | `soul` 命令 (Typer)，通过 HTTP 调用服务或直连 vault |
| **MCP Server** | 为 LLM 提供 8 个 tool + 6 个 resource（前缀 `soul_` / `soul://`） |
| **LLM** | DeepSeek Chat API (OpenAI 兼容)，失败时规则兜底 |
| **存储** | Obsidian vault，Markdown + YAML frontmatter |
| **自启动** | macOS LaunchAgent，`soul service install/uninstall` 管理 |

## 核心功能

- **6 路输入采集** — 剪贴板轮询(3s)、浏览器历史(5min)、文件监控、键盘捕获、终端命令、Claude Code hook
- **LLM 自动分类** — `coding` / `work` / `learning` / `communication` / `browsing` / `life`
- **每日洞察** — 两阶段报告：语义理解 + 深度建议
- **待办管理** — CRUD + 优先级排序 + 停滞检测
- **记忆系统** — 长期记忆片段 + 语义搜索 + 今日/本周回顾
- **周报/月报聚合** — 自动压缩历史日志为摘要
- **数字灵魂** — 用户画像管理，支持对话式交互 (`soul chat`) 和自我进化 (`soul evolve`)
- **MCP 集成** — 8 个工具 + 6 个资源，可被任意 MCP 客户端调用

## 模块一览

| 模块 | 作用 |
|------|------|
| `daily_log` | 时间序列日志，带内存缓存 |
| `note` | 手动记录入口 |
| `todo` | 待办 CRUD + 优先级 + 停滞检测 |
| `clipboard` | macOS 剪贴板轮询 (3s) |
| `browser` | Chrome/Safari 历史轮询 (5min) |
| `filewatcher` | Desktop/Documents/Downloads 文件变动 |
| `input_hook` | macOS CGEventTap 键盘捕获 |
| `terminal` | zsh hook 终端命令捕获 |
| `claude_code` | Claude Code postToolUse hook 集成 |
| `classifier` | LLM 批量分类 (6 个类别) |
| `pipeline` | 分类 → 日志 → 动作分发 |
| `insight` | 两阶段日报/周报 (语义理解 + 深度建议) |
| `compact` | 周报/月报聚合 |
| `recall` | 记忆检索 + 今日/本周回顾 |
| `memory` | 长期记忆片段管理 |
| `soul` | 数字灵魂画像管理 |

## 快速开始

```bash
# 安装
pip install -e .

# 启动守护进程
soul service start

# 查看状态
soul service status

# 安装开机自启
soul service install

# 记一条笔记
soul note "完成了 API 重构"

# 查看今日回顾
soul recall today

# 生成每日洞察
soul insight today

# 获取工作建议
soul insight suggest

# 和灵魂对话
soul soul chat "我今天做的怎么样"
```

## CLI 命令

```
soul note           记录一条笔记
soul search         跨全部记忆语义搜索
soul recall         今日回顾 / --week 本周回顾
soul compact        压缩日志为周报/月报

soul todo add       添加待办
soul todo ls        列出待办
soul todo done      完成待办
soul todo rm        删除待办

soul insight today  今日洞察报告
soul insight week   本周洞察报告
soul insight tasks  活跃/停滞任务
soul insight suggest 工作建议

soul service start|stop|status     守护进程管理
soul service install|uninstall     LaunchAgent 自启动

soul clipboard status              剪贴板监控状态
soul terminal start|stop|status    终端命令监控
soul input-hook start|stop|status  键盘捕获控制

soul core show|edit                永久记忆 (MEMORY.md)
soul memory ls|search              长期记忆管理

soul soul init|show|chat|evolve    数字灵魂管理
soul claudecode install|uninstall  Claude Code hook
```

## MCP Server

MCP Server 暴露以下接口，可被 Claude Code 等 MCP 客户端直接调用：

**Tools (8)**

| Tool | 说明 |
|------|------|
| `soul_search` | 语义搜索 |
| `soul_recall` | 按时段回忆 |
| `soul_insight` | 每日洞察报告 |
| `soul_categories` | 时间分配统计 |
| `soul_todos` | 待办列表 |
| `soul_suggest` | AI 建议 |
| `soul_note` | 记录笔记 |
| `soul_task_progress` | 待办进度追踪 |

**Resources (6)**

| URI | 说明 |
|-----|------|
| `soul://insight/today` | 今日洞察 |
| `soul://insight/week` | 本周洞察 |
| `soul://todos/active` | 活跃待办 |
| `soul://todos/stalled` | 停滞待办 |
| `soul://core/memory` | 核心记忆 |
| `soul://stats/categories` | 分类统计 |

## 配置

编辑 `config/soul.json`：

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

在 `.env` 中设置 API Key：

```
DEEPSEEK_API_KEY=your-key-here
```

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 | — |
| `SOUL_AGENT_URL` | 服务地址 | `http://localhost:8330` |
| `SOUL_AGENT_ENABLED` | 是否启用 shell hook | — |

## 项目结构

```
soul_agent/
├── cli.py                 # Typer CLI 入口
├── service.py             # FastAPI 守护进程
├── mcp_server.py          # MCP Server
├── core/
│   ├── vault.py           # VaultEngine 单例
│   ├── config.py          # 配置加载
│   ├── llm.py             # LLM API 封装
│   ├── queue.py           # 摄入队列 + 去重
│   └── frontmatter.py     # YAML frontmatter 解析
├── modules/               # 14 个功能模块
│   ├── clipboard.py       # 剪贴板采集
│   ├── browser.py         # 浏览器历史采集
│   ├── filewatcher.py     # 文件监控
│   ├── input_hook.py      # 键盘捕获
│   ├── terminal.py        # 终端命令采集
│   ├── claude_code.py     # Claude Code hook
│   ├── classifier.py      # LLM 分类器
│   ├── pipeline.py        # 分类管线
│   ├── daily_log.py       # 每日日志
│   ├── note.py            # 笔记
│   ├── todo.py            # 待办
│   ├── insight.py         # 洞察报告
│   ├── compact.py         # 聚合压缩
│   ├── recall.py          # 记忆检索
│   ├── memory.py          # 长期记忆
│   └── soul.py            # 数字灵魂
├── hooks/
│   └── claude_code_hook.sh
├── launchd/
│   └── com.soul-agent.daemon.plist
config/
└── soul.json
tests/                     # 19 个测试文件
```

## 开发

```bash
# 开发模式安装
pip install -e .

# 运行全部测试
python -m pytest tests/ -v

# 运行单个测试
python -m pytest tests/test_pipeline.py -v
```

### 开发约定

- Python 3.10+，全程使用类型注解
- 模块为无状态函数 + 模块级状态字典（仅 VaultEngine 使用类）
- 所有 vault 文件使用 YAML frontmatter 元数据
- 线程安全：`threading.Lock` 保护共享状态
- LLM 优雅降级：API 失败时有基于规则的兜底
- 测试使用 `tmp_path` fixture，mock LLM 调用
- 面向用户的洞察/报告内容使用中文

## 许可证

MIT
