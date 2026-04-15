"""스크린샷 도구 — OS 네이티브 명령으로 화면 캡처.

macOS:  screencapture
Linux:  gnome-screenshot, scrot, grim (Wayland) 자동 탐색
Windows: PowerShell Add-Type (간이)

캡처된 PNG는 /tmp 또는 지정 경로에 저장. base64 옵션 가능.
"""

from __future__ import annotations

import asyncio
import platform
import shutil
import tempfile
from pathlib import Path

from loguru import logger


class ScreenshotTool:
    async def capture(self, path: str | None = None, full_screen: bool = True) -> str:
        """화면을 캡처해 PNG 경로를 반환한다."""
        if not path:
            path = tempfile.mktemp(prefix="raphael_screenshot_", suffix=".png")
        path = str(Path(path).expanduser().resolve())

        system = platform.system()
        if system == "Darwin":
            cmd = ["screencapture", "-x"] + (["-S"] if not full_screen else []) + [path]
        elif system == "Linux":
            for tool in ("grim", "gnome-screenshot", "scrot"):
                if shutil.which(tool):
                    if tool == "grim":
                        cmd = ["grim", path]
                    elif tool == "gnome-screenshot":
                        cmd = ["gnome-screenshot", "-f", path]
                    else:
                        cmd = ["scrot", path]
                    break
            else:
                return "스크린샷 도구 없음 (grim/gnome-screenshot/scrot 설치 필요)"
        else:
            return f"지원하지 않는 OS: {system}"

        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, err = await proc.communicate()
        if proc.returncode != 0:
            return f"스크린샷 실패: {err.decode('utf-8', errors='replace').strip()}"

        if not Path(path).exists():
            return "스크린샷 파일이 생성되지 않음 (사용자 취소?)"
        logger.info(f"스크린샷 저장: {path}")
        return path
