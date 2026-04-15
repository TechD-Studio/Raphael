"""리서치 에이전트 — 문서 분석, 요약, RAG + 웹 검색 기반 질의응답."""

from __future__ import annotations

from dataclasses import dataclass, field

from core.agent_base import AgentBase
from core.model_router import ModelRouter
from core.prompts import TOOL_USAGE_PROMPT
from memory.rag import RAGManager
from tools.tool_registry import ToolRegistry


ROLE_PROMPT = """\
당신은 Raphael의 리서치 에이전트입니다.
역할: 문서를 분석하고, 요약하고, 질문에 답변합니다.

규칙:
- 옵시디언 노트에서 관련 정보를 검색해 답변에 활용한다 (자동 제공되는 <context>).
- 최신 정보나 외부 지식이 필요하면 web_search 도구를 사용한다.
- 파일을 읽어야 하면 read_file 도구를 사용한다.
- 출처를 명시한다.
- 정보가 부족하면 솔직히 모른다고 말한다.
"""


@dataclass
class ResearchAgent(AgentBase):
    """문서 분석 + 요약 + RAG + 웹 검색 질의응답 에이전트."""

    rag: RAGManager = field(default=None, repr=False)

    def __init__(
        self,
        router: ModelRouter,
        rag: RAGManager | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        super().__init__(
            name="research",
            description="문서 분석, 요약, RAG + 웹 검색 질의응답",
            router=router,
            tools=["file_reader", "web_search"],
            system_prompt=ROLE_PROMPT + "\n\n" + TOOL_USAGE_PROMPT,
            tool_registry=tool_registry,
        )
        self.rag = rag

    async def handle(self, user_input: str, **kwargs) -> str:
        """사용자 질문에 RAG 컨텍스트를 붙여 모델에 전달한다."""
        context = ""
        if self.rag:
            try:
                context = await self.rag.build_context(user_input)
            except Exception:
                context = ""

        if context:
            augmented = f"{context}\n\n위 컨텍스트를 참고하여 답변해주세요.\n\n질문: {user_input}"
        else:
            augmented = user_input

        return await self._call_model(augmented, **kwargs)

    async def search(self, query: str, n_results: int = 5) -> list[dict]:
        """RAG 검색 결과를 반환한다."""
        if not self.rag:
            return []
        results = await self.rag.search(query, n_results)
        return [
            {"content": r.content, "metadata": r.metadata, "distance": r.distance}
            for r in results
        ]
