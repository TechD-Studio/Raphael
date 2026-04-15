"""클립보드 도구 — read/write."""

from __future__ import annotations

import asyncio
import platform
import shutil


class ClipboardTool:
    async def read(self) -> str:
        system = platform.system()
        if system == "Darwin":
            cmd = ["pbpaste"]
        elif system == "Linux":
            for t in ("wl-paste", "xclip", "xsel"):
                if shutil.which(t):
                    cmd = ["wl-paste"] if t == "wl-paste" else (
                        ["xclip", "-selection", "clipboard", "-o"] if t == "xclip" else
                        ["xsel", "--clipboard", "--output"]
                    )
                    break
            else:
                return "클립보드 도구 없음 (wl-paste/xclip/xsel 설치 필요)"
        else:
            return f"지원하지 않는 OS: {system}"

        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        out, _ = await proc.communicate()
        return out.decode("utf-8", errors="replace")

    async def write(self, text: str) -> str:
        system = platform.system()
        if system == "Darwin":
            cmd = ["pbcopy"]
        elif system == "Linux":
            for t in ("wl-copy", "xclip", "xsel"):
                if shutil.which(t):
                    cmd = ["wl-copy"] if t == "wl-copy" else (
                        ["xclip", "-selection", "clipboard"] if t == "xclip" else
                        ["xsel", "--clipboard", "--input"]
                    )
                    break
            else:
                return "클립보드 도구 없음"
        else:
            return f"지원하지 않는 OS: {system}"

        proc = await asyncio.create_subprocess_exec(
            *cmd, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate(text.encode("utf-8"))
        return f"클립보드에 복사됨 ({len(text)} chars)"
