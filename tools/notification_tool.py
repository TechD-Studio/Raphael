"""시스템 알림 — macOS Notification Center / Linux notify-send."""

from __future__ import annotations

import asyncio
import platform
import shutil


class NotificationTool:
    async def notify(self, title: str, message: str = "") -> str:
        system = platform.system()
        if system == "Darwin":
            script = f'display notification "{message}" with title "{title}"'
            cmd = ["osascript", "-e", script]
        elif system == "Linux":
            if not shutil.which("notify-send"):
                return "notify-send 미설치 (sudo apt install libnotify-bin)"
            cmd = ["notify-send", title, message]
        else:
            return f"미지원 OS: {system}"

        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()
        return f"알림 전송: {title}"
