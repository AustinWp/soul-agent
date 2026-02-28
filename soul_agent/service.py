"""Background FastAPI service for soul-agent.

Runs as a daemon on localhost:8330 with endpoints for notes, todos,
terminal command capture, search, and clipboard monitoring.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from rich.console import Console

if TYPE_CHECKING:
    from soul_agent.core.queue import IngestQueue

console = Console()

SERVICE_HOST = "127.0.0.1"
SERVICE_PORT = 8330
PID_DIR = Path.home() / ".soul-agent"
PID_FILE = PID_DIR / "daemon.pid"
DEFAULT_CONFIG = Path(__file__).parent.parent / "config" / "mem.json"
_ENV_FILE = Path(__file__).parent.parent / ".env"


def _load_dotenv() -> None:
    """Load .env file into os.environ if it exists."""
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


_load_dotenv()

# ── Terminal command buffer ────────────────────────────────────────────────

_cmd_buffer: deque[dict[str, Any]] = deque()
_CMD_FLUSH_COUNT = 20
_CMD_FLUSH_INTERVAL = 30 * 60  # 30 minutes in seconds
_last_flush_time: float = 0.0
_buffer_lock = threading.Lock()


def _flush_cmd_buffer(engine: Any, ingest_queue: IngestQueue | None = None) -> None:
    """Flush buffered terminal commands into memory."""
    global _last_flush_time
    with _buffer_lock:
        if not _cmd_buffer:
            return
        cmds = list(_cmd_buffer)
        _cmd_buffer.clear()
        _last_flush_time = time.time()

    lines = []
    for c in cmds:
        line = f"$ {c['command']} (exit={c.get('exit_code', '?')}, {c.get('duration', 0)}s)"
        lines.append(line)
    text = "Terminal commands:\n" + "\n".join(lines)

    if ingest_queue is not None:
        from datetime import datetime

        from soul_agent.core.queue import IngestItem

        ingest_queue.put(IngestItem(text=text, source="terminal", timestamp=datetime.now(), meta={}))
    else:
        try:
            engine.append_log(text, source="terminal")
        except Exception:
            pass


# ── Compaction scheduler ──────────────────────────────────────────────────

def _compaction_loop(engine: Any, stop_event: threading.Event) -> None:
    """Check daily if last week's report exists; generate if missing."""
    from datetime import date, timedelta

    # Initial check on startup
    try:
        from soul_agent.modules.compact import INSIGHTS_DIR, _week_label, compact_week

        today = date.today()
        last_week = today - timedelta(days=7)
        label = _week_label(last_week)
        rel_path = f"{INSIGHTS_DIR}/{label}.md"
        if not engine.read_resource(rel_path):
            compact_week(last_week, engine)
    except Exception:
        pass

    # Then check once per day
    while not stop_event.wait(timeout=86400):
        try:
            from soul_agent.modules.compact import INSIGHTS_DIR, _week_label, compact_week

            today = date.today()
            last_week = today - timedelta(days=7)
            label = _week_label(last_week)
            rel_path = f"{INSIGHTS_DIR}/{label}.md"
            if not engine.read_resource(rel_path):
                compact_week(last_week, engine)
        except Exception:
            pass


# ── FastAPI app ────────────────────────────────────────────────────────────

from fastapi import FastAPI, Query
from pydantic import BaseModel


class NoteRequest(BaseModel):
    text: str

class TodoAddRequest(BaseModel):
    text: str
    due: Optional[str] = None
    priority: str = "normal"

class TodoIdRequest(BaseModel):
    todo_id: str

class TerminalCmdRequest(BaseModel):
    command: str
    exit_code: int = 0
    duration: int = 0

class CompactRequest(BaseModel):
    scope: str = "week"

class DailyLogRequest(BaseModel):
    text: str
    source: str = "manual"

class CoreUpdateRequest(BaseModel):
    content: str

class ClaudeCodeRequest(BaseModel):
    text: str

class SoulInitRequest(BaseModel):
    preset: str

class SoulChatRequest(BaseModel):
    question: str


