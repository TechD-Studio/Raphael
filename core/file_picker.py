"""OS 네이티브 폴더 선택 다이얼로그.

Mac: osascript (AppleScript)
Linux: zenity → kdialog → tkinter 순서로 fallback
"""

from __future__ import annotations

import asyncio
import platform
import shutil
from pathlib import Path


class PickerError(Exception):
    """폴더 선택 실패."""


async def pick_directory(initial_dir: str | None = None, title: str = "폴더 선택") -> str:
    """OS 네이티브 폴더 선택 다이얼로그를 열고 선택된 경로를 반환한다.

    사용자가 취소하면 빈 문자열을 반환한다.
    지원하지 않는 환경이면 PickerError를 발생시킨다.
    """
    system = platform.system()

    if system == "Darwin":
        return await _pick_mac(initial_dir, title)
    elif system == "Linux":
        return await _pick_linux(initial_dir, title)
    else:
        raise PickerError(f"지원하지 않는 OS: {system}")


# ── Mac ───────────────────────────────────────────────────


async def _pick_mac(initial_dir: str | None, title: str) -> str:
    """AppleScript로 Finder 폴더 선택 다이얼로그 실행."""
    initial = ""
    if initial_dir:
        expanded = str(Path(initial_dir).expanduser())
        if Path(expanded).is_dir():
            # AppleScript escape
            escaped = expanded.replace('"', '\\"')
            initial = f' default location POSIX file "{escaped}"'

    title_escaped = title.replace('"', '\\"')
    script = f'POSIX path of (choose folder with prompt "{title_escaped}"{initial})'

    try:
        result = await _run(["osascript", "-e", script])
    except _UserCancelled:
        return ""
    return result.strip().rstrip("/")


# ── Linux ─────────────────────────────────────────────────


async def _pick_linux(initial_dir: str | None, title: str) -> str:
    """zenity → kdialog → tkinter 순으로 시도한다."""
    expanded = str(Path(initial_dir).expanduser()) if initial_dir else str(Path.home())

    if shutil.which("zenity"):
        try:
            return (await _run([
                "zenity", "--file-selection", "--directory",
                f"--title={title}",
                f"--filename={expanded}/",
            ])).strip()
        except _UserCancelled:
            return ""

    if shutil.which("kdialog"):
        try:
            return (await _run([
                "kdialog", "--getexistingdirectory", expanded,
                "--title", title,
            ])).strip()
        except _UserCancelled:
            return ""

    # tkinter fallback — python3-tk 패키지 필요
    return await asyncio.get_event_loop().run_in_executor(
        None, _pick_tkinter, expanded, title
    )


def _pick_tkinter(initial_dir: str, title: str) -> str:
    """tkinter 기반 폴더 선택. 동기 함수로, executor에서 실행해야 함."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        raise PickerError(
            "폴더 선택 도구를 찾을 수 없습니다. "
            "다음 중 하나를 설치하세요: zenity (GTK), kdialog (KDE), python3-tk"
        )

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        path = filedialog.askdirectory(title=title, initialdir=initial_dir)
    finally:
        root.destroy()

    return path or ""


# ── subprocess 헬퍼 ───────────────────────────────────────


class _UserCancelled(Exception):
    pass


async def _run(cmd: list[str]) -> str:
    """서브프로세스를 실행하고 stdout을 반환한다.

    exit code가 1 (osascript/zenity/kdialog의 '사용자 취소')이면
    _UserCancelled를 발생시킨다.
    """
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode == 1:
        # 사용자가 취소한 경우
        raise _UserCancelled()

    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace").strip()
        raise PickerError(f"다이얼로그 실행 실패 (rc={proc.returncode}): {err}")

    return stdout.decode("utf-8", errors="replace")
