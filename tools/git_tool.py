"""Git 통합 도구 — status/diff/log/commit."""

from __future__ import annotations

import asyncio
from pathlib import Path

from loguru import logger


class GitTool:
    """Git 명령어 실행. cwd는 호출 시마다 지정 가능 (기본: 현재 작업 디렉토리)."""

    async def _run(self, args: list[str], cwd: str | None = None) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd or None,
        )
        out, err = await proc.communicate()
        return proc.returncode, out.decode("utf-8", errors="replace"), err.decode("utf-8", errors="replace")

    async def status(self, cwd: str | None = None) -> str:
        rc, out, err = await self._run(["status", "--short"], cwd)
        if rc != 0:
            return f"git status 실패: {err.strip()}"
        return out.strip() or "(변경 없음)"

    async def diff(self, path: str | None = None, cwd: str | None = None, staged: bool = False) -> str:
        args = ["diff"]
        if staged:
            args.append("--staged")
        if path:
            args.extend(["--", path])
        rc, out, err = await self._run(args, cwd)
        if rc != 0:
            return f"git diff 실패: {err.strip()}"
        if not out.strip():
            return "(diff 없음)"
        # 길이 제한 — LLM 컨텍스트 초과 방지
        if len(out) > 8000:
            out = out[:8000] + f"\n\n... (잘림, 전체 {len(out)}자)"
        return out

    async def log(self, n: int = 10, cwd: str | None = None) -> str:
        rc, out, err = await self._run(
            ["log", f"-n{n}", "--oneline", "--decorate"],
            cwd,
        )
        if rc != 0:
            return f"git log 실패: {err.strip()}"
        return out.strip() or "(커밋 없음)"

    async def commit(self, message: str, cwd: str | None = None) -> str:
        """스테이지된 변경에 대해 커밋."""
        if not message.strip():
            return "커밋 메시지가 비어있습니다."
        # 스테이지 확인
        rc, out, _ = await self._run(["diff", "--staged", "--name-only"], cwd)
        if rc != 0 or not out.strip():
            return "스테이지된 변경이 없습니다. 먼저 git add 를 실행하세요."

        rc, out, err = await self._run(["commit", "-m", message], cwd)
        if rc != 0:
            return f"commit 실패: {err.strip()}"
        return out.strip()
