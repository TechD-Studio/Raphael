"""입력 보안 — 신뢰된 소스 검증 + 명령어 인젝션 방어.

신뢰된 소스: CLI(로컬), WebUI(로컬), 등록된 텔레그램/디스코드 유저.
비신뢰 소스(웹 검색 결과, 이메일, 외부 문서 등)에서 유입된 텍스트에
명령어처럼 보이는 패턴이 있어도 실행하지 않는다.
"""

from __future__ import annotations

import re
from enum import Enum

from loguru import logger


class InputSource(Enum):
    """입력이 어디서 왔는지 식별."""

    CLI = "cli"
    WEB_UI = "web_ui"
    TELEGRAM = "telegram"
    DISCORD = "discord"
    # 비신뢰 소스
    RAG_CONTEXT = "rag_context"
    WEB_SEARCH = "web_search"
    FILE_CONTENT = "file_content"
    EXTERNAL = "external"


# 신뢰된 소스 목록
TRUSTED_SOURCES = frozenset({
    InputSource.CLI,
    InputSource.WEB_UI,
    InputSource.TELEGRAM,
    InputSource.DISCORD,
})

# 명령어로 간주되는 패턴들
_COMMAND_PATTERNS = [
    r"^/\w+",                      # /command 형식
    r"^!\w+",                      # !command 형식
    r"^(raphael|raph)\s+\w+",     # raphael 명령어 형식
]

_COMMAND_RE = re.compile("|".join(_COMMAND_PATTERNS), re.IGNORECASE)

# 위험한 인젝션 패턴 (외부 텍스트가 시스템 동작을 조작하려는 시도)
_INJECTION_PATTERNS = [
    r"ignore\s+(previous|above|all)[\s\w]*(instructions?|prompts?)",
    r"disregard\s+(previous|above|all)[\s\w]*(instructions?|prompts?)?",
    r"you\s+are\s+now\s+",
    r"new\s+instructions?:",
    r"system\s*:\s*",
    r"<\s*system\s*>",
    r"execute\s+(this|the\s+following)\s+(command|code|script)",
    r"run\s+(this|the\s+following)\s+(command|code|script)",
    r"eval\s*\(",
    r"exec\s*\(",
    r"subprocess",
    r"os\.system",
    r"이전\s*지시를?\s*무시",
    r"새로운\s*지시",
    r"명령어를?\s*실행",
]

_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)


def is_trusted(source: InputSource) -> bool:
    """입력 소스가 신뢰된 소스인지 확인한다."""
    return source in TRUSTED_SOURCES


def contains_command(text: str) -> bool:
    """텍스트에 명령어 패턴이 포함되어 있는지 확인한다."""
    return bool(_COMMAND_RE.search(text.strip()))


def contains_injection(text: str) -> bool:
    """텍스트에 프롬프트 인젝션 패턴이 포함되어 있는지 확인한다."""
    return bool(_INJECTION_RE.search(text))


def sanitize_external_text(text: str) -> str:
    """비신뢰 소스의 텍스트에서 명령어/인젝션 패턴을 무력화한다.

    명령어 접두사(/, !)를 유니코드 유사 문자로 교체하고,
    인젝션 패턴을 [BLOCKED] 으로 치환한다.
    """
    # /command → ∕command (유니코드 슬래시로 교체 — 시각적으로 유사하지만 명령어로 파싱 안됨)
    sanitized = re.sub(r"^(/\w+)", lambda m: "\u2215" + m.group(1)[1:], text, flags=re.MULTILINE)

    # 인젝션 패턴 치환
    sanitized = _INJECTION_RE.sub("[blocked]", sanitized)

    return sanitized


def validate_input(text: str, source: InputSource) -> tuple[str, list[str]]:
    """입력을 검증하고 필요 시 정제한다.

    Returns:
        (정제된 텍스트, 경고 메시지 리스트)
    """
    warnings: list[str] = []

    if is_trusted(source):
        # 신뢰된 소스: 그대로 통과
        return text, warnings

    # 비신뢰 소스: 검사 + 정제
    if contains_injection(text):
        warnings.append(f"프롬프트 인젝션 패턴 감지 (source={source.value})")
        logger.warning(f"인젝션 패턴 감지: source={source.value}, text={text[:100]}...")

    if contains_command(text):
        warnings.append(f"명령어 패턴 감지 — 비신뢰 소스이므로 실행하지 않음 (source={source.value})")
        logger.warning(f"비신뢰 소스 명령어 차단: source={source.value}, text={text[:100]}...")

    sanitized = sanitize_external_text(text)
    return sanitized, warnings
