"""Reviewer 에이전트 — 작업 결과를 검토해 부족한 부분 지적.

사용 흐름: planner가 작업 종료 후 reviewer를 호출해 자체 평가.
또는 사용자가 직접 'raphael review "방금 작업"' 으로 호출.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.agent_base import AgentBase
from core.model_router import ModelRouter
from core.prompts import TOOL_USAGE_PROMPT
from tools.tool_registry import ToolRegistry


ROLE_PROMPT = """\
당신은 Raphael의 Reviewer(검토자) 에이전트입니다.
역할: 다른 에이전트가 수행한 작업 결과를 비판적으로 검토하고 부족한 부분을 명확히 지적합니다.

## 검토 절차

1. 사용자가 제공한 작업 컨텍스트를 이해.
2. 필요시 read_file로 산출물을 직접 확인.
3. 다음 항목을 평가:
   - 요구사항 충족도 (사용자 의도 vs 실제 결과)
   - 완성도 (빈 파일, 누락된 섹션, 미완성 코드 등)
   - 정확성 (사실 오류, 버그 가능성)
   - 사용성 (사용자가 바로 활용 가능한가)

4. 결과 보고 형식:

```
## 검토 결과

### ✅ 좋은 점
- ...

### ⚠ 보완 필요
- ...

### 🔧 권장 다음 작업
- ...
```

## 규칙
- 칭찬보다 누락/오류를 우선 발견.
- 추측 금지 — 파일 실제 내용을 read_file로 확인 후 평가.
- 사용자가 즉시 후속 작업을 결정할 수 있도록 구체적으로 제시.
"""


@dataclass
class ReviewerAgent(AgentBase):
    """작업 결과 비판적 검토 에이전트."""

    def __init__(self, router: ModelRouter, tool_registry: ToolRegistry | None = None) -> None:
        super().__init__(
            name="reviewer",
            description="작업 결과 비판적 검토 + 보완 지시",
            router=router,
            tools=["file_reader", "delegate"],
            system_prompt=ROLE_PROMPT + "\n\n" + TOOL_USAGE_PROMPT,
            tool_registry=tool_registry,
        )

    async def handle(self, user_input: str, **kwargs) -> str:
        return await self._call_model(user_input, **kwargs)
