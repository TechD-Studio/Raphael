"""코딩 에이전트 — 코드 작성, 실행, 디버깅."""

from __future__ import annotations

from dataclasses import dataclass

from core.agent_base import AgentBase
from core.model_router import ModelRouter
from core.prompts import TOOL_USAGE_PROMPT
from tools.tool_registry import ToolRegistry


ROLE_PROMPT = """\
당신은 Raphael의 코딩 에이전트입니다.
역할: 코드 작성, 실행, 디버깅, 리팩토링, 파일 시스템 조작을 수행합니다.

규칙:
- 파일 읽기/쓰기/삭제가 필요하면 read_file/write_file/delete_file 도구를 사용한다.
- 코드 실행이 필요하면 execute 또는 python 도구를 사용한다.
- 웹에서 정보를 찾아야 하면 web_search 도구를 사용한다.
- 에러 발생 시 원인을 분석하고 수정안을 제시한다.
- 코드 블록은 언어를 명시한다.
"""


@dataclass
class CodingAgent(AgentBase):
    """코드 작성, 실행, 디버깅 에이전트."""

    def __init__(self, router: ModelRouter, tool_registry: ToolRegistry | None = None) -> None:
        super().__init__(
            name="coding",
            description="코드 작성, 실행, 디버깅, 파일 조작",
            router=router,
            tools=["executor", "file_reader", "file_writer", "web_search", "git_tool", "delegate", "browser_tool", "profile", "screenshot_tool", "clipboard_tool", "mcp", "notification_tool", "calendar_tool", "email_tool", "converter_tool", "voice"],
            system_prompt=ROLE_PROMPT + "\n\n" + TOOL_USAGE_PROMPT,
            tool_registry=tool_registry,
        )

    async def handle(self, user_input: str, **kwargs) -> str:
        """사용자 입력을 처리한다. _call_model이 tool 루프를 자동 수행."""
        return await self._call_model(user_input, **kwargs)
