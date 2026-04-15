"""브라우저 열기 도구 — 로컬 파일 또는 URL을 기본 브라우저에서 연다.

cross-platform: webbrowser 모듈 사용 (Mac/Linux/Windows 자동 감지).
파일 경로 입력 시 path_guard로 검증한 후 file:// URL로 변환.
"""

from __future__ import annotations

import webbrowser
from pathlib import Path

from loguru import logger

from tools.path_guard import PathNotAllowedError, check_path


class BrowserTool:
    """기본 브라우저에서 파일/URL 열기."""

    SAFE_SCHEMES = ("http://", "https://", "file://")

    def open(self, target: str) -> str:
        """target이 URL이면 그대로, 파일 경로면 file:// 로 변환해 연다."""
        if not target or not target.strip():
            return "열 대상이 없습니다."

        target = target.strip()

        # URL인지 검사
        if target.startswith(self.SAFE_SCHEMES):
            ok = webbrowser.open(target)
            return f"브라우저 열기 {'성공' if ok else '실패'}: {target}"

        # 파일 경로 — 샌드박스 통과 후 file:// 로
        try:
            resolved = check_path(target)
        except PathNotAllowedError as e:
            return f"파일 열기 거부: {e}"

        if not resolved.exists():
            return f"파일이 존재하지 않습니다: {resolved}"
        if not resolved.is_file():
            return f"파일이 아닙니다: {resolved}"

        url = f"file://{resolved}"
        ok = webbrowser.open(url)
        logger.info(f"브라우저 열기: {url} (성공={ok})")
        return f"브라우저 열기 {'성공' if ok else '실패'}: {resolved}"
