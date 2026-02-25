# Phase 4 设计文档：全量输入 + 智能分类 + 洞察引擎 + MCP Server

**日期**：2026-02-25
**状态**：已确认

---

## 1. 目标

将 mem-agent 从"记忆系统"升级为"AI 工作助手"：

1. 全量输入采集 — 浏览器历史、文件变更、Claude Code 对话、输入法全局 Hook
2. LLM 自动分类 — 每条输入自动分类 + 打标签 + 识别待办意图
3. 多维度洞察 — 日报、时间分配、模式识别、任务追踪、工作建议
4. MCP Server — 让 Claude 直接访问记忆和洞察
5. CLI 查看 — 人可通过 CLI 命令查看洞察报告

---

## 2. 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                     Source Adapters                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────┐  │
│  │ Browser  │ │ FileWatch│ │ ClaudeCC │ │ InputMethod   │  │
│  │ History  │ │ (watchdog│ │ (hooks)  │ │ (CGEvent tap) │  │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └──────┬────────┘  │
│  ┌────┴─────┐ ┌─────┴────┐                      │           │
│  │Clipboard │ │Terminal  │                      │           │
│  │(existing)│ │(existing)│                      │           │
│  └────┬─────┘ └────┬─────┘                      │           │
└───────┼─────────────┼──────────────────────────── ┼──────────┘
        v             v                            v
┌─────────────────────────────────────────────────────────────┐
│                   Ingest Queue (内存队列)                     │
│   批量触发: 10 条 OR 60 秒超时                                │
│   去重: 60 秒内相似内容合并                                    │
└──────────────────────────┬──────────────────────────────────┘
                           v
┌─────────────────────────────────────────────────────────────┐
│                   LLM Classifier (DeepSeek)                  │
│   输出: category, tags[], importance, summary                │
│         action_type, action_detail (待办识别)                 │
│   Fallback: 规则分类 (LLM 不可用时)                           │
└──────────────────────────┬──────────────────────────────────┘
                           v
┌─────────────────────────────────────────────────────────────┐
│                   Tagged Storage                             │
│   L2 daily log (frontmatter + category/tags)                │
│   OpenViking session (双写保持)                               │
│   分类索引 (viking://resources/classified/)                   │
└──────────────────────────┬──────────────────────────────────┘
                           v
┌─────────────────────────────────────────────────────────────┐
│                   Insight Engine                              │
│   DailyInsight | PatternTracker | TaskTracker | WorkAdvisor  │
└──────────────────────────┬──────────────────────────────────┘
                           v
┌──────────────────────────┴──────────────────────────────────┐
│             MCP Server          CLI (mem insight)            │
│         (Claude 调用)          (人查看)                       │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Source Adapters（输入源适配器）

### 3.1 浏览器历史 — `modules/browser.py`

- 定时读取 Chrome/Safari 本地 SQLite 数据库（每 5 分钟）
- Chrome: `~/Library/Application Support/Google/Chrome/Default/History`
- Safari: `~/Library/Safari/History.db`
- 只拉增量（记录 `last_visit_time`）
- 提取: URL、页面标题、访问时间
- 过滤: 忽略 `chrome://`、`about:`，5 分钟内同 URL 去重
- 写入 Ingest Queue，source = `browser`

### 3.2 文件变更 — `modules/filewatcher.py`

- 使用 `watchdog` 库监听指定目录（默认: `~/Desktop`、`~/Documents`、`~/Downloads`，可配置）
- 监听: 文件创建、修改（忽略删除和临时文件）
- 过滤: `.git/`、`node_modules/`、`.DS_Store`、二进制文件
- 文本文件提取文件名 + 前 500 字符
- 写入 Ingest Queue，source = `file`，meta 含文件路径

### 3.3 Claude Code 对话 — `modules/claude_code.py`

- 利用 Claude Code hooks 机制
- 提供 `mem claudecode install` 安装命令，写入 `~/.claude/settings.json`
- Hook 在对话结束（Stop event）时 POST 摘要到 `http://127.0.0.1:8330/ingest/claudecode`
- 写入 Ingest Queue，source = `claude-code`

### 3.4 输入法全局 Hook — `modules/input_hook.py`

- 使用 macOS `CGEventTap`（通过 `pyobjc` 的 `Quartz` 模块）
- **默认关闭**，通过 `mem input-hook start/stop` 控制，配置项 `input_hook.enabled`
- 缓冲区: 连续输入累积，停顿 5 秒视为一段结束
- 最短 10 字符才记录
- **隐私保护**: 检测到密码输入框（`isSecureTextField`）时暂停采集
- **应用感知过滤**: 终端类应用（Terminal、iTerm2 — 已有 terminal adapter）和 Claude Code 激活时自动静默，避免与专属适配器重复
- 需要 macOS 辅助功能权限，首次启动引导授权
- 写入 Ingest Queue，source = `input-method`

### 3.5 现有输入源改造

- `clipboard.py` → 改为写入 Ingest Queue（不再直接 `ingest_text` + `append_daily_log`）
- `terminal.py` → 命令 flush 时写入 Ingest Queue
- `note.py` → 写入 Ingest Queue

所有输入源统一走 Ingest Queue → Classifier → Storage 流水线。

---

## 4. Ingest Queue + LLM Classifier

### 4.1 数据模型 — `core/queue.py`

```python
@dataclass
class IngestItem:
    text: str                    # 原始内容
    source: str                  # "note"|"clipboard"|"terminal"|"browser"|"file"|"claude-code"|"input-method"
    timestamp: datetime
    meta: dict                   # 源特有元数据 (URL, file_path, app_name, command, etc.)

@dataclass
class ClassifiedItem(IngestItem):
    category: str                # 一级分类
    tags: list[str]              # 多标签
    importance: int              # 1-5 重要度
    summary: str                 # 一句话摘要
    action_type: str | None      # "new_task"|"task_progress"|"task_done"|None
    action_detail: str | None    # 待办内容描述
    related_todo_id: str | None  # 匹配的已有 Todo ID
```

### 4.2 队列行为

- 线程安全 `queue.Queue`
- 后台 Classifier 线程消费
- 批量触发: 积攒 10 条 OR 60 秒超时
- 入队去重: 60 秒内 text hash + 长度粗筛

### 4.3 分类体系

| 一级分类 | 说明 |
|---------|------|
| `coding` | 编程开发 |
| `work` | 工作事务 |
| `learning` | 学习研究 |
| `communication` | 沟通交流 |
| `browsing` | 浏览消费 |
| `life` | 日常生活 |

二级标签（tags）由 LLM 自由生成，不固定。

### 4.4 分类 Prompt

```
你是一个个人输入分类器。对以下批量输入逐条分类。

每条返回:
- category: coding|work|learning|communication|browsing|life
- tags: 2-5个关键标签
- importance: 1-5 (5=非常重要)
- summary: 一句话摘要（<30字）
- action_type: 是否包含待办意图？
  - "new_task": 用户提到了要做某事但还没做
  - "task_progress": 用户在推进某个已有任务
  - "task_done": 用户完成了某事
  - null: 无待办相关
- action_detail: 如果有 action_type，描述具体待办内容

当前活跃待办列表（用于匹配 task_progress/task_done）:
{active_todos_json}

输入列表:
[{source}, {timestamp}] {text}
...

以 JSON 数组返回。
```

### 4.5 Fallback 规则（LLM 不可用时）

- source=terminal → coding
- source=browser → browsing
- source=claude-code → coding
- 其他 → work, importance=3

### 4.6 待办联动

- `action_type == "new_task"` → 自动创建 Todo（可配置关闭）
- `action_type == "task_progress"` → 在 Todo 追加活动记录，日报体现进展
- `action_type == "task_done"` → 提示确认标记 Todo 完成

### 4.7 分类后写入

```
ClassifiedItem
  ├→ append_daily_log()        — L2 日志 + category/tags/importance
  ├→ ingest_text()             — OpenViking session（语义记忆）
  ├→ update_category_index()   — 分类索引
  └→ update_todo_activity()    — 如有 action_type，更新 Todo
```

---

## 5. Insight Engine（洞察引擎）

### 5.1 模块结构 — `modules/insight.py`

```
Insight Engine
├── DailyInsight     — 每日洞察（每天 20:00 + 手动触发）
├── PatternTracker   — 模式追踪（7/30 天滑动窗口）
├── TaskTracker      — 任务完成追踪
└── WorkAdvisor      — 工作建议（LLM 生成）
```

### 5.2 DailyInsight

触发: 守护进程定时线程每天 20:00，存储到 `viking://resources/insights/daily-YYYY-MM-DD.md`

报告包含:
- **时间分配** — 按 category 统计小时数和百分比
- **任务追踪** — 已完成 / 进行中 / 新识别待办 / 停滞预警
- **核心话题** — 今日 Top 3 话题
- **关联发现** — 跨输入源的关联内容
- **工作建议** — AI 生成的 3-5 条建议

### 5.3 TaskTracker

数据来源: Todo 系统 + Classifier 的 action_type

追踪维度:
- 任务创建（时间、来源、手动/自动识别）
- 任务活动（每日活动次数、来源）
- 任务完成（完成时间、总耗时估算）
- 任务停滞（超 N 天无活动）

Todo frontmatter 增加字段:
```yaml
activity_log:
  - {date: "2026-02-22", count: 3, sources: ["note", "claude-code"]}
last_activity: 2026-02-25
auto_detected: false
```

### 5.4 PatternTracker

| 模式 | 检测方法 | 输出示例 |
|------|---------|---------|
| 时间分配趋势 | 按 category 日统计，周环比 | "本周 coding +30%" |
| 高频话题 | tags 频率 Top 10 | "近 7 天最关注: mem-agent, Python" |
| 注意力碎片化 | category 切换频率 | "平均每 20 分钟切换话题" |
| 未完成循环 | 重复出现但未关联完成事件的话题 | "你反复提到 X 但未推进" |
| 工作节奏 | 按小时统计输入密度 | "10-12 点和 14-16 点最高产" |

### 5.5 WorkAdvisor

基于 DailyInsight + PatternTracker + TaskTracker + P0 永久记忆，调用 LLM 生成:
- 3-5 条具体可执行的建议
- 基于数据（引用具体数据点）
- 包含效率提升和工作创新建议
- 考虑用户个人偏好和长期目标

---

## 6. MCP Server

### 6.1 架构 — `mcp_server.py`

- 独立进程，stdio transport
- 内部通过 HTTP 调用守护进程 (127.0.0.1:8330)
- 注册到 `~/.claude/settings.json`

### 6.2 Tools

| Tool | 参数 | 说明 |
|------|------|------|
| `mem_search` | `query, limit` | 语义搜索记忆 |
| `mem_recall` | `period` | 时间段回顾 |
| `mem_insight` | `date` | 获取洞察报告 |
| `mem_categories` | `period, category?` | 分类统计 |
| `mem_todos` | `status` | 待办列表及完成情况 |
| `mem_suggest` | `focus?` | AI 工作建议 |
| `mem_note` | `text, tags?` | 手动添加记忆 |
| `mem_task_progress` | `todo_id` | 任务活动时间线 |

### 6.3 Resources

| URI | 说明 |
|-----|------|
| `mem://insight/today` | 今日洞察 |
| `mem://insight/week` | 本周洞察 |
| `mem://todos/active` | 活跃待办 |
| `mem://todos/stalled` | 停滞任务 |
| `mem://core/memory` | 永久记忆 |
| `mem://stats/categories` | 分类统计 |

---

## 7. CLI 扩展

新增 `mem insight` 子命令组:

```bash
mem insight today          # 今日洞察（Rich 渲染）
mem insight week           # 本周洞察
mem insight tasks          # 任务追踪总览
mem insight focus <cat>    # 某分类详细时间线
mem insight suggest        # 工作建议
```

新增 `mem input-hook` 子命令:

```bash
mem input-hook start       # 启动输入法 Hook
mem input-hook stop        # 停止
mem input-hook status      # 状态
```

新增 `mem claudecode` 子命令:

```bash
mem claudecode install     # 安装 Claude Code hooks
mem claudecode uninstall   # 卸载
```

---

## 8. 新增文件清单

| 文件 | 说明 |
|------|------|
| `core/queue.py` | Ingest Queue + IngestItem/ClassifiedItem |
| `modules/classifier.py` | LLM 批量分类器 + 待办识别 + fallback |
| `modules/browser.py` | 浏览器历史采集 |
| `modules/filewatcher.py` | 文件变更监听 |
| `modules/claude_code.py` | Claude Code 对话捕获 |
| `modules/input_hook.py` | 输入法全局 Hook |
| `modules/insight.py` | 洞察引擎 (Daily+Pattern+Task+Advisor) |
| `mcp_server.py` | MCP Server |

## 9. 修改文件清单

| 文件 | 改动 |
|------|------|
| `core/frontmatter.py` | 增加 category/tags/importance/activity_log |
| `modules/note.py` | 改为写入 Ingest Queue |
| `modules/clipboard.py` | 改为写入 Ingest Queue |
| `modules/terminal.py` | 改为写入 Ingest Queue |
| `modules/todo.py` | 增加 activity_log 追踪 |
| `modules/daily_log.py` | 支持带分类标签的日志条目 |
| `service.py` | 新增线程 + API 端点 |
| `cli.py` | 新增子命令组 |
| `pyproject.toml` | 新增依赖 |

## 10. 新增依赖

| 包 | 用途 |
|---|------|
| `watchdog` | 文件变更监听 |
| `pyobjc-framework-Quartz` | CGEventTap |
| `pyobjc-framework-Cocoa` | NSWorkspace |
| `mcp` | MCP SDK |

## 11. 不在 Phase 4 范围

- Web Dashboard
- macOS 通知推送
- 多设备同步
- 知识图谱可视化
