# Soul Agent

> 你的数字灵魂 — 捕获、分类、反思每日活动，给出洞察与建议。

Soul Agent 作为后台守护进程运行，持续从剪贴板、浏览器、文件系统、键盘输入和终端命令五个来源采集信号。通过 LLM 对每条输入进行分类，将结构化日志写入 Obsidian vault，并生成每日洞察和行动建议。

## 架构

```
输入源 (5路)              分类引擎              存储 (Obsidian Vault)
─────────────            ────────              ──────────────────
Clipboard ──┐                                  logs/YYYY-MM-DD.md
Browser ────┤            DeepSeek LLM          todos/active/*.md
FileWatch ──┼─→ IngestQueue ─→ Pipeline ─→     todos/done/*.md
Keystroke ──┤   (batch+dedup)  (classify)      insights/*.md
Terminal ───┘                                  core/MEMORY.md
```

- **后台服务**: FastAPI 守护进程，监听 `localhost:8330`
- **CLI**: `soul` 命令 (基于 Typer)
- **MCP Server**: 为 LLM 提供 tool/resource 接口
- **LLM**: DeepSeek Chat API (OpenAI 兼容)
- **存储**: Obsidian vault，Markdown + YAML frontmatter

## 核心功能

- **5 路输入采集** — 剪贴板轮询、浏览器历史、文件监控、键盘捕获、终端命令
- **LLM 自动分类** — 将每条事件归类为 `coding` / `work` / `learning` / `communication` / `browsing` / `life`
- **每日洞察** — 两阶段报告：语义理解 + 深度建议
- **待办管理** — 优先级排序 + 停滞检测
- **记忆检索** — 跨全部数据的语义搜索
- **周报/月报聚合** — 自动压缩历史日志为摘要

## 快速开始

```bash
# 安装
pip install -e .

# 启动守护进程
soul service start

# 查看状态
soul service status

# 记一条笔记
soul note "完成了 API 重构"

# 查看今日回顾
soul recall today

# 生成每日洞察
soul insight
```

## 开发

```bash
# 开发模式安装
pip install -e .

# 运行全部测试
python -m pytest tests/ -v

# 运行单个测试文件
python -m pytest tests/test_pipeline.py -v
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

## 许可证

MIT
