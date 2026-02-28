"""Classification pipeline: connects IngestQueue -> Classifier -> Storage."""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from ..core.queue import ClassifiedItem, IngestItem, IngestQueue
from .classifier import classify_batch
from .daily_log import append_daily_log
from .todo import add_todo, update_todo_activity

if TYPE_CHECKING:
    from ..core.vault import VaultEngine


def _get_active_todos(engine: VaultEngine) -> list[dict[str, Any]]:
    from ..core.frontmatter import parse_frontmatter
    todos = []
    try:
        for filename in engine.list_resources("todos/active"):
            rel_path = f"todos/active/{filename}"
            content = engine.read_resource(rel_path)
            if content:
                fields, body = parse_frontmatter(content)
                todos.append({"id": fields.get("id", ""), "text": body.strip()})
    except Exception:
        pass
    return todos


def process_batch(items: list[IngestItem], engine: VaultEngine) -> list[ClassifiedItem]:
    active_todos = _get_active_todos(engine)
    classified = classify_batch(items, active_todos, engine.config)
    for ci in classified:
        try:
            append_daily_log(ci.text, ci.source, engine, category=ci.category, tags=ci.tags, importance=ci.importance)
        except Exception:
            pass
        if ci.action_type == "new_task" and ci.action_detail:
            try:
                add_todo(ci.action_detail)
            except Exception:
                pass
        if ci.action_type == "task_progress" and ci.related_todo_id:
            try:
                update_todo_activity(ci.related_todo_id, ci.source, engine)
            except Exception:
                pass
    return classified


def _pipeline_loop(queue: IngestQueue, engine: VaultEngine, running: threading.Event) -> None:
    while running.is_set():
        batch = queue.get_batch(timeout=2)
        if batch:
            try:
                process_batch(batch, engine)
            except Exception:
                pass


def start_pipeline_thread(queue: IngestQueue, engine: VaultEngine) -> tuple[threading.Thread, threading.Event]:
    running = threading.Event()
    running.set()
    thread = threading.Thread(target=_pipeline_loop, args=(queue, engine, running), daemon=True, name="pipeline")
    thread.start()
    return thread, running
