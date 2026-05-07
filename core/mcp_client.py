"""MCP (Model Context Protocol) 클라이언트.

settings.yaml의 mcp.servers 정의를 읽어 stdio MCP 서버에 연결하고,
서버가 노출하는 도구들을 raphael의 ToolRegistry에 동적으로 등록한다.

settings 예시:
  mcp:
    servers:
      - name: "filesystem"
        command: "npx"
        args: ["-y", "@modelcontextprotocol/server-filesystem", "/Users/dh/Documents"]
      - name: "github"
        command: "npx"
        args: ["-y", "@modelcontextprotocol/server-github"]
        env:
          GITHUB_PERSONAL_ACCESS_TOKEN: "${GH_TOKEN}"
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass, field

from loguru import logger

from config.settings import get_settings
from tools.tool_registry import ToolRegistry


@dataclass
class MCPServerHandle:
    """등록된 MCP 서버 + 세션 핸들."""

    name: str
    session: object  # mcp.ClientSession
    tools: list[str] = field(default_factory=list)


class MCPClientManager:
    """여러 MCP 서버를 동시에 관리하고, raphael 도구로 노출한다."""

    def __init__(self) -> None:
        self.servers: dict[str, MCPServerHandle] = {}
        self._exit_stack: AsyncExitStack | None = None

    async def start(self, registry: ToolRegistry) -> None:
        """settings의 mcp.servers를 모두 기동하고 ToolRegistry에 등록한다.

        서버들은 asyncio.gather 로 병렬 기동한다. npx 콜드 스타트가 서버당
        5~30초 걸리므로 순차 기동은 합산 지연이 곧 데몬 부팅 지연이 된다.
        하나가 실패해도 나머지는 계속 시도(return_exceptions=True).
        """
        settings = get_settings()
        servers_cfg = (settings.get("mcp") or {}).get("servers") or []
        if not servers_cfg:
            logger.debug("MCP 서버 설정 없음 — 건너뜀")
            return

        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        self._exit_stack = AsyncExitStack()

        async def _start_one(cfg: dict) -> None:
            name = cfg.get("name", "?")
            try:
                params = StdioServerParameters(
                    command=cfg["command"],
                    args=cfg.get("args", []),
                    env=cfg.get("env"),
                )
                read, write = await self._exit_stack.enter_async_context(stdio_client(params))
                session = await self._exit_stack.enter_async_context(ClientSession(read, write))
                await session.initialize()

                tools_resp = await session.list_tools()
                tool_names = []
                for tool in tools_resp.tools:
                    tool_names.append(f"mcp_{name}_{tool.name}")
                    registry.register(
                        f"mcp:{name}:{tool.name}",
                        _MCPToolProxy(session, tool.name),
                        f"[MCP {name}] {tool.description or tool.name}",
                    )
                self.servers[name] = MCPServerHandle(name=name, session=session, tools=tool_names)
                logger.info(f"MCP 서버 연결: {name} ({len(tool_names)}개 도구)")
            except Exception as e:
                logger.error(f"MCP 서버 '{name}' 연결 실패: {e}")

        await asyncio.gather(
            *(_start_one(cfg) for cfg in servers_cfg),
            return_exceptions=True,
        )

    async def stop(self) -> None:
        if self._exit_stack:
            await self._exit_stack.aclose()
            self._exit_stack = None
        self.servers.clear()

    def list_tools(self) -> list[dict]:
        out = []
        for name, h in self.servers.items():
            for t in h.tools:
                out.append({"server": name, "tool": t})
        return out


@dataclass
class _MCPToolProxy:
    """ToolRegistry에 등록되는 wrapper. MCP 서버의 도구를 호출한다."""
    session: object
    tool_name: str

    async def call(self, args: dict) -> str:
        """MCP 서버에 도구 호출 위임."""
        try:
            result = await self.session.call_tool(self.tool_name, args)
            # MCP 응답에서 텍스트 추출
            parts = []
            for item in result.content or []:
                text = getattr(item, "text", None) or str(item)
                parts.append(text)
            return "\n".join(parts) if parts else "(빈 결과)"
        except Exception as e:
            return f"MCP 도구 호출 실패: {e}"
