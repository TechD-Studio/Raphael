"""파일 시스템 훅 — watchdog으로 파일 변경 감지 후 에이전트 자동 호출.

설정 (settings.yaml 또는 settings.local.yaml):

  hooks:
    watches:
      - path: ~/projects/myrepo
        patterns: ["*.py", "*.md"]
        events: [modified, created]    # modified, created, deleted, moved 중
        agent: coding
        prompt: |
          파일 {path} 가 변경되었습니다. 중요한 변경이면 한 줄로 요약하세요.
        debounce_seconds: 2
"""

from __future__ import annotations

import asyncio
import fnmatch
import time
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from config.settings import get_settings
from core.input_guard import InputSource
from core.orchestrator import Orchestrator


@dataclass
class WatchRule:
    path: Path
    patterns: list[str]
    events: set[str]
    agent: str
    prompt_template: str
    debounce_seconds: float
    last_fire: dict = field(default_factory=dict)  # {abs_path: last_fire_ts}

    def matches(self, event_path: str, event_type: str) -> bool:
        if event_type not in self.events:
            return False
        if not any(fnmatch.fnmatch(event_path, p) or fnmatch.fnmatch(Path(event_path).name, p) for p in self.patterns):
            return False
        return True

    def should_fire(self, event_path: str) -> bool:
        last = self.last_fire.get(event_path, 0)
        now = time.monotonic()
        if now - last < self.debounce_seconds:
            return False
        self.last_fire[event_path] = now
        return True


class _Handler(FileSystemEventHandler):
    def __init__(self, rule: WatchRule, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
        self.rule = rule
        self.queue = queue
        self.loop = loop

    def _enqueue(self, ev: FileSystemEvent, ev_type: str):
        if ev.is_directory:
            return
        if not self.rule.matches(ev.src_path, ev_type):
            return
        if not self.rule.should_fire(ev.src_path):
            return
        # asyncio 큐는 다른 스레드에서 호출해야 하므로 thread-safe 방식
        self.loop.call_soon_threadsafe(self.queue.put_nowait, (self.rule, ev_type, ev.src_path))

    def on_modified(self, event):
        self._enqueue(event, "modified")

    def on_created(self, event):
        self._enqueue(event, "created")

    def on_deleted(self, event):
        self._enqueue(event, "deleted")

    def on_moved(self, event):
        self._enqueue(event, "moved")


def load_rules() -> list[WatchRule]:
    """settings에서 hooks.watches 정의를 파싱한다."""
    settings = get_settings()
    raw = (settings.get("hooks") or {}).get("watches") or []
    rules: list[WatchRule] = []
    for r in raw:
        try:
            rules.append(WatchRule(
                path=Path(r["path"]).expanduser(),
                patterns=list(r.get("patterns") or ["*"]),
                events=set(r.get("events") or ["modified"]),
                agent=r.get("agent") or "coding",
                prompt_template=r.get("prompt") or "파일 {path}가 {event}되었습니다. 요약하세요.",
                debounce_seconds=float(r.get("debounce_seconds", 2.0)),
            ))
        except KeyError as e:
            logger.warning(f"watch 규칙 누락: {e}")
    return rules


async def watch_loop(orch: Orchestrator) -> None:
    """파일 변경을 감시하고 매칭 규칙에 따라 에이전트를 호출한다."""
    rules = load_rules()
    if not rules:
        logger.warning(
            "settings.yaml에 hooks.watches 정의가 없습니다. 예시는 interfaces/file_watcher.py 헤더 참고."
        )
        return

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    observer = Observer()

    for rule in rules:
        if not rule.path.exists():
            logger.warning(f"감시 경로가 없습니다: {rule.path}")
            continue
        handler = _Handler(rule, queue, loop)
        observer.schedule(handler, str(rule.path), recursive=True)
        logger.info(f"감시 시작: {rule.path} (patterns={rule.patterns}, events={rule.events}) → {rule.agent}")

    observer.start()
    logger.info("파일 시스템 훅 활성 — Ctrl+C로 종료")

    try:
        while True:
            rule, ev_type, src_path = await queue.get()
            prompt = rule.prompt_template.format(path=src_path, event=ev_type)
            logger.info(f"[hook fire] {ev_type} {src_path} → {rule.agent}")
            try:
                response = await orch.route(
                    prompt,
                    agent_name=rule.agent,
                    source=InputSource.CLI,
                    session_id=f"watch:{rule.agent}",
                )
                logger.info(f"[hook response] {response[:200]}")
            except Exception as e:
                logger.error(f"hook 실행 실패: {e}")
    finally:
        observer.stop()
        observer.join()


def run_watch(orch: Orchestrator) -> None:
    """동기 진입점."""
    try:
        asyncio.run(watch_loop(orch))
    except KeyboardInterrupt:
        logger.info("watch 종료")
