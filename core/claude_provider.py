"""Claude Code 구독 (CLI) 백엔드.

Anthropic API 키 없이, 사용자가 이미 설치/로그인한 `claude` CLI를 통해
Claude Pro/Max 구독을 활용한다.

흐름:
  ModelRouter.chat → cfg.provider == "claude_cli" → ClaudeCodeProvider.chat
  → asyncio subprocess "claude -p PROMPT --output-format json"
  → JSON 파싱 → Ollama 호환 응답 형식으로 변환

스트리밍은 --output-format stream-json 으로 라인별 처리.

요구사항:
- `claude` CLI 설치 + 로그인 (Pro/Max 구독)
- macOS/Linux 모두 동일

settings.yaml 예시:
  models:
    available:
      claude-sonnet:
        provider: claude_cli
        name: "claude (sonnet)"
        description: "Claude Code 구독 (Sonnet)"
        cli_args: ["--model", "sonnet"]    # 또는 빈 리스트
        allowed_tools: ["Read"]            # claude 쪽 도구 권한
"""

from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import dataclass

from loguru import logger


class ClaudeCLIError(Exception):
    """claude CLI 실행 실패 또는 인증 만료."""


@dataclass
class ClaudeCodeProvider:
    """`claude -p` headless 호출 wrapper."""

    cli_path: str | None = None

    def __post_init__(self) -> None:
        if self.cli_path is None:
            self.cli_path = shutil.which("claude")

    def is_available(self) -> bool:
        return self.cli_path is not None

    # ── 메시지 변환 ────────────────────────────────────────

    @staticmethod
    def _messages_to_prompt(messages: list[dict]) -> str:
        """raphael messages 리스트를 단일 prompt 문자열로 직렬화.

        claude CLI는 자체적으로 system/대화 컨텍스트를 관리하지 않으므로
        매 호출에 전체 히스토리를 합쳐서 보낸다. (또는 --resume 으로 세션 유지 가능 — 후속)
        """
        parts: list[str] = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if not content:
                continue
            if role == "system":
                parts.append(f"[SYSTEM]\n{content}\n")
            elif role == "user":
                parts.append(f"[USER]\n{content}\n")
            elif role == "assistant":
                parts.append(f"[ASSISTANT]\n{content}\n")
            else:
                parts.append(f"[{role.upper()}]\n{content}\n")
        return "\n".join(parts).strip()

    # ── 명령 구성 ──────────────────────────────────────────

    def _build_cmd(
        self,
        prompt: str,
        cli_args: list[str] | None = None,
        allowed_tools: list[str] | None = None,
        stream: bool = False,
        session_id: str | None = None,
    ) -> list[str]:
        cmd = [self.cli_path, "-p", prompt]
        if stream:
            cmd.extend(["--output-format", "stream-json", "--verbose"])
        else:
            cmd.extend(["--output-format", "json"])
        if allowed_tools is not None:
            # 빈 리스트면 도구 사용 차단 (보안)
            cmd.extend(["--allowedTools", ",".join(allowed_tools) if allowed_tools else "none"])
        if session_id:
            cmd.extend(["--resume", session_id])
        if cli_args:
            cmd.extend(cli_args)
        return cmd

    # ── 비스트리밍 chat ────────────────────────────────────

    async def chat(
        self,
        messages: list[dict],
        cli_args: list[str] | None = None,
        allowed_tools: list[str] | None = None,
        session_id: str | None = None,
        timeout: float = 600.0,
    ) -> dict:
        if not self.is_available():
            raise ClaudeCLIError(
                "claude CLI가 설치되어 있지 않습니다. 설치 후 'claude login' 또는 구독 인증을 완료하세요."
            )
        prompt = self._messages_to_prompt(messages)
        cmd = self._build_cmd(prompt, cli_args=cli_args, allowed_tools=allowed_tools, session_id=session_id)
        logger.debug(f"claude chat → {cmd[:4]}... (prompt {len(prompt)} chars)")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise ClaudeCLIError(f"claude CLI 타임아웃 ({timeout}s)")

        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace").strip()
            raise ClaudeCLIError(f"claude CLI 실패 (rc={proc.returncode}): {err[:300]}")

        return self._to_ollama_format(stdout.decode("utf-8", errors="replace"))

    # ── 스트리밍 chat ──────────────────────────────────────

    async def chat_stream(
        self,
        messages: list[dict],
        cli_args: list[str] | None = None,
        allowed_tools: list[str] | None = None,
        session_id: str | None = None,
    ):
        """라인별 stream-json 파싱 → Ollama 호환 chunk yield."""
        if not self.is_available():
            raise ClaudeCLIError("claude CLI 미설치")
        prompt = self._messages_to_prompt(messages)
        cmd = self._build_cmd(prompt, cli_args=cli_args, allowed_tools=allowed_tools, stream=True, session_id=session_id)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            assert proc.stdout is not None
            buf = ""
            async for raw in proc.stdout:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # stream-json 이벤트 → text delta 추출
                text = self._extract_stream_text(obj)
                if text:
                    yield {"message": {"content": text}, "done": False}
                # 종료 이벤트
                if obj.get("type") == "result" or obj.get("type") == "stop":
                    yield {"message": {"content": ""}, "done": True}
                    return
        finally:
            if proc.returncode is None:
                proc.terminate()
            try:
                await proc.wait()
            except Exception:
                pass

    @staticmethod
    def _extract_stream_text(obj: dict) -> str:
        """다양한 stream-json 이벤트 타입에서 텍스트 추출."""
        # claude code stream-json 형식은 버전마다 다를 수 있어 안전하게 fallback
        t = obj.get("type", "")
        if t == "content_block_delta":
            d = obj.get("delta", {})
            return d.get("text", "") or ""
        if t == "message_delta":
            return obj.get("delta", {}).get("text", "") or ""
        if t == "assistant" or t == "text":
            msg = obj.get("message") or obj
            content = msg.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return "".join(c.get("text", "") for c in content if isinstance(c, dict))
        if t == "result":
            return obj.get("result", "") or ""
        return ""

    # ── 응답 변환 ──────────────────────────────────────────

    @staticmethod
    def _to_ollama_format(stdout_text: str) -> dict:
        """claude JSON 응답을 Ollama /api/chat 호환 형태로 변환."""
        try:
            data = json.loads(stdout_text)
        except json.JSONDecodeError:
            return {
                "message": {"role": "assistant", "content": stdout_text.strip()},
                "done": True,
                "prompt_eval_count": 0,
                "eval_count": 0,
                "total_duration": 0,
            }

        if data.get("is_error"):
            err = data.get("result") or data.get("error", "unknown")
            raise ClaudeCLIError(f"claude 응답 오류: {err}")

        text = data.get("result", "")
        usage = data.get("usage") or {}
        in_tok = int(usage.get("input_tokens", 0) or 0) + int(usage.get("cache_creation_input_tokens", 0) or 0) + int(usage.get("cache_read_input_tokens", 0) or 0)
        out_tok = int(usage.get("output_tokens", 0) or 0)
        duration_ms = int(data.get("duration_ms", 0) or 0)

        return {
            "model": "claude-cli",
            "message": {"role": "assistant", "content": text},
            "done": True,
            "prompt_eval_count": in_tok,
            "eval_count": out_tok,
            "total_duration": duration_ms * 1_000_000,
            # 추가 메타 (raphael 토큰 통계에 비용 노출)
            "claude_meta": {
                "session_id": data.get("session_id"),
                "cost_usd": data.get("total_cost_usd"),
                "model_usage": data.get("modelUsage"),
            },
        }
