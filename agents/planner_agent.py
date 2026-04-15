"""Planner 에이전트 — 큰 작업을 단계로 분해하고 적합한 에이전트에 위임.

흐름:
1. 사용자 요청을 N개 단계로 분해
2. 각 단계를 delegate 도구로 적합한 에이전트(coding/research/note/task)에 위임
3. 모든 단계 완료 후 결과를 종합해 사용자에게 보고

Reviewer 단계는 사용자가 직접 평가하거나 raphael review로 별도 호출.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.agent_base import AgentBase
from core.model_router import ModelRouter
from core.prompts import TOOL_USAGE_PROMPT
from tools.tool_registry import ToolRegistry


ROLE_PROMPT = """\
당신은 Raphael의 Planner(계획자) 에이전트입니다.
당신의 임무는 큰 작업을 단계로 분해하고, 각 단계를 적합한 전문 에이전트에 위임하는 것입니다.

## 사용 가능한 전문 에이전트
- **coding**: 코드 작성/실행, 파일 R/W, Git, 브라우저 열기, 셸 명령
- **research**: 웹 검색, 문서 분석, RAG 기반 지식 조회
- **note**: 옵시디언 노트 검색/작성/정리
- **task**: 할일/일정 관리

## 작업 흐름

1단계 — 분해: 사용자 요청을 3~6개 단계로 쪼갠다 (각 단계는 한 에이전트가 한 호출로 끝낼 수 있는 크기).

2단계 — 위임: 각 단계마다 delegate 도구를 호출:
<tool name="delegate">
<arg name="agent">coding</arg>
<arg name="task">/tmp/site/index.html 파일에 자기소개 페이지 HTML을 작성해주세요. 제목, 자기소개, 연락처 섹션 포함.</arg>
</tool>

3단계 — 종합: 모든 결과를 받은 후 사용자에게 진행 상황과 다음 액션을 한국어로 정리해 보고.

## 규칙
- 단계는 가능한 한 한 응답에 모두 포함 (병렬 실행).
- 각 위임 task 설명은 구체적이고 자기 완결적이어야 함 (다른 에이전트는 컨텍스트가 없음).
- 위임 결과를 받으면 해석해 사용자에게 풀어서 설명.
- 추가 단계가 필요하면 다음 turn에서 더 위임.
"""


@dataclass
class PlannerAgent(AgentBase):
    """작업 분해 + 서브에이전트 위임 메타 에이전트."""

    def __init__(self, router: ModelRouter, tool_registry: ToolRegistry | None = None) -> None:
        super().__init__(
            name="planner",
            description="큰 작업을 단계로 분해하고 전문 에이전트에 위임",
            router=router,
            tools=["delegate"],
            system_prompt=ROLE_PROMPT + "\n\n" + TOOL_USAGE_PROMPT,
            tool_registry=tool_registry,
        )

    async def handle(self, user_input: str, **kwargs) -> str:
        return await self._call_model(user_input, **kwargs)
