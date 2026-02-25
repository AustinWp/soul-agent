"""Background FastAPI service for mem-agent.

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
from typing import TYPE_CHECKING, Any

from rich.console import Console

if TYPE_CHECKING:
    from mem_agent.core.queue import IngestQueue

console = Console()

SERVICE_HOST = "127.0.0.1"
SERVICE_PORT = 8330
PID_DIR = Path.home() / ".mem-agent"
PID_FILE = PID_DIR / "daemon.pid"
DEFAULT_CONFIG = Path(__file__).parent.parent / "config" / "ov.conf"
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
    """Flush buffered terminal commands into memory.

    When *ingest_queue* is provided, the combined text is placed on the queue
    for classification instead of being ingested directly.
    """
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

        from mem_agent.core.queue import IngestItem

        ingest_queue.put(IngestItem(text=text, source="terminal", timestamp=datetime.now(), meta={}))
    else:
        try:
            engine.ingest_text(text, source="terminal")
        except Exception:
            pass

        # Dual-write: also append to daily log
        try:
            from mem_agent.modules.daily_log import append_daily_log

            append_daily_log(text, "terminal", engine)
        except Exception:
            pass


# ── Compaction scheduler ──────────────────────────────────────────────────

def _compaction_loop(engine: Any, stop_event: threading.Event) -> None:
    """Check daily if last week's report exists; generate if missing."""
    from datetime import date, timedelta

    # Initial check on startup
    try:
        from mem_agent.modules.compact import INSIGHTS_DIR, _week_label, compact_week

        today = date.today()
        last_week = today - timedelta(days=7)
        label = _week_label(last_week)
        uri = f"{INSIGHTS_DIR}{label}.md"
        if not engine.read_resource(uri):
            compact_week(last_week, engine)
    except Exception:
        pass

    # Then check once per day
    while not stop_event.wait(timeout=86400):
        try:
            from mem_agent.modules.compact import INSIGHTS_DIR, _week_label, compact_week

            today = date.today()
            last_week = today - timedelta(days=7)
            label = _week_label(last_week)
            uri = f"{INSIGHTS_DIR}{label}.md"
            if not engine.read_resource(uri):
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
    due: str | None = None
    priority: str = "normal"

class TodoIdRequest(BaseModel):
    todo_id: str

class TerminalCmdRequest(BaseModel):
    command: str
    exit_code: int = 0
    duration: int = 0

class CompactRequest(BaseModel):
    scope: str = "week"

class LifecycleTagRequest(BaseModel):
    uri: str
    priority: str = "P1"
    ttl_days: int | None = None

class DailyLogRequest(BaseModel):
    text: str
    source: str = "manual"

class ClaudeCodeRequest(BaseModel):
    text: str


