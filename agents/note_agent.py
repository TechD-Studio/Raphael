"""노트 에이전트 — 옵시디언 노트 작성, 정리, 검색."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.agent_base import AgentBase
from core.model_router import ModelRouter
from core.prompts import TOOL_USAGE_PROMPT
from config.settings import get_settings
from memory.rag import RAGManager
from tools.tool_registry import ToolRegistry


ROLE_PROMPT = """\
당신은 Raphael의 노트 에이전트입니다.
역할: 옵시디언 볼트에서 노트를 검색하고, 새 노트를 작성하고, 기존 노트를 정리합니다.

규칙:
- 노트를 읽을 때는 read_file, 작성/수정할 때는 write_file/append_file 도구를 사용한다.
- 노트는 마크다운 형식으로 작성한다.
- 옵시디언 링크 [[제목]] 문법을 활용한다.
- 태그는 #태그 형식을 사용한다.
"""


@dataclass
class NoteAgent(AgentBase):
    """옵시디언 노트 작성/정리/검색 에이전트."""

    rag: RAGManager = field(default=None, repr=False)
    vault_path: Path = field(default=None, repr=False)

    def __init__(
        self,
        router: ModelRouter,
        rag: RAGManager | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        super().__init__(
            name="note",
            description="옵시디언 노트 작성/정리/검색",
            router=router,
            tools=["file_reader", "file_writer"],
            system_prompt=ROLE_PROMPT + "\n\n" + TOOL_USAGE_PROMPT,
            tool_registry=tool_registry,
        )
        self.rag = rag
        self.vault_path = Path(get_settings()["memory"]["obsidian_vault"]).expanduser()

    async def handle(self, user_input: str, **kwargs) -> str:
        """노트 관련 요청을 처리한다."""
        context = ""
        if self.rag:
            try:
                context = await self.rag.build_context(user_input)
            except Exception:
                context = ""

        # 볼트 경로를 프롬프트에 포함시켜 에이전트가 파일 도구로 정확한 경로를 쓸 수 있게 한다
        prefix = f"(옵시디언 볼트: {self.vault_path})\n"
        if context:
            augmented = f"{prefix}{context}\n\n위 노트를 참고하여 답변해주세요.\n\n요청: {user_input}"
        else:
            augmented = f"{prefix}요청: {user_input}"

        return await self._call_model(augmented, **kwargs)

    async def search_notes(self, query: str, n_results: int = 5) -> list[dict]:
        """노트를 검색한다."""
        if not self.rag:
            return []
        results = await self.rag.search(query, n_results)
        return [
            {"content": r.content, "metadata": r.metadata, "distance": r.distance}
            for r in results
        ]
