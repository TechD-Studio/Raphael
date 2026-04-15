"""코드/스크립트 실행기 — subprocess 실행, 로그 기록."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from config.settings import get_settings


@dataclass
class ExecResult:
    """실행 결과."""

    command: str
    return_code: int
    stdout: str
    stderr: str
    duration_seconds: float


class Executor:
    """코드/스크립트를 subprocess로 실행하고 결과를 로그에 기록한다."""

    def __init__(self) -> None:
        settings = get_settings()
        exec_cfg = settings["tools"]["executor"]
        self.log_executions = exec_cfg.get("log_executions", True)
        self.log_path = Path(exec_cfg.get("log_path", "./logs/exec.log"))
        self.timeout = exec_cfg.get("timeout_seconds", 60)

        if self.log_executions:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

    async def run(self, command: str, cwd: str | None = None) -> ExecResult:
        """셸 명령어를 실행하고 결과를 반환한다.

        macOS 환경 보정: `python` 단독 호출은 존재하지 않으므로 자동으로 `python3`로 치환.
        `pip install ...` 은 `python3 -m pip install --user ...` 로 치환 (PEP 668 우회).
        """
        import re as _re
        import shutil as _shutil
        original = command
        # python3가 있고 python이 없을 때만 치환
        if _shutil.which("python3") and not _shutil.which("python"):
            # `python ...`, `&& python ...`, `; python ...` 등 단어 경계 치환
            command = _re.sub(r"(^|[\s;&|])python(?=\s|$)", r"\1python3", command)
        # pip 단독 호출 → python3 -m pip --user
        if _shutil.which("python3") and not _shutil.which("pip"):
            command = _re.sub(
                r"(^|[\s;&|])pip\s+install\s+",
                r"\1python3 -m pip install --user --break-system-packages ",
                command,
            )
        if command != original:
            logger.info(f"실행(보정): {command}")
        else:
            logger.info(f"실행: {command}")
        start = time.monotonic()

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            result = ExecResult(
                command=command,
                return_code=-1,
                stdout="",
                stderr=f"타임아웃: {self.timeout}초 초과",
                duration_seconds=time.monotonic() - start,
            )
            self._log_result(result)
            return result

        duration = time.monotonic() - start
        result = ExecResult(
            command=command,
            return_code=proc.returncode,
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
            duration_seconds=round(duration, 2),
        )

        self._log_result(result)
        return result

    async def run_python(self, code: str) -> ExecResult:
        """Python 코드를 직접 실행한다."""
        # 임시 파일 없이 -c 옵션으로 실행
        escaped = code.replace("'", "'\\''")
        return await self.run(f"python3 -c '{escaped}'")

    def _log_result(self, result: ExecResult) -> None:
        level = "INFO" if result.return_code == 0 else "WARNING"
        logger.log(level, f"실행 완료: rc={result.return_code}, {result.duration_seconds}s")

        if self.log_executions:
            entry = (
                f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
                f"rc={result.return_code} t={result.duration_seconds}s\n"
                f"  cmd: {result.command}\n"
                f"  stdout: {result.stdout[:500]}\n"
                f"  stderr: {result.stderr[:500]}\n"
                f"{'─' * 60}\n"
            )
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(entry)
