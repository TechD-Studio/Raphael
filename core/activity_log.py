"""활동 로그 — 에이전트/도구/세션 이벤트를 구조화(JSONL)로 기록.

다른 터미널/탭에서 실시간으로 진행 상황을 보기 위한 기반.

저장 위치: ~/.raphael/activity.jsonl (환경변수 RAPHAEL_ACTIVITY_LOG로 오버라이드)
각 라인은 JSON 객체:
  {"ts": "2026-04-15T08:10:00", "type": "tool_call", "agent": "coding",
   "session": "cli:main", "data": {...}}
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger


def log_path() -> Path:
    p = os.environ.get("RAPHAEL_ACTIVITY_LOG")
    if p:
        return Path(p).expanduser()
    return Path.home() / ".raphael" / "activity.jsonl"


@dataclass
class ActivityLogger:
    """에이전트 이벤트를 JSONL 파일에 추가하는 writer.

    기본적으로 on_tool_call/on_tool_result 훅과 결합해 사용.
    on_event가 지정되면 모든 이벤트를 콜백에도 전달 — 웹/봇 실시간 UI 갱신용.
    """

    session_id: str = "cli"
    agent: str = ""
    console: bool = False         # True면 stderr에 사람 읽기용 출력
    on_event: "any" = None        # Optional[Callable[[dict], None]] — 이벤트 구독

    # ── 공개 API ──────────────────────────────────────────

    def tool_call(self, call) -> None:
        self._emit("tool_call", {
            "name": call.name,
            "args": {k: v[:200] if isinstance(v, str) else v for k, v in call.args.items()},
        })

    def tool_result(self, result) -> None:
        self._emit("tool_result", {
            "name": result.name,
            "error": result.error,
            "output": result.output[:500] if isinstance(result.output, str) else str(result.output)[:500],
        })

    def user_message(self, text: str) -> None:
        self._emit("user_message", {"text": text[:500]})

    def assistant_message(self, text: str) -> None:
        self._emit("assistant_message", {"text": text[:500]})

    def note(self, text: str, **extra) -> None:
        """임의의 메모 이벤트."""
        self._emit("note", {"text": text, **extra})

    def model_call_start(self, model: str, messages_count: int, iteration: int = 1) -> None:
        self._emit("model_call_start", {
            "model": model,
            "messages": messages_count,
            "iteration": iteration,
        })

    def model_call_progress(self, elapsed_seconds: float) -> None:
        self._emit("model_call_progress", {"elapsed_seconds": round(elapsed_seconds, 1)})

    def model_call_end(self, model: str, duration_seconds: float, tokens: dict | None = None) -> None:
        self._emit("model_call_end", {
            "model": model,
            "duration_seconds": round(duration_seconds, 2),
            "tokens": tokens or {},
        })

    def token_chunk(self, text: str) -> None:
        """스트리밍 토큰 도착 (선택적 — 대량일 수 있으므로 기본 비활성)."""
        self._emit("token_chunk", {"text": text})

    def delegate_start(self, target: str, task: str, depth: int = 0) -> None:
        self._emit("delegate_start", {"target": target, "task": task[:200], "depth": depth})

    def delegate_end(self, target: str, depth: int = 0, error: bool = False) -> None:
        self._emit("delegate_end", {"target": target, "depth": depth, "error": error})

    # ── 내부 ─────────────────────────────────────────────

    def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        entry = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "type": event_type,
            "agent": self.agent,
            "session": self.session_id,
            "data": data,
        }
        path = log_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"활동 로그 쓰기 실패: {e}")

        if self.console:
            self._print_console(entry)

        if self.on_event is not None:
            try:
                self.on_event(entry)
            except Exception as e:
                logger.warning(f"on_event 콜백 오류: {e}")

    # ── 콘솔 렌더 상태 ────────────────────────────────────
    # 같은 thinking 줄을 캐리지 리턴(\r)으로 덮어쓰기 위한 상태
    _thinking_active: bool = False
    _last_render_len: int = 0

    DIM, GRAY, RESET = "\033[2m", "\033[90m", "\033[0m"

    @staticmethod
    def _visible_len(s: str) -> int:
        """ANSI 이스케이프를 제외한 표시 길이."""
        import re as _re
        return len(_re.sub(r"\033\[[0-9;]*m", "", s))

    def _clear_thinking_line(self) -> None:
        """현재 thinking 줄을 가시 영역만큼 덮어쓰고 캐리지 리턴."""
        if self._thinking_active and self._last_render_len > 0:
            # 충분한 폭으로 덮기 — 터미널 폭 80 가정
            pad = max(self._last_render_len, 80)
            print("\r" + " " * pad + "\r", end="", file=sys.stderr, flush=True)
        self._thinking_active = False
        self._last_render_len = 0

    def _render_thinking(self, model: str, elapsed: float | None = None, iteration: int = 1) -> None:
        elapsed_str = f" {elapsed}s" if elapsed else ""
        iter_str = f" (반복 {iteration})" if iteration > 1 else ""
        line = f"{self.DIM}🧠 thinking… {model}{elapsed_str}{iter_str}{self.RESET}"
        visible = self._visible_len(line)
        pad = max(0, self._last_render_len - visible)
        print(f"\r{line}{' ' * pad}", end="", file=sys.stderr, flush=True)
        self._thinking_active = True
        self._last_render_len = visible

    def _print_console(self, entry: dict) -> None:
        """사람이 읽기 좋은 형식으로 stderr에 출력. thinking 줄은 라이브 갱신."""
        t = entry["type"]
        data = entry["data"]

        if t == "model_call_start":
            self._clear_thinking_line()
            self._render_thinking(
                model=data.get("model", "?"),
                iteration=data.get("iteration", 1),
            )
            self._current_model = data.get("model", "?")
            self._current_iteration = data.get("iteration", 1)
        elif t == "model_call_progress":
            if self._thinking_active:
                self._render_thinking(
                    model=getattr(self, "_current_model", "?"),
                    elapsed=data.get("elapsed_seconds"),
                    iteration=getattr(self, "_current_iteration", 1),
                )
        elif t == "model_call_end":
            self._clear_thinking_line()
            tk = data.get("tokens") or {}
            tok_str = f" {self.GRAY}[{tk.get('prompt', 0)}+{tk.get('completion', 0)} tok]{self.RESET}" if tk else ""
            print(f"{self.DIM}⚡ {data['duration_seconds']}s{self.RESET}{tok_str}", file=sys.stderr, flush=True)
        elif t == "token_chunk":
            self._clear_thinking_line()
            print(data.get("text", ""), end="", file=sys.stderr, flush=True)
        elif t == "tool_call":
            self._clear_thinking_line()
            args_str = ", ".join(f"{k}={v!r}" for k, v in list(data.get("args", {}).items())[:2])
            print(f"{self.GRAY}🔧 {data['name']}({args_str[:100]}){self.RESET}", file=sys.stderr, flush=True)
        elif t == "tool_result":
            self._clear_thinking_line()
            icon = "✗" if data.get("error") else "✓"
            out = (data.get("output") or "")[:120].replace("\n", " ")
            print(f"{self.GRAY}{icon} {out}{self.RESET}", file=sys.stderr, flush=True)
        elif t == "note":
            self._clear_thinking_line()
            print(f"{self.GRAY}ℹ  {data.get('text', '')}{self.RESET}", file=sys.stderr, flush=True)

    # ── 에이전트에 연결 ───────────────────────────────────

    def attach(self, agent) -> None:
        """Agent의 on_tool_call / on_tool_result 훅에 연결한다."""
        self.agent = agent.name

        prev_call = agent.on_tool_call
        prev_result = agent.on_tool_result

        def on_call(c):
            self.tool_call(c)
            if prev_call:
                return prev_call(c)

        def on_result(r):
            self.tool_result(r)
            if prev_result:
                return prev_result(r)

        agent.on_tool_call = on_call
        agent.on_tool_result = on_result


# ── JSONL 파싱 (log tail용) ────────────────────────────────


def format_entry(entry: dict, color: bool = True) -> str:
    """엔트리를 사람이 읽을 수 있는 한 줄로 포맷."""
    t = entry.get("type", "?")
    data = entry.get("data", {})
    agent = entry.get("agent", "")
    session = entry.get("session", "")
    ts = entry.get("ts", "").split("T")[-1][:8] if entry.get("ts") else ""

    GREEN, RED, YELLOW, CYAN, DIM, RESET = (
        ("\033[32m", "\033[31m", "\033[33m", "\033[36m", "\033[2m", "\033[0m")
        if color else ("", "", "", "", "", "")
    )

    prefix = f"{DIM}{ts}{RESET} {CYAN}[{agent or '-'}/{session}]{RESET}"

    if t == "tool_call":
        args = data.get("args", {})
        args_str = ", ".join(f"{k}={v!r}" for k, v in list(args.items())[:3])
        return f"{prefix} 🔧 {YELLOW}{data.get('name', '?')}{RESET}({args_str[:160]})"
    if t == "tool_result":
        icon = f"{RED}✗{RESET}" if data.get("error") else f"{GREEN}✓{RESET}"
        out = (data.get("output") or "")[:160].replace("\n", " ")
        return f"{prefix} {icon} {data.get('name', '?')}: {out}"
    if t == "user_message":
        return f"{prefix} 🧑 {(data.get('text') or '')[:160]}"
    if t == "assistant_message":
        return f"{prefix} 🤖 {(data.get('text') or '')[:160]}"
    if t == "note":
        return f"{prefix} ℹ  {data.get('text', '')}"
    if t == "model_call_start":
        it = data.get("iteration", 1)
        it_str = f" (반복 {it})" if it > 1 else ""
        return f"{prefix} 🧠 thinking... {CYAN}{data.get('model', '?')}{RESET} msgs={data.get('messages', '?')}{it_str}"
    if t == "model_call_progress":
        return f"{prefix} {DIM}⏳ {data.get('elapsed_seconds', '?')}s elapsed{RESET}"
    if t == "model_call_end":
        tk = data.get("tokens") or {}
        tok = f" [+{tk.get('prompt', 0)}/+{tk.get('completion', 0)} tok]" if tk else ""
        return f"{prefix} ⚡ done in {GREEN}{data.get('duration_seconds', '?')}s{RESET}{tok}"
    if t == "token_chunk":
        return f"{prefix} {DIM}› {data.get('text', '')}{RESET}"
    return f"{prefix} {t}: {data}"
