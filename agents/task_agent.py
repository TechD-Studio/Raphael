"""태스크 에이전트 — 일정, 태스크, 할일 관리."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from core.agent_base import AgentBase
from core.model_router import ModelRouter
from tools.tool_registry import ToolRegistry

SYSTEM_PROMPT = """\
당신은 Raphael의 태스크 관리 에이전트입니다.
역할: 할일 목록 관리, 일정 관리, 태스크 상태 추적을 수행합니다.

규칙:
- 태스크에는 제목, 상태(todo/in_progress/done), 우선순위(high/medium/low)가 있습니다.
- 마감일이 있는 경우 ISO 형식(YYYY-MM-DD)으로 기록합니다.
- 태스크 목록 요청 시 상태별로 정리해서 보여줍니다.
"""

TASKS_FILE = "./data/tasks.json"


@dataclass
class TaskAgent(AgentBase):
    """일정, 태스크, 할일 관리 에이전트."""

    _tasks: list[dict] = field(default_factory=list, repr=False)
    _tasks_file: Path = field(default=None, repr=False)

    def __init__(
        self,
        router: ModelRouter,
        tool_registry: ToolRegistry | None = None,
        **kwargs,
    ) -> None:
        super().__init__(
            name="task",
            description="일정, 태스크, 할일 관리",
            router=router,
            tools=[],
            system_prompt=SYSTEM_PROMPT,
            tool_registry=tool_registry,
        )
        self._tasks_file = Path(kwargs.get("tasks_file", TASKS_FILE))
        self._tasks = self._load_tasks()

    async def handle(self, user_input: str, **kwargs) -> str:
        """태스크 관련 요청을 처리한다."""
        # 현재 태스크 목록을 컨텍스트로 전달
        tasks_ctx = json.dumps(self._tasks, ensure_ascii=False, indent=2) if self._tasks else "없음"
        augmented = f"현재 태스크 목록:\n{tasks_ctx}\n\n요청: {user_input}"
        return await self._call_model(augmented, **kwargs)

    # ── 태스크 CRUD ────────────────────────────────────────

    def add_task(
        self,
        title: str,
        priority: str = "medium",
        due_date: str | None = None,
    ) -> dict:
        """태스크를 추가한다."""
        task = {
            "id": len(self._tasks) + 1,
            "title": title,
            "status": "todo",
            "priority": priority,
            "due_date": due_date,
        }
        self._tasks.append(task)
        self._save_tasks()
        logger.info(f"태스크 추가: {title}")
        return task

    def update_task(self, task_id: int, **kwargs) -> dict | None:
        """태스크를 업데이트한다."""
        for task in self._tasks:
            if task["id"] == task_id:
                task.update(kwargs)
                self._save_tasks()
                logger.info(f"태스크 업데이트: #{task_id}")
                return task
        return None

    def list_tasks(self, status: str | None = None) -> list[dict]:
        """태스크 목록을 반환한다."""
        if status:
            return [t for t in self._tasks if t["status"] == status]
        return list(self._tasks)

    def delete_task(self, task_id: int) -> bool:
        """태스크를 삭제한다."""
        before = len(self._tasks)
        self._tasks = [t for t in self._tasks if t["id"] != task_id]
        if len(self._tasks) < before:
            self._save_tasks()
            logger.info(f"태스크 삭제: #{task_id}")
            return True
        return False

    # ── 저장/로드 ──────────────────────────────────────────

    def _load_tasks(self) -> list[dict]:
        if self._tasks_file.exists():
            return json.loads(self._tasks_file.read_text(encoding="utf-8"))
        return []

    def _save_tasks(self) -> None:
        self._tasks_file.parent.mkdir(parents=True, exist_ok=True)
        self._tasks_file.write_text(
            json.dumps(self._tasks, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