def create_app() -> Any:
    """Create and return the FastAPI application."""

    # Shared state
    state: dict[str, Any] = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Initialize engine, clipboard, janitor, abstract refresher on startup."""
        from mem_agent.core.engine import get_engine
        from mem_agent.core.queue import IngestQueue
        from mem_agent.modules.abstract import AbstractRefresher
        from mem_agent.modules.browser import start_browser_monitor
        from mem_agent.modules.clipboard import start_clipboard_monitor
        from mem_agent.modules.filewatcher import start_file_watcher
        from mem_agent.modules.insight import start_insight_thread
        from mem_agent.modules.janitor import start_janitor_thread
        from mem_agent.modules.pipeline import start_pipeline_thread

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

        # Janitor thread (hourly cleanup)
        janitor_thread, janitor_stop = start_janitor_thread(engine)
        state["janitor_thread"] = janitor_thread
        state["janitor_stop"] = janitor_stop

        # Abstract refresher (debounced directory index updates)
        refresher = AbstractRefresher(engine)
        refresher.start()
        state["abstract_refresher"] = refresher

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
        janitor_stop.set()
        janitor_thread.join(timeout=5)
        refresher.stop()
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

    app = FastAPI(title="mem-agent", lifespan=lifespan)

    # ── Endpoints ──────────────────────────────────────────────────────

    @app.post("/note")
    def post_note(req: NoteRequest):
        engine = state["engine"]
        engine.ingest_text(req.text, source="note")
        return {"status": "ok"}

    @app.post("/todo/add")
    def post_todo_add(req: TodoAddRequest):
        from mem_agent.modules.todo import add_todo
        add_todo(req.text, due=req.due, priority=req.priority)
        return {"status": "ok"}

    @app.get("/todo/list")
    def get_todo_list():
        from mem_agent.modules.todo import list_todos
        list_todos()
        return {"status": "ok"}

    @app.post("/todo/done")
    def post_todo_done(req: TodoIdRequest):
        from mem_agent.modules.todo import complete_todo
        complete_todo(req.todo_id)
        return {"status": "ok"}

    @app.post("/todo/rm")
    def post_todo_rm(req: TodoIdRequest):
        from mem_agent.modules.todo import remove_todo
        remove_todo(req.todo_id)
        return {"status": "ok"}

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
        items = []
        if hasattr(results, "resources") and results.resources:
            for ctx in results.resources:
                items.append({
                    "type": "resource",
                    "uri": getattr(ctx, "uri", ""),
                    "score": getattr(ctx, "score", 0),
                    "abstract": getattr(ctx, "abstract", ""),
                })
        if hasattr(results, "memories") and results.memories:
            for ctx in results.memories:
                items.append({
                    "type": "memory",
                    "uri": getattr(ctx, "uri", ""),
                    "score": getattr(ctx, "score", 0),
                    "abstract": getattr(ctx, "abstract", ""),
                })
        return {"results": items}

    @app.get("/clipboard/status")
    def get_clipboard_status():
        from mem_agent.modules.clipboard import clip_stats
        return {
            "active": clip_stats["active"],
            "clips_captured": clip_stats["count"],
        }

    @app.get("/health")
    def get_health():
        return {"status": "ok", "service": "mem-agent"}

    # ── Phase 3 endpoints ─────────────────────────────────────────────

    @app.post("/compact")
    def post_compact(req: CompactRequest):
        from datetime import date

        from mem_agent.modules.compact import compact_month, compact_week

        engine = state["engine"]
        today = date.today()
        if req.scope == "month":
            report = compact_month(today, engine)
        else:
            report = compact_week(today, engine)
        return {"status": "ok", "report_length": len(report)}

    @app.get("/abstract/{path:path}")
    def get_abstract(path: str):
        from mem_agent.modules.abstract import read_abstract

        engine = state["engine"]
        directory_uri = f"viking://resources/{path}/"
        abstract = read_abstract(directory_uri, engine)
        if abstract is None:
            return {"status": "not_found", "abstract": None}
        return {"status": "ok", "abstract": abstract}

    @app.post("/lifecycle/tag")
    def post_lifecycle_tag(req: LifecycleTagRequest):
        from mem_agent.modules.lifecycle import tag_resource

        engine = state["engine"]
        ok = tag_resource(req.uri, req.priority, req.ttl_days, engine)
        return {"status": "ok" if ok else "error"}

    @app.get("/janitor/status")
    def get_janitor_status():
        from mem_agent.modules.janitor import janitor_stats

        return {
            "last_run": janitor_stats["last_run"],
            "last_archived": janitor_stats["last_archived"],
            "total_archived": janitor_stats["total_archived"],
            "running": janitor_stats["running"],
        }

    @app.post("/daily-log")
    def post_daily_log(req: DailyLogRequest):
        from mem_agent.modules.daily_log import append_daily_log

        engine = state["engine"]
        append_daily_log(req.text, req.source, engine)
        return {"status": "ok"}

    # ── Phase 5 endpoints ─────────────────────────────────────────────

    @app.post("/ingest/claudecode")
    async def ingest_claudecode(req: ClaudeCodeRequest):
        from datetime import datetime

        from mem_agent.core.queue import IngestItem

        state["ingest_queue"].put(
            IngestItem(text=req.text, source="claude-code", timestamp=datetime.now(), meta={})
        )
        return {"status": "queued"}

    @app.get("/insight")
    async def get_insight(date: str = "today"):
        from datetime import date as _date

        from mem_agent.modules.insight import build_daily_insight

        engine = state["engine"]
        target = _date.today() if date == "today" else _date.fromisoformat(date)
        report = build_daily_insight(target, engine)
        return {"date": target.isoformat(), "report": report}

    @app.get("/categories")
    async def get_categories(period: str = "today"):
        from datetime import date as _date

        from mem_agent.modules.daily_log import get_daily_log
        from mem_agent.modules.insight import compute_time_allocation, parse_daily_log_entries

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

        from mem_agent.modules.insight import build_daily_insight

        engine = state["engine"]
        report = build_daily_insight(_date.today(), engine)
        return {"suggestions": report}

    @app.get("/todo/progress/{todo_id}")
    async def get_todo_progress(todo_id: str):
        from mem_agent.core.frontmatter import parse_activity_log, parse_frontmatter
        from mem_agent.modules.todo import ACTIVE_DIR

        engine = state["engine"]
        for filename in engine.list_resources(ACTIVE_DIR):
            content = engine.read_resource(f"{ACTIVE_DIR}{filename}")
            if content:
                fields, body = parse_frontmatter(content)
                if fields.get("id", "")[:8] == todo_id[:8]:
                    activity = parse_activity_log(fields.get("activity_log", ""))
                    return {"id": todo_id, "text": body.strip(), "activity": activity}
        return {"error": "not found"}

    @app.get("/input-hook/status")
    async def input_hook_status():
        from mem_agent.modules.input_hook import hook_status

        return hook_status()

    @app.post("/input-hook/stop")
    async def input_hook_stop():
        from mem_agent.modules.input_hook import stop_input_hook

        stop_input_hook()
        return {"status": "stopped"}

    return app


# ── Process management ─────────────────────────────────────────────────────

def _read_pid() -> int | None:
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

    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "mem_agent.service:app",
            "--host", SERVICE_HOST,
            "--port", str(SERVICE_PORT),
            "--log-level", "warning",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
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
