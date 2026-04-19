"""오케스트레이터 — 에이전트 등록/조회/라우팅, 태스크 분배.

세션 격리: `session_id`를 route()에 주면 해당 세션만의 대화 히스토리를 유지한다.
여러 사용자가 동시에 접속해도 대화가 섞이지 않는다.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from loguru import logger

from core.activity_log import ActivityLogger
from core.agent_base import AgentBase
from core.input_guard import InputSource, validate_input
from core.model_router import ModelRouter


@dataclass
class Orchestrator:
    """에이전트를 관리하고, 사용자 요청을 적절한 에이전트에 라우팅한다."""

    router: ModelRouter
    _agents: dict[str, AgentBase] = field(default_factory=dict, repr=False)
    _default_agent: str = ""
    # 세션별 대화 히스토리: {(session_id, agent_name): conversation_list}
    _sessions: dict[tuple[str, str], list[dict]] = field(default_factory=dict, repr=False)
    _persist_loaded: bool = field(default=False, repr=False)

    # ── 디스크 영속화 ──────────────────────────────────────

    @staticmethod
    def _sessions_dir():
        import os
        from pathlib import Path
        override = os.environ.get("RAPHAEL_SESSIONS_DIR")
        d = Path(override) if override else Path.home() / ".raphael" / "sessions"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _session_file(self, session_id: str, agent_name: str):
        import re
        safe_sid = re.sub(r"[^A-Za-z0-9_\-]", "_", session_id)
        safe_an = re.sub(r"[^A-Za-z0-9_\-]", "_", agent_name)
        return self._sessions_dir() / f"{safe_sid}__{safe_an}.json"

    def _persist_session(self, session_id: str, agent_name: str, conversation: list[dict]) -> None:
        import json
        try:
            p = self._session_file(session_id, agent_name)
            p.write_text(json.dumps(conversation, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.debug(f"세션 저장 실패: {e}")

    def _load_persisted(self, session_id: str, agent_name: str) -> list[dict] | None:
        import json
        p = self._session_file(session_id, agent_name)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"세션 복원 실패 ({p.name}): {e}")
            return None

    def list_persisted_sessions(self) -> list[dict]:
        """저장된 세션 목록 (id, agent, 마지막 수정)."""
        out = []
        for p in sorted(self._sessions_dir().glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            stem = p.stem
            if "__" in stem:
                sid, aname = stem.split("__", 1)
                out.append({"session_id": sid, "agent": aname, "mtime": p.stat().st_mtime, "path": str(p)})
        return out

    def delete_persisted_session(self, session_id: str) -> int:
        cnt = 0
        for p in self._sessions_dir().glob(f"{session_id}__*.json"):
            try:
                p.unlink()
                cnt += 1
            except Exception:
                pass
        return cnt

    # ── 에이전트 등록 ──────────────────────────────────────

    def register(self, agent: AgentBase) -> None:
        """에이전트를 등록한다."""
        self._agents[agent.name] = agent
        logger.info(f"에이전트 등록: {agent.name}")
        if not self._default_agent:
            self._default_agent = agent.name

    def set_default(self, agent_name: str) -> None:
        """기본 에이전트를 설정한다."""
        if agent_name not in self._agents:
            raise ValueError(f"Unknown agent: {agent_name}")
        self._default_agent = agent_name

    # ── 에이전트 조회 ──────────────────────────────────────

    def get_agent(self, name: str) -> AgentBase:
        if name not in self._agents:
            raise ValueError(f"Unknown agent: {name}. Available: {list(self._agents.keys())}")
        return self._agents[name]

    def list_agents(self) -> list[dict]:
        return [agent.info() for agent in self._agents.values()]

    @property
    def default_agent(self) -> AgentBase | None:
        if self._default_agent:
            return self._agents[self._default_agent]
        return None

    # ── 요청 처리 ──────────────────────────────────────────

    async def route(
        self,
        user_input: str,
        agent_name: str | None = None,
        source: InputSource = InputSource.CLI,
        session_id: str | None = None,
        **kwargs,
    ) -> str:
        """사용자 입력을 에이전트에 라우팅하여 처리한다.

        session_id가 주어지면 해당 세션의 대화 히스토리를 에이전트에 주입하고,
        처리 후 업데이트된 히스토리를 저장한다. session_id가 None이면 단일 전역 세션.
        """
        sanitized, warnings = validate_input(user_input, source)
        for w in warnings:
            logger.warning(w)

        if agent_name:
            agent = self.get_agent(agent_name)
        elif self._default_agent:
            agent = self._agents[self._default_agent]
        else:
            raise RuntimeError("등록된 에이전트가 없습니다.")

        if not agent_name or agent_name in ("main", "coder", "coding"):
            routed = self._auto_complexity_route(sanitized, agent)
            if routed is not None:
                agent = routed

        # Auto-routing — 매 호출마다 평가, 응답 끝나면 모델 원복
        # 단, 사용자가 명시적으로 Claude 등 비-Ollama 모델을 선택했으면 auto-route 스킵
        _saved_model_for_route = None
        _user_chose_provider = False
        try:
            from config.settings import get_model_config
            cur_cfg = get_model_config(self.router.current_key)
            _user_chose_provider = cur_cfg.get("provider") == "claude_cli"
        except Exception:
            pass

        if not _user_chose_provider:
            try:
                from core.router_strategy import RouterStrategy, TaskContext
                strat = RouterStrategy()
                if strat.strategy == "auto":
                    ctx = TaskContext(
                        user_input=sanitized,
                        agent=agent.name,
                        messages_count=len(agent._conversation),
                    )
                    decision = strat.decide(ctx)
                    if decision.agent_name and decision.agent_name != agent.name:
                        try:
                            new_agent = self.get_agent(decision.agent_name)
                            logger.info(f"auto-route 에이전트: {agent.name} → {new_agent.name} (rule={decision.rule_name})")
                            agent = new_agent
                        except ValueError:
                            pass
                    if decision.model_key and decision.model_key != self.router.current_key:
                        try:
                            _saved_model_for_route = self.router.current_key
                            self.router.switch_model(decision.model_key)
                            logger.info(f"auto-route 모델: {_saved_model_for_route} → {decision.model_key} (rule={decision.rule_name})")
                        except ValueError:
                            _saved_model_for_route = None
            except Exception as e:
                logger.debug(f"auto-routing 스킵: {e}")
        else:
            logger.info(f"사용자 선택 모델({self.router.current_key}) 유지 — auto-route 스킵")

        logger.debug(
            f"[{agent.name}] 요청 처리 (source={source.value}, session={session_id}): "
            f"{sanitized[:80]}..."
        )

        # 활동 로그 연결
        verbose = kwargs.pop("verbose", False)               # stderr에 사람 읽기용 출력
        stream_tokens = kwargs.pop("stream_tokens", None)    # None이면 verbose 따라감
        activity_callback = kwargs.pop("activity_callback", None)  # 외부 구독자

        if stream_tokens is None:
            stream_tokens = verbose or (activity_callback is not None)

        act_session = session_id or f"{source.value}:main"
        activity = ActivityLogger(
            session_id=act_session,
            console=verbose,
            on_event=activity_callback,
        )
        activity.attach(agent)
        activity.user_message(sanitized)
        agent.activity = activity

        if stream_tokens:
            kwargs["stream_tokens"] = True

        # 세션 격리: 세션별 conversation을 에이전트에 로드
        if session_id is not None:
            key = (session_id, agent.name)
            saved = self._sessions.get(key)
            if saved is None:
                # 메모리에 없으면 디스크에서 복원 시도
                disk = self._load_persisted(session_id, agent.name)
                if disk is not None:
                    saved = disk
                    self._sessions[key] = copy.deepcopy(disk)
                    logger.info(f"세션 복원: {session_id}/{agent.name} ({len(disk)}개 메시지)")
            if saved is not None:
                agent._conversation = copy.deepcopy(saved)
            else:
                agent.clear_conversation()

        # 현재 날짜/시간 자동 주입 (매 호출마다 갱신)
        try:
            from datetime import datetime
            now = datetime.now()
            date_msg = f"## 현재 시각\n{now.strftime('%Y-%m-%d %H:%M %A')} (이 정보가 필요한 질문에는 이 값을 사용하세요)"
            agent._conversation = [
                m for m in agent._conversation
                if not (m.get("role") == "system" and m.get("content", "").startswith("## 현재 시각"))
            ]
            insert_at = 1 if agent._conversation and agent._conversation[0]["role"] == "system" else 0
            agent._conversation.insert(insert_at, {"role": "system", "content": date_msg})
        except Exception as e:
            logger.debug(f"날짜 주입 실패: {e}")

        # 사용자 프로필 facts 자동 주입 (대화 시작 시 한 번)
        try:
            from core.profile import Profile
            addendum = Profile.load().to_system_addendum()
            if addendum and not any(
                m.get("role") == "system" and "## 사용자 프로필" in m.get("content", "")
                for m in agent._conversation
            ):
                insert_at = 1 if agent._conversation and agent._conversation[0]["role"] == "system" else 0
                agent._conversation.insert(insert_at, {"role": "system", "content": addendum.strip()})
        except Exception as e:
            logger.debug(f"profile 주입 실패: {e}")

        # main 에이전트에 활성 전문가 카탈로그 자동 주입
        try:
            if agent.name == "main":
                from core.agent_definitions import list_definitions, load_active_agents
                active = load_active_agents()
                catalog_lines = ["[AVAILABLE AGENTS]"]
                for d in list_definitions():
                    if d.name == "main" or d.name not in active:
                        continue
                    tools = ", ".join(d.tools) if d.tools else "(없음)"
                    catalog_lines.append(f"- **{d.name}**: {d.description} (tools: {tools})")
                catalog = "\n".join(catalog_lines) if len(catalog_lines) > 1 else "[AVAILABLE AGENTS]\n(활성화된 전문가 없음)"
                # 매 호출마다 갱신 — 기존 카탈로그 메시지 제거 후 재주입
                agent._conversation = [
                    m for m in agent._conversation
                    if not (m.get("role") == "system" and m.get("content", "").startswith("[AVAILABLE AGENTS]"))
                ]
                insert_at = 1 if agent._conversation and agent._conversation[0]["role"] == "system" else 0
                agent._conversation.insert(insert_at, {"role": "system", "content": catalog})
        except Exception as e:
            logger.debug(f"main 카탈로그 주입 실패: {e}")

        try:
            from config.settings import get_settings
            custom = (get_settings().get("tools") or {}).get("custom_instructions", "").strip()
            if custom:
                agent._conversation = [
                    m for m in agent._conversation
                    if not (m.get("role") == "system" and m.get("content", "").startswith("## 사용자 커스텀 지시문"))
                ]
                insert_at = 1 if agent._conversation and agent._conversation[0]["role"] == "system" else 0
                agent._conversation.insert(insert_at, {
                    "role": "system",
                    "content": f"## 사용자 커스텀 지시문 (최우선 준수)\n{custom}",
                })
        except Exception as e:
            logger.debug(f"커스텀 지시문 주입 실패: {e}")

        try:
            from core.memory import build_memory_context
            mem = build_memory_context()
            if mem:
                agent._conversation = [
                    m for m in agent._conversation
                    if not (m.get("role") == "system" and m.get("content", "").startswith("## 기억"))
                ]
                insert_at = 1 if agent._conversation and agent._conversation[0]["role"] == "system" else 0
                agent._conversation.insert(insert_at, {
                    "role": "system",
                    "content": f"## 기억 (프로젝트 컨텍스트 + 오늘 작업 + 성공 패턴)\n{mem}",
                })
        except Exception as e:
            logger.debug(f"기억 주입 실패: {e}")

        try:
            response = await agent.handle(sanitized, **kwargs)
            activity.assistant_message(response)

            if self._should_auto_review(agent, sanitized, response):
                review = await self._run_auto_review(agent, sanitized, response, activity, **kwargs)
                if review:
                    response = f"{response}\n\n---\n\n🔍 **자동 검토**\n{review}"

            try:
                from core.memory import (
                    append_daily_log, summarize_session_for_log,
                    auto_extract_decisions, append_project_decision,
                )
                log_entry = summarize_session_for_log(
                    sanitized, response, agent.name, self.router.current_model_name,
                )
                append_daily_log(log_entry)
                for d in auto_extract_decisions(sanitized, response):
                    append_project_decision(d)
            except Exception as e:
                logger.debug(f"기억 기록 실패: {e}")
        finally:
            if session_id is not None:
                self._sessions[(session_id, agent.name)] = copy.deepcopy(agent._conversation)
                # 매 턴 디스크에 영속화 — 세션 종료/크래시 이후에도 복원 가능
                self._persist_session(session_id, agent.name, agent._conversation)
            agent.activity = None
            # auto-route로 모델 임시 전환했다면 원복
            # 단, handle() 중 에스컬레이션 또는 사용자 명시 선택 시 원복 안 함
            escalated = getattr(agent, "_escalated", False)
            if _saved_model_for_route and not escalated:
                try:
                    self.router.switch_model(_saved_model_for_route)
                except Exception:
                    pass

        if warnings:
            banner = "⚠ 외부 콘텐츠 보안 경고 (아래 패턴이 감지되어 무력화되었습니다):\n"
            banner += "\n".join(f"  - {w}" for w in warnings)
            response = f"{banner}\n\n---\n\n{response}"

        return response

    # ── 자동 검토 ──────────────────────────────────────────

    _REVIEW_TRIGGER_TOOLS = frozenset({"write_file", "execute", "python"})

    def _should_auto_review(self, agent: AgentBase, user_input: str, response: str) -> bool:
        """코딩 에이전트가 파일을 작성했거나 코드를 실행한 경우 자동 검토."""
        if "reviewer" not in self._agents:
            return False
        if agent.name not in ("coder", "coding", "main"):
            return False
        try:
            from config.settings import get_model_config
            if get_model_config(self.router.current_key).get("provider") == "claude_cli":
                return False
        except Exception:
            pass
        from config.settings import get_settings
        if not (get_settings().get("agents") or {}).get("auto_review", True):
            return False
        conv = agent._conversation
        for m in conv[-6:]:
            c = m.get("content", "")
            if any(f'name="{t}"' in c for t in self._REVIEW_TRIGGER_TOOLS):
                return True
        return False

    async def _run_auto_review(
        self, agent: AgentBase, user_input: str, response: str,
        activity: ActivityLogger, **kwargs,
    ) -> str:
        """reviewer 에이전트로 결과 검토."""
        reviewer = self._agents["reviewer"]
        review_prompt = (
            f"다음 작업 결과를 검토하세요.\n\n"
            f"## 사용자 요청\n{user_input[:500]}\n\n"
            f"## 에이전트 응답 (요약)\n{response[:1000]}\n\n"
            f"누락, 오류, 개선 사항이 있으면 간결하게 지적하세요. "
            f"문제가 없으면 '검토 완료: 이상 없음'이라고만 답하세요."
        )
        try:
            activity.note("자동 검토 시작 (reviewer)")
            review = await reviewer.handle(review_prompt)
            activity.note(f"자동 검토 완료: {review[:100]}")
            if "이상 없음" in review and len(review) < 50:
                return ""
            return review.strip()
        except Exception as e:
            logger.warning(f"자동 검토 실패: {e}")
            return ""

    # ── 자동 복잡도 라우팅 ────────────────────────────────

    _COMPLEX_KEYWORDS = (
        "만들어", "구현", "작성해", "빌드", "설계", "개발",
        "사이트", "앱", "서버", "API", "시스템",
        "리팩토링", "마이그레이션", "변환",
        "build", "create", "implement", "develop", "refactor",
    )
    _COMPLEX_MIN_LEN = 80

    _SIMPLE_TASK_KEYWORDS = (
        "그림", "그려", "이미지", "사진", "일러스트", "image", "draw", "photo",
        "검색", "찾아", "알려줘", "설명해", "번역",
        "search", "find", "explain", "translate",
    )

    def _auto_complexity_route(self, text: str, current: AgentBase) -> AgentBase | None:
        """복잡한 요청이면 planner로 자동 라우팅. 단순 도구 호출은 제외."""
        if "planner" not in self._agents:
            return None
        if any(kw in text for kw in self._SIMPLE_TASK_KEYWORDS):
            return None
        has_keyword = any(kw in text for kw in self._COMPLEX_KEYWORDS)
        is_long = len(text) >= self._COMPLEX_MIN_LEN
        multi_step = text.count("\n") >= 3 or text.count(",") >= 3
        if has_keyword and (is_long or multi_step):
            logger.info(f"복잡도 감지 → planner 자동 라우팅 (len={len(text)}, keywords=True)")
            return self._agents["planner"]
        return None

    def reset_session(self, session_id: str, agent_name: str | None = None) -> None:
        """특정 세션의 대화를 초기화한다."""
        if agent_name:
            self._sessions.pop((session_id, agent_name), None)
        else:
            # 전체 에이전트 세션 제거
            for key in list(self._sessions.keys()):
                if key[0] == session_id:
                    del self._sessions[key]

    def list_sessions(self) -> list[str]:
        """활성 세션 ID 목록."""
        return sorted({k[0] for k in self._sessions.keys()})

    # ── 상태 ───────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "agents": list(self._agents.keys()),
            "default_agent": self._default_agent,
            "model": self.router.current_key,
        }
