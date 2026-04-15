"""툴 레지스트리 — 에이전트가 사용할 수 있는 툴을 등록/조회한다."""

from __future__ import annotations

from typing import Any, Callable

from loguru import logger


class ToolRegistry:
    """전역 툴 레지스트리. 이름으로 툴 인스턴스를 등록하고 조회한다."""

    def __init__(self) -> None:
        self._tools: dict[str, Any] = {}
        self._descriptions: dict[str, str] = {}

    def register(self, name: str, tool: Any, description: str = "") -> None:
        """툴을 등록한다."""
        self._tools[name] = tool
        self._descriptions[name] = description
        logger.debug(f"툴 등록: {name}")

    def get(self, name: str) -> Any:
        """이름으로 툴을 가져온다."""
        if name not in self._tools:
            raise ValueError(f"Unknown tool: {name}. Available: {list(self._tools.keys())}")
        return self._tools[name]

    def list_tools(self) -> list[dict[str, str]]:
        """등록된 툴 목록을 반환한다."""
        return [
            {"name": name, "description": self._descriptions.get(name, "")}
            for name in self._tools
        ]

    def has(self, name: str) -> bool:
        return name in self._tools


def create_default_registry() -> ToolRegistry:
    """기본 툴들을 등록한 레지스트리를 반환한다."""
    from tools.executor import Executor
    from tools.file_reader import FileReader
    from tools.file_writer import FileWriter
    from tools.browser_tool import BrowserTool
    from tools.calendar_tool import CalendarTool
    from tools.clipboard_tool import ClipboardTool
    from tools.converter_tool import ConverterTool
    from tools.email_tool import EmailTool
    from tools.fetch_tool import FetchTool
    from tools.git_tool import GitTool
    from tools.notification_tool import NotificationTool
    from tools.screenshot_tool import ScreenshotTool
    from tools.web_search import WebSearch

    registry = ToolRegistry()
    registry.register("file_reader", FileReader(), "파일 읽기 (txt, md, pdf, csv, 코드)")
    registry.register("file_writer", FileWriter(), "파일 생성/수정/삭제")
    registry.register("executor", Executor(), "코드/스크립트 실행")
    registry.register("web_search", WebSearch(), "웹 검색 (DuckDuckGo)")
    registry.register("git_tool", GitTool(), "Git 조작 (status/diff/log/commit)")
    registry.register("browser_tool", BrowserTool(), "기본 브라우저에서 파일/URL 열기")
    registry.register("screenshot_tool", ScreenshotTool(), "화면 캡처 (PNG 저장)")
    registry.register("clipboard_tool", ClipboardTool(), "시스템 클립보드 R/W")
    registry.register("notification_tool", NotificationTool(), "시스템 알림")
    registry.register("calendar_tool", CalendarTool(), "캘린더 이벤트 추가")
    registry.register("email_tool", EmailTool(), "이메일 IMAP/SMTP")
    registry.register("converter_tool", ConverterTool(), "파일 변환 (md→html/pdf, csv→차트)")
    registry.register("fetch_tool", FetchTool(), "URL 컨텐츠 가져오기 + 본문 추출 + 선택 요약")

    logger.info(f"기본 툴 레지스트리 생성: {[t['name'] for t in registry.list_tools()]}")
    return registry
