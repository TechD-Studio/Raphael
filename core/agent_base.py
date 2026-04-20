"""에이전트 베이스 클래스 — 모든 에이전트가 상속해야 하는 공통 인터페이스."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

import asyncio

from core.model_router import ModelNotInstalledError, ModelRouter
from core.tool_runner import (
    execute_tool_call,
    format_results,
    parse_tool_calls,
    strip_tool_calls,
)
from tools.tool_registry import ToolRegistry


MAX_TOOL_ITERATIONS = 6

# 대화 압축 임계값 — 메시지 수가 이를 넘으면 과거를 요약으로 치환
COMPACT_THRESHOLD = 30
# 최근 N개의 메시지는 원문 유지
KEEP_RECENT = 10

# 위험한 도구 (실행 전 승인 필요)
DANGEROUS_TOOLS = frozenset({"execute", "python", "delete_file"})


@dataclass
class AgentBase(ABC):
    """에이전트 공통 베이스.

    모든 에이전트는 이 클래스를 상속하고 `handle` 메서드를 구현한다.
    """

    name: str
    description: str
    router: ModelRouter
    tools: list[str] = field(default_factory=list)
    system_prompt: str = ""
    tool_registry: ToolRegistry | None = None
    # 위험한 도구 호출 시 승인 콜백 (None이면 자동 허용). 콜백은 (tool_name, args) -> bool.
    approval_callback: callable | None = None
    # 도구 이벤트 훅: on_tool_call(call), on_tool_result(result). 동기/비동기 모두 OK.
    on_tool_call: callable | None = None
    on_tool_result: callable | None = None
    # 활동 로거 (Orchestrator가 주입). 모델 호출 시작/진행/종료 이벤트 기록.
    activity: "any" = None
    _conversation: list[dict] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        if self.system_prompt:
            self._conversation = [{"role": "system", "content": self.system_prompt}]

    # ── 대화 관리 ──────────────────────────────────────────

    def add_message(self, role: str, content: str) -> None:
        """대화 히스토리에 메시지를 추가한다."""
        self._conversation.append({"role": role, "content": content})

    def get_conversation(self) -> list[dict]:
        return list(self._conversation)

    def clear_conversation(self) -> None:
        """대화 히스토리를 초기화한다. 시스템 프롬프트는 유지."""
        self._conversation = [
            msg for msg in self._conversation if msg["role"] == "system"
        ]

    # ── 모델 호출 ──────────────────────────────────────────

    async def _call_model(self, user_input: str, **kwargs) -> str:
        """사용자 입력을 모델에 보내고 응답 텍스트를 반환한다.

        ReAct 루프 + 대화 압축 + 위험 도구 승인을 포함한다.
        """
        import time as _time

        self.add_message("user", user_input)
        # 에스컬레이션은 세션 sticky — 이미 승격됐으면 플래그 유지 (재하향 방지)
        if not getattr(self, "_escalated_sticky", False):
            self._escalated = False
        # 이번 턴에 실제로 도구가 몇 번 실행됐는지 — _self_reflect의 false-positive 방지용
        self._tools_used_this_turn = 0
        await self._maybe_compact()

        failure_hint = self._load_failure_patterns()
        if failure_hint:
            self._conversation = [
                m for m in self._conversation
                if not (m.get("role") == "system" and "## 과거 실패 사례" in m.get("content", ""))
            ]
            insert_at = 1 if self._conversation and self._conversation[0]["role"] == "system" else 0
            self._conversation.insert(insert_at, {"role": "system", "content": failure_hint})

        # kwargs에서 verbose/stream 플래그 추출 — Orchestrator에서 전달
        stream_tokens = kwargs.pop("stream_tokens", False)

        for iteration in range(MAX_TOOL_ITERATIONS):
            # 모델 호출 시작 이벤트 + 경과 타이머 + 토큰 통계 기록
            tokens_before = self.router.get_token_stats().get(
                self.router.current_model_name, {"prompt": 0, "completion": 0}
            )
            if self.activity is not None:
                self.activity.model_call_start(
                    model=self.router.current_model_name,
                    messages_count=len(self._conversation),
                    iteration=iteration + 1,
                )

            start = _time.monotonic()

            async def _elapsed_ticker():
                # 5초 간격으로 elapsed 이벤트
                while True:
                    await asyncio.sleep(5)
                    if self.activity is not None:
                        self.activity.model_call_progress(_time.monotonic() - start)

            ticker = asyncio.create_task(_elapsed_ticker())

            try:
                if stream_tokens:
                    assistant_msg = await self._stream_chat(**kwargs)
                    result = {"message": {"content": assistant_msg}}
                else:
                    result = await self.router.chat(self._conversation, **kwargs)
                    assistant_msg = result["message"]["content"]
            except ModelNotInstalledError as e:
                ticker.cancel()
                logger.warning(f"[{self.name}] {e}")
                # Claude 실패 시 gemma4로 폴백 시도
                try:
                    from config.settings import get_settings, get_model_config
                    cur = get_model_config(self.router.current_key)
                    if cur.get("provider") == "claude_cli":
                        ladder = get_settings().get("models", {}).get("escalation_ladder", [])
                        fallback = next(
                            (k for k in reversed(ladder)
                             if get_model_config(k).get("provider") != "claude_cli"),
                            None,
                        )
                        if fallback:
                            logger.info(f"[{self.name}] Claude 실패 → {fallback}로 폴백")
                            self.router.switch_model(fallback)
                            continue  # ReAct 루프 재시도
                except Exception:
                    pass
                return f"⚠ {e}"
            finally:
                ticker.cancel()
                try:
                    await ticker
                except (asyncio.CancelledError, Exception):
                    pass

            duration = _time.monotonic() - start
            if self.activity is not None:
                tokens_after = self.router.get_token_stats().get(
                    self.router.current_model_name, {"prompt": 0, "completion": 0}
                )
                diff = {
                    "prompt": tokens_after["prompt"] - tokens_before["prompt"],
                    "completion": tokens_after["completion"] - tokens_before["completion"],
                }
                self.activity.model_call_end(
                    model=self.router.current_model_name,
                    duration_seconds=duration,
                    tokens=diff,
                )

            self.add_message("assistant", assistant_msg)

            # tool 호출 파싱
            if not self.tool_registry:
                return assistant_msg

            calls = parse_tool_calls(assistant_msg)
            if not calls:
                # 도구 호출이 전혀 없는 경우라도 (혹시) 태그가 텍스트로 남아있으면 정제
                cleaned = strip_tool_calls(assistant_msg)
                final = cleaned if cleaned else assistant_msg
                # 빈 응답 방어 — 현재 모델이 빈 응답이면 상위 모델로 자동 에스컬레이션 (한 번)
                if not final.strip() and not getattr(self, "_escalated", False):
                    self._escalated = True
                    self._escalated_sticky = True  # 이후 턴에도 유지
                    # 에스컬레이션 사다리 — settings.yaml의 models.escalation_ladder 사용.
                    # 기본: gemma 내부만 (프로젝트 목표: 로컬 gemma4 한계 탐구).
                    from config.settings import get_settings
                    _s = get_settings()
                    ladder = (_s.get("models", {}).get("escalation_ladder")
                              or ["gemma4-e2b", "gemma4-e4b"])
                    nxt = None
                    try:
                        cur_idx = ladder.index(self.router.current_key)
                    except ValueError:
                        cur_idx = -1
                    for cand in ladder[cur_idx + 1:]:
                        # claude_cli provider는 CLI 설치 여부 확인
                        try:
                            from config.settings import get_model_config
                            cfg = get_model_config(cand)
                            if cfg.get("provider") == "claude_cli":
                                from core.claude_provider import ClaudeCodeProvider
                                if not ClaudeCodeProvider().is_available():
                                    logger.debug(f"에스컬레이션 스킵: {cand} (claude CLI 미설치)")
                                    continue
                        except Exception:
                            continue
                        nxt = cand
                        break
                    if nxt:
                        logger.warning(
                            f"[{self.name}] 빈 응답 → 상위 모델 자동 전환: "
                            f"{self.router.current_key} → {nxt}"
                        )
                        # 마지막 assistant 빈 메시지 제거 후 재시도
                        if self._conversation and self._conversation[-1]["role"] == "assistant":
                            self._conversation.pop()
                        saved = self.router.current_key
                        try:
                            self.router.switch_model(nxt)
                            # 현재 iteration 재시도를 위해 user 입력 재주입 없이 계속
                            continue
                        except Exception as e:
                            logger.warning(f"에스컬레이션 실패: {e}")
                            self.router.switch_model(saved)
                if not final.strip():
                    last_tr = next(
                        (m["content"] for m in reversed(self._conversation)
                         if m["role"] == "user" and m["content"].startswith("<tool_results>")),
                        None,
                    )
                    if last_tr:
                        return (
                            f"⚠ 현재 모델({self.router.current_model_name})이 후속 응답을 생성하지 못했습니다.\n"
                            f"수집된 결과:\n{last_tr}"
                        )
                    return "⚠ 모델이 빈 응답을 반환했습니다. `/model` 로 상위 모델 전환하거나 auto-route 규칙을 조정하세요."
                final = await self._self_reflect(user_input, final)
                return final

            # 필터: 에이전트에 바인딩된 도구만 허용
            calls = [c for c in calls if self._is_tool_allowed(c.name)]
            if not calls:
                # 허용 도구가 없으면 태그를 그대로 보여주지 말고 정제
                cleaned = strip_tool_calls(assistant_msg)
                return cleaned if cleaned else assistant_msg

            # 도구 실행 — 위험 도구는 승인 콜백 체크
            logger.info(f"[{self.name}] 도구 {len(calls)}개 실행 (반복 {iteration + 1})")
            self._tools_used_this_turn += len(calls)
            results = []
            for c in calls:
                # on_tool_call 훅
                if self.on_tool_call is not None:
                    try:
                        maybe = self.on_tool_call(c)
                        if asyncio.iscoroutine(maybe):
                            await maybe
                    except Exception as e:
                        logger.warning(f"on_tool_call 훅 오류: {e}")

                if c.name in DANGEROUS_TOOLS and self.approval_callback is not None:
                    try:
                        approved = self.approval_callback(c.name, c.args)
                        if asyncio.iscoroutine(approved):
                            approved = await approved
                    except Exception as e:
                        logger.error(f"승인 콜백 오류: {e}")
                        approved = False
                    if not approved:
                        from core.tool_runner import ToolResult
                        results.append(ToolResult(
                            name=c.name,
                            args=c.args,
                            output="사용자가 실행을 거부했습니다.",
                            error=True,
                        ))
                        continue
                r = await execute_tool_call(c, self.tool_registry)
                results.append(r)
                # on_tool_result 훅
                if self.on_tool_result is not None:
                    try:
                        maybe = self.on_tool_result(r)
                        if asyncio.iscoroutine(maybe):
                            await maybe
                    except Exception as e:
                        logger.warning(f"on_tool_result 훅 오류: {e}")

            # 결과를 user 메시지로 피드백
            feedback = format_results(results)
            self.add_message("user", f"<tool_results>\n{feedback}\n</tool_results>")

            # 빈 content 감지 시 모델에게 강력한 수정 지시 주입 (에스컬레이션 전에 먼저 재시도)
            if any("ESCALATE_EMPTY_CONTENT" in (r.output or "") for r in results):
                empty_paths = [
                    r.args.get("path", "?") for r in results
                    if "ESCALATE_EMPTY_CONTENT" in (r.output or "")
                ]
                self.add_message(
                    "user",
                    "🚨 방금 write_file 호출에서 <arg name=\"content\"> 본문이 비어 있었습니다. "
                    f"파일 {empty_paths} 은 아직 비어 있습니다.\n"
                    "즉시 **같은 응답 안**에서 write_file을 다시 호출하세요. "
                    "이번에는 <arg name=\"content\"> 태그 사이에 **실제 코드/문서 본문**을 그대로 포함하세요. "
                    "설명 문장 없이 tool 블록만 출력하세요.",
                )

            # 약한 모델이 content 없이 write_file을 반복 호출하면 자동 에스컬레이션
            # (설정에 claude/상위 모델이 포함되어 있을 때만 작동. 기본은 gemma 내부만.)
            self._empty_write_count = getattr(self, "_empty_write_count", 0)
            empty_this_round = sum(1 for r in results if "ESCALATE_EMPTY_CONTENT" in (r.output or ""))
            if empty_this_round > 0:
                self._empty_write_count += empty_this_round
            else:
                self._empty_write_count = 0
            # 2번 누적 빈 content → 즉시 에스컬레이션
            logger.debug(f"[{self.name}] empty_write_count={self._empty_write_count}, escalated={getattr(self, '_escalated', False)}")
            if self._empty_write_count >= 2 and not getattr(self, "_escalated", False):
                if True:
                    from config.settings import get_settings as _gs
                    escalation_ladder = (_gs().get("models", {}).get("escalation_ladder")
                                         or ["gemma4-e2b", "gemma4-e4b"])
                    try:
                        cur_idx = escalation_ladder.index(self.router.current_key)
                    except ValueError:
                        cur_idx = -1
                    for cand in escalation_ladder[cur_idx + 1:]:
                        try:
                            from config.settings import get_model_config
                            cfg = get_model_config(cand)
                            if cfg.get("provider") == "claude_cli":
                                from core.claude_provider import ClaudeCodeProvider
                                if not ClaudeCodeProvider().is_available():
                                    continue
                            logger.warning(
                                f"[{self.name}] 빈 content write_file 감지 → 에스컬레이션: "
                                f"{self.router.current_key} → {cand}"
                            )
                            self.router.switch_model(cand)
                            self._escalated = True
                            self._escalated_sticky = True
                            break
                        except Exception:
                            continue

        # 반복 상한 도달 — 실패 케이스 저장 후 마지막 응답 반환
        logger.warning(f"[{self.name}] 도구 호출 최대 반복({MAX_TOOL_ITERATIONS}) 도달")
        try:
            self._save_failure("max_iterations", user_input)
        except Exception as e:
            logger.debug(f"실패 로그 저장 실패: {e}")
        tail = strip_tool_calls(assistant_msg) or assistant_msg
        return f"⚠ 최대 반복({MAX_TOOL_ITERATIONS}) 도달 — 동일 실수 반복. 마지막 응답:\n{tail}"

    def _save_failure(self, reason: str, user_input: str) -> None:
        """실패 케이스를 ~/.raphael/failures/ 에 JSON으로 누적 저장."""
        import json
        from datetime import datetime
        from pathlib import Path
        d = Path.home() / ".raphael" / "failures"
        d.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = d / f"{ts}_{self.name}_{reason}.json"
        payload = {
            "agent": self.name,
            "model": self.router.current_key,
            "reason": reason,
            "user_input": user_input,
            "conversation": self._conversation[-10:],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"실패 케이스 저장: {path}")

    # ── 반사적 사고 ──────────────────────────────────────

    async def _self_reflect(self, user_input: str, response: str) -> str:
        """응답 품질 자체 평가. 부족하면 보완 시도. Claude/짧은 대화는 스킵."""
        if len(response.strip()) < 10:
            return response
        if len(user_input.strip()) < 30 and len(response.strip()) < 200:
            return response
        # 이번 턴에 도구가 실제로 실행됐다면 — 리플렉터는 텍스트만 보므로 "도구 썼어야 했는데
        # 안 썼네" 식의 false-positive를 거의 확실히 낸다. 일감은 이미 끝난 상태.
        if getattr(self, "_tools_used_this_turn", 0) > 0:
            return response
        try:
            from config.settings import get_model_config
            if get_model_config(self.router.current_key).get("provider") == "claude_cli":
                return response
        except Exception:
            pass
        if any(kw in response for kw in ("⚠ 최대 반복", "⚠ 모델이 빈 응답")):
            return response
        reflect_prompt = (
            "방금 내가 한 답변을 점검한다:\n"
            f"사용자 질문: {user_input[:300]}\n"
            f"내 답변: {response[:500]}\n\n"
            "다음 중 해당되는 것이 있으면 '보완필요: [구체적 내용]'으로 답하라:\n"
            "1. 사용자가 구체적 정보(가격, 코드, 수치)를 요청했는데 모호한 조언만 했다\n"
            "2. 도구를 사용할 수 있었는데 사용하지 않았다\n"
            "3. 질문에 직접 답하지 않고 관련 없는 얘기를 했다\n"
            "문제없으면 'OK'라고만 답하라."
        )
        try:
            r = await self.router.chat(
                [{"role": "system", "content": "짧게 답하라."},
                 {"role": "user", "content": reflect_prompt}],
                retry_on_empty=False,
            )
            verdict = r.get("message", {}).get("content", "").strip()
            if verdict.startswith("보완필요"):
                logger.info(f"[{self.name}] 자체 검토: 보완 시도 — {verdict[:100]}")
                supplement_prompt = (
                    f"방금 답변에 부족한 점이 발견되었다: {verdict}\n"
                    f"원래 질문: {user_input[:300]}\n"
                    "도구를 사용해서라도 부족한 부분을 보완하라."
                )
                self.add_message("user", supplement_prompt)
                supplement = await self._call_model(supplement_prompt)
                # supplement 도 대화에 assistant 로 남겨야 다음 턴에 orphan user 로 재처리되지 않는다.
                self.add_message("assistant", supplement)
                return f"{response}\n\n---\n\n💡 **보완**\n{supplement}"
        except Exception as e:
            logger.debug(f"자체 검토 실패 (무시): {e}")
        return response

    @staticmethod
    def _load_failure_patterns() -> str:
        """최근 실패 패턴에서 교훈을 추출해 프롬프트에 주입할 텍스트 생성."""
        import json
        from pathlib import Path
        d = Path.home() / ".raphael" / "failures"
        if not d.exists():
            return ""
        files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:5]
        if not files:
            return ""
        patterns: list[str] = []
        for f in files:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                reason = data.get("reason", "unknown")
                agent = data.get("agent", "")
                inp = data.get("user_input", "")[:80]
                patterns.append(f"- [{agent}] {reason}: {inp}")
            except Exception:
                pass
        if not patterns:
            return ""
        return (
            "\n## 과거 실패 사례 (같은 실수 반복 금지)\n"
            + "\n".join(patterns)
            + "\n위 패턴을 피하고 다른 접근법을 시도하라.\n"
        )

    # 카테고리 → 실제 도구 이름 매핑 (모듈 레벨에서도 참조)
    _TOOL_MAPPING = {
        "file_reader": {"read_file"},
        "file_writer": {"write_file", "append_file", "delete_file", "mkdir"},
        "executor": {"execute", "python"},
        "web_search": {"web_search"},
        "rag_search": set(),
        "delegate": {"delegate"},
        "git_tool": {"git_status", "git_diff", "git_log", "git_commit"},
        "browser_tool": {"open_in_browser"},
        "profile": {"remember", "forget"},
        "screenshot_tool": {"screenshot"},
        "clipboard_tool": {"clipboard_read", "clipboard_write"},
        "mcp": {"mcp_call"},
        "notification_tool": {"notify"},
        "calendar_tool": {"calendar_add"},
        "email_tool": {"email_inbox", "email_send"},
        "converter_tool": {"convert_md_to_html", "convert_md_to_pdf", "convert_csv_to_chart", "image_resize"},
        "voice": {"speak"},
        "fetch_tool": {"fetch_url"},
        "image_gen": {"generate_image"},
    }

    def _is_tool_allowed(self, tool_name: str) -> bool:
        """도구 허용 검사.

        self.tools가 비어있으면 = 페르소나 에이전트 → 전체 도구 허용.
        self.tools가 지정되어 있으면 = 제한 에이전트 → 매핑된 도구만 허용.
        """
        # 페르소나 에이전트: 도구 카테고리 미지정 → 전체 허용
        if not self.tools:
            return True
        allowed: set[str] = set()
        for t in self.tools:
            allowed |= self._TOOL_MAPPING.get(t, set())
        return tool_name in allowed

    # ── 추상 메서드 ────────────────────────────────────────

    @abstractmethod
    async def handle(self, user_input: str, **kwargs) -> str:
        """사용자 입력을 처리하고 응답을 반환한다. 각 에이전트가 구현."""
        ...

    # ── 툴 바인딩 ──────────────────────────────────────────

    def bind_tools(self, tool_names: list[str]) -> None:
        """이 에이전트가 사용할 수 있는 툴 목록을 설정한다."""
        self.tools = tool_names
        logger.debug(f"[{self.name}] tools bound: {tool_names}")

    def has_tool(self, tool_name: str) -> bool:
        return tool_name in self.tools

    # ── 스트리밍 ──────────────────────────────────────────

    async def _stream_chat(self, **kwargs) -> str:
        """스트리밍 방식으로 모델 응답을 받고 토큰을 activity로 전달한다.

        사용자에게 보이는 토큰 스트림에서는 <tool>...</tool> 블록을 제외한다
        (도구 호출은 별도의 tool_call/tool_result 이벤트로 표시되므로 중복 방지).
        ReAct 루프의 도구 파싱은 필터링 전 원본 텍스트로 수행한다.
        """
        from core.tool_runner import StreamingTagFilter

        parts: list[str] = []
        tag_filter = StreamingTagFilter()

        async for chunk in self.router.chat_stream(self._conversation, **kwargs):
            piece = chunk.get("message", {}).get("content", "")
            if piece:
                parts.append(piece)  # 원본 누적 (도구 파싱용)
                visible = tag_filter.feed(piece)
                if visible and self.activity is not None:
                    self.activity.token_chunk(visible)
            if chunk.get("done"):
                break

        # 남은 버퍼 flush
        tail = tag_filter.flush()
        if tail and self.activity is not None:
            self.activity.token_chunk(tail)

        # 스트리밍 완료 후 개행 (console 표시 깔끔하게)
        if self.activity is not None and self.activity.console:
            import sys as _sys
            print("", file=_sys.stderr)

        return "".join(parts)

    # ── 대화 압축 ──────────────────────────────────────────

    async def _maybe_compact(self) -> None:
        """대화가 임계값을 넘으면 과거를 LLM으로 요약해 하나의 system 메시지로 교체한다."""
        if len(self._conversation) < COMPACT_THRESHOLD:
            return

        # 맨 앞 system, 뒷 KEEP_RECENT 개는 유지. 중간은 요약 대상.
        system_msgs = [m for m in self._conversation if m["role"] == "system"]
        non_system = [m for m in self._conversation if m["role"] != "system"]
        if len(non_system) <= KEEP_RECENT:
            return

        to_compact = non_system[:-KEEP_RECENT]
        keep = non_system[-KEEP_RECENT:]

        # 요약 요청 프롬프트
        transcript = "\n".join(
            f"{m['role']}: {m['content'][:400]}"
            for m in to_compact
        )
        summary_prompt = [
            {"role": "system", "content": "이 대화의 핵심 사실과 결정을 간결한 한국어로 요약하라. 5줄 이하."},
            {"role": "user", "content": transcript},
        ]

        try:
            result = await self.router.chat(summary_prompt)
            summary = result["message"]["content"].strip()
        except Exception as e:
            logger.warning(f"대화 요약 실패 — 압축 건너뜀: {e}")
            return

        compact_note = {
            "role": "system",
            "content": f"[이전 대화 요약 — {len(to_compact)}개 메시지]\n{summary}",
        }

        self._conversation = system_msgs + [compact_note] + keep
        logger.info(f"[{self.name}] 대화 압축: {len(non_system)} → {len(keep) + 1}")

    # ── 내보내기 ──────────────────────────────────────────

    def export_markdown(self) -> str:
        """대화를 마크다운 형식으로 내보낸다."""
        lines = [f"# {self.name} 에이전트 대화 기록\n"]
        for m in self._conversation:
            role = m["role"]
            content = m["content"]
            if role == "system":
                lines.append(f"> **system**: {content[:200]}...")
            elif role == "user":
                lines.append(f"\n**🧑 User**\n\n{content}\n")
            elif role == "assistant":
                lines.append(f"\n**🤖 {self.name}**\n\n{content}\n")
        return "\n".join(lines)

    def export_json(self) -> list[dict]:
        """대화를 JSON-serializable 리스트로 내보낸다."""
        return [dict(m) for m in self._conversation]

    # ── 메타 ───────────────────────────────────────────────

    def info(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "tools": self.tools,
            "model": self.router.current_key,
            "conversation_length": len(self._conversation),
        }