def create_app() -> Any:
    """Create and return the FastAPI application."""

    # Shared state
    state: dict[str, Any] = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Initialize engine, clipboard, insight on startup."""
        from soul_agent.core.vault import get_engine
        from soul_agent.core.queue import IngestQueue
        from soul_agent.modules.browser import start_browser_monitor
        from soul_agent.modules.clipboard import start_clipboard_monitor
        from soul_agent.modules.filewatcher import start_file_watcher
        from soul_agent.modules.insight import start_insight_thread
        from soul_agent.modules.pipeline import start_pipeline_thread

        engine = get_engine()
        engine.initialize(config_path=str(DEFAULT_CONFIG))
        state["engine"] = engine

        # Ingest queue and classification pipeline
        ingest_queue = IngestQueue(batch_size=10, flush_interval=60)
        state["ingest_queue"] = ingest_queue

        pipeline_thread, pipeline_stop = start_pipeline_thread(ingest_queue, engine)
        state["pipeline_thread"] = pipeline_thread
        state["pipeline_stop"] = pipeline_stop

        # Browser history monitor
        browser_thread, browser_stop = start_browser_monitor(ingest_queue)
        state["browser_thread"] = browser_thread
        state["browser_stop"] = browser_stop

        # File watcher
        file_observer, file_stop = start_file_watcher(ingest_queue)
        state["file_observer"] = file_observer
        state["file_stop"] = file_stop

        # Insight thread (daily insight at 20:00)
        insight_thread, insight_stop = start_insight_thread(engine)
        state["insight_thread"] = insight_thread
        state["insight_stop"] = insight_stop

        # Clipboard monitor (now with ingest queue)
        clip_thread, clip_running = start_clipboard_monitor(engine, ingest_queue=ingest_queue)
        state["clip_thread"] = clip_thread
        state["clip_running"] = clip_running

        # Compaction scheduler thread
        compact_stop = threading.Event()
        compact_thread = threading.Thread(
            target=_compaction_loop,
            args=(engine, compact_stop),
            daemon=True,
            name="compaction-scheduler",
        )
        compact_thread.start()
        state["compact_thread"] = compact_thread
        state["compact_stop"] = compact_stop

        global _last_flush_time
        _last_flush_time = time.time()

        yield

        # Shutdown all threads
        clip_running.clear()
        clip_thread.join(timeout=5)
        compact_stop.set()
        compact_thread.join(timeout=5)
        pipeline_stop.clear()
        pipeline_thread.join(timeout=5)
        browser_stop.clear()
        browser_thread.join(timeout=5)
        file_observer.stop()
        file_observer.join(timeout=5)
        insight_stop.clear()
        insight_thread.join(timeout=5)
        engine.close()

    app = FastAPI(title="soul-agent", lifespan=lifespan)

    # ── Endpoints ──────────────────────────────────────────────────────

    @app.post("/note")
    def post_note(req: NoteRequest):
        engine = state["engine"]
        engine.append_log(req.text, source="note")
        return {"status": "ok"}

    @app.post("/todo/add")
    def post_todo_add(req: TodoAddRequest):
        from soul_agent.modules.todo import add_todo
        todo_id = add_todo(req.text, due=req.due, priority=req.priority)
        return {"status": "ok", "todo_id": todo_id}

    @app.get("/todo/list")
    def get_todo_list():
        from soul_agent.modules.todo import list_todos
        todos = list_todos()
        return {"status": "ok", "todos": todos}

    @app.post("/todo/done")
    def post_todo_done(req: TodoIdRequest):
        from soul_agent.modules.todo import complete_todo
        success = complete_todo(req.todo_id)
        return {"status": "ok", "success": success}

    @app.post("/todo/rm")
    def post_todo_rm(req: TodoIdRequest):
        from soul_agent.modules.todo import remove_todo
        success = remove_todo(req.todo_id)
        return {"status": "ok", "success": success}

    @app.post("/terminal/cmd")
    def post_terminal_cmd(req: TerminalCmdRequest):
        with _buffer_lock:
            _cmd_buffer.append({
                "command": req.command,
                "exit_code": req.exit_code,
                "duration": req.duration,
            })
            should_flush = len(_cmd_buffer) >= _CMD_FLUSH_COUNT
        if not should_flush:
            elapsed = time.time() - _last_flush_time
            should_flush = elapsed >= _CMD_FLUSH_INTERVAL and len(_cmd_buffer) > 0
        if should_flush:
            _flush_cmd_buffer(state["engine"], ingest_queue=state.get("ingest_queue"))
        return {"status": "ok", "buffered": len(_cmd_buffer)}

    @app.get("/search")
    def get_search(q: str = Query(...), limit: int = Query(10)):
        engine = state["engine"]
        results = engine.search(query=q, limit=limit)
        return {"results": results}

    @app.get("/clipboard/status")
    def get_clipboard_status():
        from soul_agent.modules.clipboard import clip_stats
        return {
            "active": clip_stats["active"],
            "clips_captured": clip_stats["count"],
        }

    @app.get("/health")
    def get_health():
        return {"status": "ok", "service": "soul-agent"}

    # ── Phase 3 endpoints ─────────────────────────────────────────────

    @app.post("/compact")
    def post_compact(req: CompactRequest):
        from datetime import date

        from soul_agent.modules.compact import compact_month, compact_week

        engine = state["engine"]
        today = date.today()
        if req.scope == "month":
            report = compact_month(today, engine)
        else:
            report = compact_week(today, engine)
        return {"status": "ok", "report": report, "report_length": len(report)}

    @app.post("/daily-log")
    def post_daily_log(req: DailyLogRequest):
        from soul_agent.modules.daily_log import append_daily_log

        engine = state["engine"]
        append_daily_log(req.text, req.source, engine)
        return {"status": "ok"}

    @app.get("/recall")
    def get_recall(scope: str = Query("today")):
        if scope == "week":
            from soul_agent.modules.recall import recall_week
            data = recall_week()
        else:
            from soul_agent.modules.recall import recall_today
            data = recall_today()
        return {"status": "ok", "data": data}

    @app.get("/core")
    def get_core():
        engine = state["engine"]
        content = engine.read_resource("core/MEMORY.md")
        return {"status": "ok", "content": content or ""}

    @app.post("/core")
    def post_core(req: CoreUpdateRequest):
        engine = state["engine"]
        engine.write_resource(
            content=req.content,
            directory="core",
            filename="MEMORY.md",
        )
        return {"status": "ok"}

    @app.get("/todo/stalled")
    def get_todo_stalled():
        from soul_agent.modules.todo import get_stalled_todos

        engine = state["engine"]
        stalled = get_stalled_todos(engine)
        return {"status": "ok", "stalled": stalled}

    # ── Phase 5 endpoints ─────────────────────────────────────────────

    @app.post("/ingest/claudecode")
    async def ingest_claudecode(req: ClaudeCodeRequest):
        from datetime import datetime

        from soul_agent.core.queue import IngestItem

        state["ingest_queue"].put(
            IngestItem(text=req.text, source="claude-code", timestamp=datetime.now(), meta={})
        )
        return {"status": "queued"}

    @app.get("/insight")
    async def get_insight(date: str = "today"):
        from datetime import date as _date

        from soul_agent.modules.insight import build_daily_insight

        engine = state["engine"]
        target = _date.today() if date == "today" else _date.fromisoformat(date)
        report = build_daily_insight(target, engine)
        return {"date": target.isoformat(), "report": report}

    @app.get("/categories")
    async def get_categories(period: str = "today"):
        from datetime import date as _date

        from soul_agent.modules.daily_log import get_daily_log
        from soul_agent.modules.insight import compute_time_allocation, parse_daily_log_entries

        engine = state["engine"]
        log = get_daily_log(_date.today(), engine)
        if not log:
            return {"categories": {}}
        entries = parse_daily_log_entries(log)
        alloc = compute_time_allocation(entries)
        return {"categories": alloc}

    @app.get("/suggest")
    async def get_suggest(focus: str = ""):
        from datetime import date as _date

        from soul_agent.modules.insight import build_daily_insight

        engine = state["engine"]
        report = build_daily_insight(_date.today(), engine)
        return {"suggestions": report}

    @app.get("/todo/progress/{todo_id}")
    async def get_todo_progress(todo_id: str):
        from soul_agent.core.frontmatter import parse_activity_log, parse_frontmatter
        from soul_agent.modules.todo import ACTIVE_DIR

        engine = state["engine"]
        for filename in engine.list_resources(ACTIVE_DIR):
            content = engine.read_resource(f"{ACTIVE_DIR}/{filename}")
            if content:
                fields, body = parse_frontmatter(content)
                if fields.get("id", "")[:8] == todo_id[:8]:
                    activity = parse_activity_log(fields.get("activity_log", ""))
                    return {"id": todo_id, "text": body.strip(), "activity": activity}
        return {"error": "not found"}

    @app.get("/input-hook/status")
    async def input_hook_status():
        from soul_agent.modules.input_hook import hook_status

        return hook_status()

    @app.get("/memories")
    async def get_memories(importance: int = Query(0)):
        from soul_agent.modules.memory import list_all_memories

        engine = state["engine"]
        memories = list_all_memories(engine)
        if importance > 0:
            memories = [m for m in memories if m.get("importance", 0) >= importance]
        return {"status": "ok", "memories": memories}

    @app.get("/memories/search")
    async def search_memories(q: str = Query(...), limit: int = Query(10)):
        from soul_agent.modules.memory import search_memories_by_query

        engine = state["engine"]
        results = search_memories_by_query(q, engine, limit=limit)
        return {"status": "ok", "results": results}

    @app.post("/input-hook/start")
    async def input_hook_start():
        from soul_agent.modules.input_hook import hook_status, start_input_hook

        status = hook_status()
        if status.get("active"):
            return {"status": "already_running"}
        ingest_queue = state.get("ingest_queue")
        if ingest_queue is None:
            return {"status": "error", "message": "ingest queue not available"}
        thread, running = start_input_hook(ingest_queue)
        state["input_hook_thread"] = thread
        state["input_hook_running"] = running
        return {"status": "started"}

    @app.post("/input-hook/stop")
    async def input_hook_stop():
        from soul_agent.modules.input_hook import stop_input_hook

        stop_input_hook()
        return {"status": "stopped"}

    # ── Soul endpoints ───────────────────────────────────────────────

    @app.get("/soul")
    async def get_soul():
        from soul_agent.modules.soul import load_soul

        engine = state["engine"]
        content = load_soul(engine)
        return {"status": "ok", "content": content or ""}

    @app.post("/soul/init")
    async def post_soul_init(req: SoulInitRequest):
        from soul_agent.modules.soul import init_soul

        engine = state["engine"]
        init_soul(req.preset, engine)
        return {"status": "ok"}

    @app.post("/soul/chat")
    async def post_soul_chat(req: SoulChatRequest):
        from soul_agent.modules.soul import chat_with_soul

        engine = state["engine"]
        answer = chat_with_soul(req.question, engine)
        return {"status": "ok", "answer": answer}

    @app.post("/soul/evolve")
    async def post_soul_evolve():
        from datetime import date as _date

        from soul_agent.modules.memory import load_high_importance_memories
        from soul_agent.modules.soul import evolve_soul, load_soul

        engine = state["engine"]
        if not load_soul(engine):
            return {"status": "ok", "evolved": False, "reason": "no soul"}

        memories = load_high_importance_memories(engine, min_importance=3, limit=10)

        from soul_agent.modules.insight import INSIGHTS_DIR

        today = _date.today()
        report = engine.read_resource(f"{INSIGHTS_DIR}/daily-{today.isoformat()}.md") or ""
        evolved = evolve_soul(memories, report, engine)
        return {"status": "ok", "evolved": evolved}

    return app


# ── Process management ─────────────────────────────────────────────────────

def _read_pid() -> Optional[int]:
    """Read PID from file, return None if missing or stale."""
    if not PID_FILE.exists():
        return None
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)  # Check if process exists
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        PID_FILE.unlink(missing_ok=True)
        return None


def start_service() -> None:
    """Start the background FastAPI service as a subprocess."""
    pid = _read_pid()
    if pid is not None:
        console.print(f"[yellow]Service already running (PID {pid})[/yellow]")
        return

    PID_DIR.mkdir(parents=True, exist_ok=True)

    log_file = PID_DIR / "service.log"
    log_fd = open(log_file, "a")  # noqa: SIM115
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "soul_agent.service:app",
            "--host", SERVICE_HOST,
            "--port", str(SERVICE_PORT),
            "--log-level", "warning",
        ],
        stdout=log_fd,
        stderr=log_fd,
    )

    PID_FILE.write_text(str(proc.pid))
    console.print(f"[green]Service started[/green] (PID {proc.pid}) on {SERVICE_HOST}:{SERVICE_PORT}")


def stop_service() -> None:
    """Stop the background service."""
    pid = _read_pid()
    if pid is None:
        console.print("[dim]Service is not running.[/dim]")
        return

    try:
        os.kill(pid, signal.SIGTERM)
        console.print(f"[green]Service stopped[/green] (PID {pid})")
    except ProcessLookupError:
        console.print("[dim]Service process already gone.[/dim]")
    finally:
        PID_FILE.unlink(missing_ok=True)


def service_status() -> None:
    """Show service status."""
    pid = _read_pid()
    if pid is not None:
        console.print(f"[green]Service: running[/green] (PID {pid}) on {SERVICE_HOST}:{SERVICE_PORT}")
    else:
        console.print("[dim]Service: not running[/dim]")


# Module-level app for uvicorn to import
app = create_app()
