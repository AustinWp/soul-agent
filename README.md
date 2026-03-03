# Soul Agent

> 个人数字灵魂 — 持续采集你的数字活动，自动分类存档，生成洞察与行动建议。

Soul Agent 是一个运行在 macOS 上的后台守护进程。它从 6 个来源实时采集信号，通过 LLM 分类引擎将每条输入结构化后写入 Obsidian vault，并在每日固定时间生成工作洞察和建议。整个系统围绕「捕获 → 分类 → 存储 → 反思」闭环设计。

## 目录

- [核心功能](#核心功能)
- [架构总览](#架构总览)
- [技术方案](#技术方案)
  - [数据采集层](#1-数据采集层6-路输入源)
  - [队列与去重](#2-队列与去重)
  - [分类引擎](#3-分类引擎)
  - [分发管线](#4-分发管线)
  - [存储层](#5-存储层obsidian-vault)
  - [洞察系统](#6-洞察系统)
  - [记忆与灵魂](#7-记忆与灵魂系统)
  - [服务与进程管理](#8-服务与进程管理)
- [CLI 命令](#cli-命令)
- [MCP Server](#mcp-server)
- [快速开始](#快速开始)
- [配置](#配置)
- [项目结构](#项目结构)
- [开发](#开发)

## 核心功能

- **6 路实时采集** — 剪贴板(3s)、浏览器历史(5min)、文件系统(实时)、终端命令、Claude Code 工具调用、键盘输入，全天候静默运行
- **LLM 自动分类** — 每条输入经 DeepSeek 分类为 `coding` / `work` / `learning` / `communication` / `browsing` / `life`，附带重要度评分和中文摘要
- **智能待办管理** — 从输入中自动识别任务意图，创建/更新待办；支持停滞检测和 LLM 语义去重合并
- **每日洞察报告** — 两阶段分析：先提炼工作事项，再结合任务状态和历史记忆生成可执行建议
- **长期记忆系统** — 自动从洞察中提取高重要度记忆片段，支持语义搜索和今日/本周回顾
- **数字灵魂画像** — 基于持续积累的记忆自动进化用户画像，支持对话式交互
- **Obsidian 原生存储** — 全部数据为 Markdown + YAML frontmatter，天然兼容 Obsidian 双向链接和插件生态
- **MCP 协议集成** — 8 个工具 + 6 个资源，可被 Claude Desktop 等 MCP 客户端直接调用

## 架构总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                         macOS 后台守护进程                          │
│                    FastAPI · localhost:8330                         │
│                                                                     │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────────┐    │
│  │  输入源 (6路)  │   │  IngestQueue │   │   Pipeline            │    │
│  │              │   │              │   │                      │    │
│  │ Clipboard ───┤   │  batch=10    │   │  Classifier (LLM)   │    │
│  │ Browser ─────┤   │  dedup=60s   │   │       ↓              │    │
│  │ FileWatch ───┼──→│  flush=60s   │──→│  DailyLog 写入      │    │
│  │ Terminal ────┤   │              │   │       ↓              │    │
│  │ ClaudeCode ──┤   │  thread-safe │   │  Todo 创建/更新     │    │
│  │ InputHook ───┘   └──────────────┘   └──────────────────────┘    │
│                                                                     │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────────┐    │
│  │  Insight      │   │  Compaction  │   │  Soul Evolution     │    │
│  │  每日 20:00   │   │  每日检查    │   │  基于洞察自动触发    │    │
│  │  生成日报     │   │  生成周报    │   │  更新用户画像       │    │
│  └──────────────┘   └──────────────┘   └──────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
                              ↕ 读写
                   ┌──────────────────────┐
                   │   Obsidian Vault      │
                   │                      │
                   │  logs/YYYY-MM-DD.md  │
                   │  todos/active/*.md   │
                   │  todos/done/*.md     │
                   │  insights/*.md       │
                   │  memory/*.md         │
                   │  core/MEMORY.md      │
                   │  soul/profile.md     │
                   └──────────────────────┘
```

## 技术方案

### 1. 数据采集层（6 路输入源）

每个输入源作为独立的 daemon 线程运行，采集到的数据统一包装为 `IngestItem` 投入中央队列。

| 输入源 | 模块 | 采集机制 | 频率 |
|--------|------|----------|------|
| **Clipboard** | `clipboard.py` | `NSPasteboard` 轮询，检测 `changeCount` 变化 | 3 秒 |
| **Browser** | `browser.py` | 读取 Chrome/Safari 的 SQLite 历史数据库 | 5 分钟 |
| **FileWatch** | `filewatcher.py` | `watchdog` 库监听 Desktop/Documents/Downloads | 实时事件 |
| **Terminal** | `terminal.py` | zsh `preexec`/`precmd` hook → HTTP POST 到 daemon | 每条命令 |
| **Claude Code** | `claude_code.py` | `PostToolUse` hook，stdin 读取工具摘要 → HTTP POST | 每次工具调用 |
| **Input Hook** | `input_hook.py` | `CGEventTap` 捕获键盘事件，聚合为输入片段 | 实时事件 |

**FileWatch 去噪策略**：
- 忽略 40+ 种二进制扩展名、隐藏文件、编辑器临时文件
- 忽略 `.git`、`node_modules`、`__pycache__`、vault 自身目录等
- 5 秒窗口去重，防止 `created` + `modified` 双触发
- 只记录「文件名 + 操作类型」，不读取文件内容

**Terminal Hook 机制**：
```
用户输入命令 → zsh preexec 记录命令文本和开始时间
命令结束    → zsh precmd 计算耗时，POST 到 /terminal/cmd
daemon 端   → 缓冲 20 条或 30 分钟后批量 flush 入队列
```

**Claude Code Hook 机制**：
```
Claude Code 执行工具 → PostToolUse hook 触发
hook shell 脚本     → 从 stdin 读取工具摘要
curl POST           → 发送到 /ingest/claudecode → 直接入队列
```

### 2. 队列与去重

`IngestQueue` 是整个系统的中枢，所有输入源的数据在此汇聚。

```python
IngestQueue(batch_size=10, flush_interval=60, dedup_window=60)
```

- **批量处理**：累积 10 条或等待 60 秒后释放一个 batch
- **SHA-256 去重**：60 秒窗口内相同文本的条目自动丢弃
- **线程安全**：`threading.Lock` + `threading.Event` 实现生产者-消费者模式
- **背压控制**：消费者（Pipeline 线程）以 2 秒超时轮询 batch

### 3. 分类引擎

每个 batch 通过 `classify_batch()` 发送给 DeepSeek LLM，返回结构化 JSON。

**分类维度**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `category` | enum | `coding` / `work` / `learning` / `communication` / `browsing` / `life` |
| `tags` | list | 中文关键词标签 |
| `importance` | 1-5 | 1=琐碎, 5=关键 |
| `summary` | string | 一句话中文摘要 |
| `action_type` | nullable | `null` / `new_task` / `update_task` |
| `action_detail` | nullable | 动作描述 |
| `related_todo_id` | nullable | 关联待办 ID |

**Todo 创建约束**（防止噪音堆积）：
- `file` / `browser` / `clipboard` 来源禁止创建任务
- `importance <= 2` 的条目禁止创建任务
- 优先 `update_task` 关联已有待办
- "评估/探索/了解" 类描述不创建任务

**降级策略**：LLM 调用失败时，根据 `source → category` 映射表进行规则兜底分类（`terminal→coding`、`browser→browsing` 等）。

### 4. 分发管线

Pipeline 线程从队列取出 batch，经分类后执行三个动作：

```
ClassifiedItem
    ├── append_daily_log()     # 必做：写入时间序列日志
    ├── add_todo()             # 可选：action_type=new_task 且通过源过滤
    └── update_todo_activity() # 可选：action_type=task_progress
```

### 5. 存储层（Obsidian Vault）

所有数据以 Markdown + YAML frontmatter 格式存储在 Obsidian vault 中，天然支持双向链接和全文搜索。

```yaml
---
date: "2026-03-03"
sources: clipboard, browser, file, terminal
entry_count: 967
---
[09:45] (clipboard) [work] 人员调动表格内容
[09:47] (browser) [work] Visited: POPO文档 — https://...
[10:02] (file) [coding] File modified: pipeline.py
[10:15] (terminal) [coding] Terminal commands: $ git status ...
```

**目录结构**：
| 目录 | 内容 | 文件命名 |
|------|------|----------|
| `logs/` | 每日时间序列日志 | `YYYY-MM-DD.md` |
| `todos/active/` | 活跃待办 | `{8位hex}.md` |
| `todos/done/` | 已完成待办 | 同上 |
| `insights/` | 日报/周报 | `daily-YYYY-MM-DD.md` / `YYYY-Wxx.md` |
| `memory/` | 长期记忆片段 | `mem-YYYY-MM-DD-{hash}.md` |
| `core/` | 永久记忆 | `MEMORY.md` |
| `soul/` | 数字灵魂画像 | `profile.md` |

### 6. 洞察系统

**两阶段 LLM 分析**（每日 20:00 自动触发，也可 `--force` 手动触发）：

```
Phase 1: 语义理解
  输入：日志聚类 + 用户笔记
  输出：今日工作事项列表（去噪、去重、提炼）

Phase 2: 深度洞察
  输入：工作总结 + 活跃任务 + 停滞任务 + 长期记忆 + 用户画像
  输出：2-4 条可执行的建议（聚焦未完成事项、优先级判断、遗忘提醒）
```

**数据预处理**：
- 噪音过滤：`.tmp`、`.crdownload`、`~$` 等
- 浏览去重：同一 URL 只保留首次访问
- 时段聚类：连续同类条目合并为摘要组（上午/下午/晚上）

**聚合压缩**：
- 周报：每日检查上周报告是否存在，缺失则自动生成
- 月报：手动触发 `soul compact --month`

### 7. 记忆与灵魂系统

**长期记忆**：洞察报告生成后，自动提取 `importance >= 4` 的记忆片段存入 `memory/` 目录。支持按重要度筛选和语义搜索。

**数字灵魂**：
- `soul init` — 基于用户自我描述生成初始画像
- `soul chat` — 基于画像 + 记忆上下文的对话式交互
- `soul evolve` — 每次生成洞察后自动触发，结合新记忆更新画像

**Todo 智能合并**：
- `soul todo merge --dry-run` — LLM 语义比较，找出可合并的重复待办
- `soul todo merge --execute` — 执行合并

### 8. 服务与进程管理

**FastAPI daemon** (端口 8330)：
- 7 个 daemon 线程：Pipeline、Clipboard、Browser、FileWatch、Insight、Compaction、（可选）InputHook
- `lifespan` 上下文管理器统一管理线程生命周期
- `.env` 自动加载（DeepSeek API Key 等）

**进程管理**：
- PID 文件：`~/.soul-agent/daemon.pid`
- 日志文件：`~/.soul-agent/service.log`
- LaunchAgent：`soul service install` 写入 plist，开机自启

**LLM 代理处理**：调用 DeepSeek API 前临时清除 `http_proxy`/`https_proxy` 环境变量（避免 SOCKS 代理干扰 OpenAI SDK），调用完毕后恢复。

## CLI 命令

```
soul note [TEXT]                  记录笔记（省略 TEXT 进入交互模式）
soul search QUERY                 跨全部记忆语义搜索
soul recall [--week]              今日回顾 / 本周回顾
soul compact [--month]            压缩为周报 / 月报

soul todo add TEXT [--due DATE]   添加待办
soul todo ls                      列出活跃待办
soul todo done ID                 完成待办
soul todo rm ID                   删除待办
soul todo merge [--execute]       智能合并重复待办

soul insight today [--force]      今日洞察（--force 强制重新生成并保存）
soul insight week                 本周洞察
soul insight tasks                活跃/停滞任务
soul insight suggest              工作建议

soul service start|stop|status    守护进程管理
soul service install|uninstall    LaunchAgent 自启动管理

soul clipboard status             剪贴板监控状态
soul terminal start|stop|status   终端命令监控
soul input-hook start|stop|status 键盘捕获控制

soul core show|edit               永久记忆管理
soul memory ls|search             长期记忆管理

soul soul init|show|chat|evolve   数字灵魂管理
soul claudecode install|uninstall Claude Code hook 管理
```

## MCP Server

MCP Server 作为独立进程运行，通过 HTTP 代理到 daemon 的 API。可被任意 MCP 客户端（Claude Desktop 等）调用。

**Tools (8)**

| Tool | 说明 |
|------|------|
| `soul_search` | 语义搜索全部记忆和资源 |
| `soul_recall` | 按时段（今日/本周）回忆 |
| `soul_insight` | 获取每日洞察报告 |
| `soul_categories` | 时间分配统计 |
| `soul_todos` | 待办列表 |
| `soul_suggest` | AI 工作建议 |
| `soul_note` | 记录笔记 |
| `soul_task_progress` | 待办进度追踪 |

**Resources (6)**

| URI | 说明 |
|-----|------|
| `soul://insight/today` | 今日洞察 |
| `soul://insight/week` | 本周洞察 |
| `soul://todos/active` | 活跃待办 |
| `soul://todos/stalled` | 停滞待办 |
| `soul://core/memory` | 核心永久记忆 |
| `soul://stats/categories` | 分类统计 |

## 快速开始

```bash
# 安装（Python 3.10+）
pip install -e .

# 启动守护进程
soul service start

# 安装开机自启
soul service install

# 安装 Claude Code hook（可选）
soul claudecode install

# 安装终端 hook（可选）
soul terminal start

# 记一条笔记
soul note "完成了 API 重构"

# 查看今日回顾
soul recall

# 生成今日洞察
soul insight today --force

# 查看活跃待办
soul todo ls

# 和灵魂对话
soul soul chat "我今天做的怎么样"
```

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

**环境变量**

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 | — |
| `SOUL_AGENT_URL` | 服务地址 | `http://localhost:8330` |
| `SOUL_AGENT_ENABLED` | 是否启用 shell hook | — |

## 项目结构

```
soul-agent/
├── pyproject.toml              # 项目元数据 + 依赖
├── config/
│   └── soul.json               # vault 路径 + LLM 配置
├── soul_agent/
│   ├── cli.py                  # Typer CLI 入口 (soul 命令)
│   ├── service.py              # FastAPI daemon (端口 8330)
│   ├── mcp_server.py           # MCP Server (8 tools + 6 resources)
│   ├── core/
│   │   ├── vault.py            # VaultEngine 单例 — vault 读写抽象
│   │   ├── config.py           # JSON 配置加载 + env 变量解析
│   │   ├── llm.py              # DeepSeek API 封装 (OpenAI 兼容)
│   │   ├── queue.py            # IngestQueue — 批量 + 去重
│   │   └── frontmatter.py      # YAML frontmatter 解析/构建
│   ├── modules/
│   │   ├── clipboard.py        # 剪贴板采集 (NSPasteboard)
│   │   ├── browser.py          # 浏览器历史采集 (SQLite)
│   │   ├── filewatcher.py      # 文件监控 (watchdog)
│   │   ├── input_hook.py       # 键盘捕获 (CGEventTap)
│   │   ├── terminal.py         # 终端命令采集 (zsh hook)
│   │   ├── claude_code.py      # Claude Code hook 管理
│   │   ├── classifier.py       # LLM 批量分类器
│   │   ├── pipeline.py         # 分类 → 日志 → 动作分发
│   │   ├── daily_log.py        # 每日时间序列日志
│   │   ├── note.py             # 手动笔记
│   │   ├── todo.py             # 待办 CRUD + 停滞检测 + 智能合并
│   │   ├── insight.py          # 两阶段洞察 (语义理解 + 深度建议)
│   │   ├── compact.py          # 周报/月报聚合
│   │   ├── recall.py           # 记忆检索 + 回顾
│   │   ├── memory.py           # 长期记忆片段管理
│   │   └── soul.py             # 数字灵魂画像
│   ├── hooks/
│   │   ├── claude_code_hook.sh # Claude Code PostToolUse hook
│   │   └── zsh_hook.sh         # Terminal preexec/precmd hook
│   └── launchd/
│       └── com.soul-agent.daemon.plist  # macOS LaunchAgent 模板
└── tests/                      # 19 个测试文件
```

## 开发

```bash
# 开发模式安装
pip install -e .

# 运行全部测试
python -m pytest tests/ -v

# 运行单个测试
python -m pytest tests/test_pipeline.py -v

# 启动服务（前台调试）
uvicorn soul_agent.service:app --host 127.0.0.1 --port 8330 --reload
```

### 技术约定

- Python 3.10+，全程类型注解
- 模块设计：无状态函数 + 模块级状态字典（仅 `VaultEngine` 使用类）
- 存储格式：Markdown + YAML frontmatter
- 线程安全：`threading.Lock` 保护所有共享状态
- LLM 降级：所有 LLM 调用在 API 失败时自动切换到规则兜底
- 测试：`tmp_path` fixture + mock LLM 调用，19 个测试文件覆盖全部模块
- 语言：面向用户的洞察/报告/摘要使用中文

## 许可证

MIT
