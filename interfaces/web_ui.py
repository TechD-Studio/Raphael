"""웹 UI — Gradio 기반 채팅 + 설정 인터페이스."""

from __future__ import annotations

import asyncio

import gradio as gr
from loguru import logger

from config.settings import (
    get_current_onboard_values,
    get_settings,
    reload_settings,
    save_env,
    save_local_settings,
)
from core.file_picker import PickerError, pick_directory
from core.input_guard import InputSource
from core.model_router import ModelRouter
from core.orchestrator import Orchestrator


class WebUI:
    """Gradio 기반 웹 채팅 UI + 설정 페이지."""

    def __init__(self, router: ModelRouter, orchestrator: Orchestrator) -> None:
        self.router = router
        self.orchestrator = orchestrator
        self.settings = get_settings()

    @staticmethod
    def _content_to_text(content) -> str:
        """Gradio Chatbot이 넘긴 content(str 또는 list[dict])를 문자열로 정규화."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    parts.append(item.get("text") or item.get("content") or "")
                elif isinstance(item, str):
                    parts.append(item)
            return "".join(parts)
        return str(content) if content is not None else ""

    def _normalize_history(self, history: list[dict] | None) -> list[dict]:
        """히스토리의 content를 모두 문자열로 정규화한다."""
        if not history:
            return []
        return [
            {"role": m.get("role", "user"), "content": self._content_to_text(m.get("content"))}
            for m in history
        ]

    def _add_user_message(self, message: str, history: list[dict]) -> tuple[str, list[dict]]:
        """1단계: 사용자 메시지를 히스토리에 즉시 추가하고 입력창을 비운다."""
        history = self._normalize_history(history)
        if not message or not message.strip():
            return message, history
        history.append({"role": "user", "content": message})
        return "", history

    async def _get_response(self, history: list[dict], agent_name: str):
        """응답을 스트리밍으로 받아 UI에 실시간 반영한다.

        표시 구성:
          - 상단: 접혀 있는 "🔧 도구/생각 로그" (tool_call, tool_result, thinking, elapsed)
          - 하단: 최종 응답 텍스트 (토큰 단위로 계속 자라남)
        """
        import asyncio as _asyncio

        history = self._normalize_history(history)
        if not history or history[-1]["role"] != "user":
            yield history
            return

        user_message = history[-1]["content"]
        agent_key = agent_name if agent_name else (
            self.orchestrator.default_agent.name if self.orchestrator.default_agent else None
        )
        if not agent_key:
            history.append({"role": "assistant", "content": "에이전트가 등록되지 않았습니다."})
            yield history
            return

        # 이벤트 큐
        queue: _asyncio.Queue = _asyncio.Queue()

        def on_event(entry: dict):
            queue.put_nowait(entry)

        # 로딩 메시지 초기 표시
        history.append({"role": "assistant", "content": "🤔 생각 중..."})
        yield history

        # 응답 생성 태스크 시작 — verbose=False, stream_tokens=True, callback 지정
        async def _run():
            try:
                return await self.orchestrator.route(
                    user_message,
                    agent_name=agent_key,
                    source=InputSource.WEB_UI,
                    verbose=False,
                    stream_tokens=True,
                    activity_callback=on_event,
                )
            except Exception as e:
                logger.error(f"웹 UI 오류: {e}")
                return f"오류가 발생했습니다: {e}"

        task = _asyncio.create_task(_run())

        activity_log: list[str] = []       # 접기 영역용 로그
        response_text: str = ""             # 토큰 누적 응답
        thinking_idx: int | None = None     # 현재 thinking 줄의 인덱스 (elapsed로 업데이트)
        try:
            while not task.done() or not queue.empty():
                try:
                    entry = await _asyncio.wait_for(queue.get(), timeout=0.3)
                except _asyncio.TimeoutError:
                    continue

                t = entry.get("type")
                data = entry.get("data", {})
                if t == "token_chunk":
                    response_text += data.get("text", "")
                elif t == "tool_call":
                    args = data.get("args", {})
                    args_str = ", ".join(f"{k}={v!r}" for k, v in list(args.items())[:2])
                    activity_log.append(f"🔧 {data.get('name', '?')}({args_str[:120]})")
                elif t == "tool_result":
                    icon = "✗" if data.get("error") else "✓"
                    out = (data.get("output") or "")[:120].replace("\n", " ")
                    activity_log.append(f"{icon} {data.get('name', '?')}: {out}")
                elif t == "model_call_start":
                    iter_str = f" · 반복 {data['iteration']}" if data.get("iteration", 1) > 1 else ""
                    activity_log.append(f"🧠 thinking... {data.get('model', '?')}{iter_str}")
                    thinking_idx = len(activity_log) - 1
                elif t == "model_call_progress":
                    # 기존 thinking 줄을 경과시간으로 라이브 업데이트 (새 줄 추가 아님)
                    if thinking_idx is not None and thinking_idx < len(activity_log):
                        elapsed = data.get("elapsed_seconds", 0)
                        current = activity_log[thinking_idx]
                        # 기존 (Xs) 제거 후 새 시간 부착
                        import re as _re
                        base = _re.sub(r"\s*\(\d+(\.\d+)?s\)\s*$", "", current)
                        activity_log[thinking_idx] = f"{base} ({elapsed}s)"
                    else:
                        continue  # yield 불필요
                elif t == "model_call_end":
                    # thinking 줄을 완료 상태로 치환
                    tk = data.get("tokens") or {}
                    tok = f" [+{tk.get('prompt', 0)}/+{tk.get('completion', 0)} tok]" if tk else ""
                    final_line = f"⚡ done in {data.get('duration_seconds')}s{tok}"
                    if thinking_idx is not None and thinking_idx < len(activity_log):
                        activity_log[thinking_idx] = final_line
                    else:
                        activity_log.append(final_line)
                    thinking_idx = None
                else:
                    continue

                history[-1]["content"] = self._render_live(activity_log, response_text)
                yield history

            # 최종 응답 확정
            final = await task
            if not response_text.strip():
                response_text = final  # 스트리밍이 비어있던 경우

            history[-1]["content"] = self._render_final(activity_log, response_text)
            yield history
        except Exception as e:
            logger.error(f"스트리밍 루프 오류: {e}")
            history[-1]["content"] = f"오류: {e}"
            yield history

    @staticmethod
    def _render_live(activity_log: list[str], response_text: str) -> str:
        """진행 중 — 상단: 현재 진행 상태 한 줄 / 하단: 누적 응답."""
        parts = []
        if activity_log:
            # 가장 최근 thinking/done/tool 상태를 헤더 한 줄로
            head = activity_log[-1]
            parts.append(f"`{head}`")
            # 추가 로그(도구 실행 등)는 접혀 있는 블록으로
            if len(activity_log) > 1:
                tail = activity_log[:-1][-4:]
                body = "\n".join(f"- {x}" for x in tail)
                parts.append(f"<details><summary>진행 로그 ({len(activity_log)}건)</summary>\n\n{body}\n\n</details>")
        if response_text:
            parts.append(response_text)
        return "\n\n".join(parts) if parts else "_…_"

    @staticmethod
    def _render_final(activity_log: list[str], response_text: str) -> str:
        """완료 후 — 활동 로그 접기 + 최종 응답."""
        if not activity_log:
            return response_text
        body = "\n".join(f"- {x}" for x in activity_log)
        return (
            f"<details><summary>🔧 진행 로그 ({len(activity_log)}건)</summary>\n\n"
            f"```\n{body}\n```\n\n</details>\n\n{response_text}"
        )

    async def _save_settings(
        self,
        ollama_host: str,
        ollama_port: int,
        vault_path: str,
        telegram_token: str,
        discord_token: str,
        allowed_paths_text: str,
    ) -> str:
        """설정을 저장하고 결과 메시지를 반환한다."""
        try:
            current = get_current_onboard_values()

            # allowed_paths: 줄바꿈 구분 텍스트를 리스트로
            allowed_paths = [line.strip() for line in (allowed_paths_text or "").splitlines() if line.strip()]

            # settings.local.yaml 저장
            save_local_settings({
                "models": {"ollama": {"host": ollama_host, "port": int(ollama_port)}},
                "memory": {"obsidian_vault": vault_path},
                "tools": {"file": {"allowed_paths": allowed_paths}},
            })

            # .env 저장 (값이 변경된 경우만)
            if telegram_token and telegram_token != current["telegram_token"]:
                save_env("TELEGRAM_BOT_TOKEN", telegram_token)
            if discord_token and discord_token != current["discord_token"]:
                save_env("DISCORD_BOT_TOKEN", discord_token)

            # ModelRouter 재연결: 기존 httpx 클라이언트를 안전하게 닫고 새 인스턴스로 교체
            reload_settings()
            try:
                await self.router.close()
            except Exception:
                pass
            self.router.__post_init__()

            # 연결 테스트
            health = await self.router.health_check()
            ollama_status = "연결 성공" if health["status"] == "ok" else f"연결 실패 ({health['status']})"

            return (
                f"설정 저장 완료!\n\n"
                f"  Ollama: {ollama_host}:{ollama_port} — {ollama_status}\n"
                f"  옵시디언 볼트: {vault_path}\n"
                f"  텔레그램: {'설정됨' if telegram_token else '미설정'}\n"
                f"  디스코드: {'설정됨' if discord_token else '미설정'}"
            )
        except Exception as e:
            logger.error(f"설정 저장 오류: {e}")
            return f"설정 저장 실패: {e}"

    async def _pick_vault_dir(self, current_path: str) -> str:
        """네이티브 폴더 선택 다이얼로그를 열어 선택된 경로를 반환한다.

        사용자가 취소하면 기존 값을 유지한다.
        """
        try:
            selected = await pick_directory(
                initial_dir=current_path or None,
                title="옵시디언 볼트 폴더 선택",
            )
        except PickerError as e:
            logger.warning(f"폴더 선택 실패: {e}")
            # 실패 시 기존 값 유지 + 안내는 placeholder에 의존
            return current_path
        except Exception as e:
            logger.error(f"폴더 선택 중 예외: {e}")
            return current_path

        return selected or current_path

    # ── 라우팅 설정 헬퍼 ───────────────────────────────────

    def _routing_load_table(self) -> tuple:
        """현재 라우팅 설정을 UI에 표시할 (strategy, DataFrame rows) 반환."""
        from core.router_strategy import load_config
        cfg = load_config()
        rows = []
        for r in cfg["rules"]:
            match = r.get("match", {})
            rows.append([
                ",".join(match.get("contains_any", [])) if isinstance(match.get("contains_any"), list) else "",
                int(match.get("token_estimate_gt", 0) or 0),
                int(match.get("token_estimate_lt", 0) or 0),
                int(match.get("min_messages", 0) or 0),
                match.get("agent", "") or "",
                bool(match.get("default", False)),
                r.get("prefer_model", "") or "",
                r.get("prefer_agent", "") or "",
            ])
        return cfg["strategy"], rows

    def _routing_save_table(self, strategy: str, rows) -> str:
        """DataFrame rows 를 rules 로 변환해 저장."""
        from core.router_strategy import save_config
        rules: list[dict] = []
        # gradio가 DataFrame을 list[list] 또는 pandas DataFrame으로 전달할 수 있음
        try:
            import pandas as _pd
            if isinstance(rows, _pd.DataFrame):
                rows = rows.values.tolist()
        except ImportError:
            pass

        for row in rows or []:
            if row is None:
                continue
            # row: [contains_any, token_gt, token_lt, min_messages, agent, default, prefer_model, prefer_agent]
            contains, tgt, tlt, mmsg, ag, deflt, pm, pa = (list(row) + [None] * 8)[:8]
            match: dict = {}
            if deflt:
                match["default"] = True
            else:
                if contains and str(contains).strip():
                    match["contains_any"] = [k.strip() for k in str(contains).split(",") if k.strip()]
                try:
                    if tgt and int(tgt) > 0:
                        match["token_estimate_gt"] = int(tgt)
                except (ValueError, TypeError):
                    pass
                try:
                    if tlt and int(tlt) > 0:
                        match["token_estimate_lt"] = int(tlt)
                except (ValueError, TypeError):
                    pass
                try:
                    if mmsg and int(mmsg) > 0:
                        match["min_messages"] = int(mmsg)
                except (ValueError, TypeError):
                    pass
                if ag and str(ag).strip():
                    match["agent"] = str(ag).strip()

            if not match:
                continue  # 빈 행 건너뜀
            rule: dict = {"match": match}
            if pm and str(pm).strip():
                rule["prefer_model"] = str(pm).strip()
            if pa and str(pa).strip():
                rule["prefer_agent"] = str(pa).strip()
            if "prefer_model" not in rule and "prefer_agent" not in rule:
                continue  # 타겟 없는 규칙 무시
            rules.append(rule)

        save_config(strategy=strategy, rules=rules)
        reload_settings()
        return f"✓ 저장됨: strategy={strategy}, rules={len(rules)}개"

    def _routing_test(self, text: str = "", agent: str = "coding", messages=1) -> str:
        from core.router_strategy import RouterStrategy, TaskContext, load_config
        text = text or ""
        agent = agent or "coding"
        try:
            messages = int(messages or 1)
        except (TypeError, ValueError):
            messages = 1
        if not text.strip():
            return "테스트 입력을 채우세요."
        cfg = load_config()
        if cfg["strategy"] != "auto":
            return f"strategy가 '{cfg['strategy']}'입니다. 위에서 auto로 바꾸고 저장하세요."
        strat = RouterStrategy()
        ctx = TaskContext(user_input=text, agent=agent, messages_count=messages)
        d = strat.decide(ctx)
        if d.model_key or d.agent_name:
            return (
                f"✓ 매칭됨\n"
                f"  → 모델: {d.model_key or '(유지)'}\n"
                f"  → 에이전트: {d.agent_name or '(유지)'}\n"
                f"  규칙: {d.rule_name}"
            )
        return "매칭되는 규칙 없음 — 기본 모델/에이전트 사용"

    def _load_current_settings(self) -> tuple:
        """디스크에서 최신 설정을 읽어 UI 필드에 채울 값을 반환한다."""
        reload_settings()
        v = get_current_onboard_values()
        return (
            v["ollama_host"],
            v["ollama_port"],
            v["obsidian_vault"],
            v["telegram_token"],
            v["discord_token"],
            "\n".join(v["allowed_paths"]),
        )

    def _export_history(self, history: list[dict], fmt: str = "markdown") -> str:
        """현재 웹 대화 히스토리를 내보낸다."""
        import json as _json
        history = self._normalize_history(history)
        if not history:
            return "내보낼 대화가 없습니다."
        if fmt == "json":
            return _json.dumps(history, ensure_ascii=False, indent=2)
        # markdown
        lines = ["# Raphael 대화 기록\n"]
        for m in history:
            role = m["role"]
            content = m["content"]
            if role == "user":
                lines.append(f"\n**🧑 User**\n\n{content}\n")
            else:
                lines.append(f"\n**🤖 Raphael**\n\n{content}\n")
        return "\n".join(lines)

    def _token_stats_text(self) -> str:
        stats = self.router.get_token_stats()
        if not stats:
            return "아직 호출 기록이 없습니다."
        lines = []
        for model, s in stats.items():
            lines.append(
                f"- **{model}**: {s['calls']}회 호출, "
                f"prompt {s['prompt']:,} + completion {s['completion']:,} = "
                f"{s['prompt'] + s['completion']:,} 토큰, "
                f"누적 {s['total_ms'] / 1000:.1f}s"
            )
        return "\n".join(lines)

    async def _switch_model(self, model_key: str) -> str:
        """채팅 탭의 모델 선택 콜백 — 현재 모델을 전환하고 설치 여부 확인."""
        if not model_key:
            return f"현재 모델: **{self.router.current_key}**"
        try:
            cfg, installed, _ = await self.router.switch_model_checked(model_key)
            if installed:
                return f"모델 변경됨 → **{model_key}** ({cfg['name']})"
            return (
                f"모델 변경됨 → **{model_key}** ({cfg['name']})\n\n"
                f"⚠ Ollama 서버에 이 모델이 설치되어 있지 않습니다.\n"
                f"설치 명령: `ollama pull {cfg['name']}`"
            )
        except ValueError as e:
            return f"오류: {e}"

    async def _refresh_model_list(self) -> gr.Dropdown:
        """설치된 모델을 Ollama에서 가져와 드롭다운 choices를 업데이트한다."""
        installed = await self.router.list_installed_models()
        defined = self.router.list_models()

        choices: list[tuple[str, str]] = []
        # 정의된 것 중 설치된 것 먼저
        for key, cfg in defined.items():
            label = f"{key}"
            if cfg["name"] in installed:
                label += " ✓"
            else:
                label += " (미설치)"
            choices.append((label, key))

        # Ollama에만 있고 settings에 없는 모델도 포함
        defined_names = {cfg["name"] for cfg in defined.values()}
        for name in installed:
            if name not in defined_names:
                choices.append((f"{name} ✓ (ollama)", name))

        return gr.Dropdown(choices=choices, value=self.router.current_key)

    def _test_connection(self, ollama_host: str, ollama_port: int) -> str:
        """Ollama 연결 테스트."""
        import httpx

        try:
            url = f"http://{ollama_host}:{int(ollama_port)}"
            resp = httpx.get(url, timeout=5)
            if resp.status_code == 200:
                return f"연결 성공 — {url}"
            return f"응답 오류 (HTTP {resp.status_code}) — {url}"
        except httpx.ConnectError:
            return f"연결 실패 — {ollama_host}:{ollama_port} 에 접근할 수 없습니다."
        except Exception as e:
            return f"오류: {e}"

    # ── 세션 헬퍼 (UI 콜백) ────────────────────────────────

    def _sessions_rows(self) -> list[list]:
        """(미사용 — 내부 호환용으로 유지)"""
        from core.session_store import list_sessions
        rows = [["", "(새 대화)", "", ""]]
        for s in list_sessions()[:50]:
            rows.append([
                s["id"][:12], s["agent"], s["preview"][:60],
                s["updated"][5:16].replace("T", " "),
            ])
        return rows

    def _session_choices(self) -> list[tuple[str, str]]:
        """Dropdown용 [(label, value)]."""
        from core.session_store import list_sessions
        out = [("➕ 새 대화", "")]
        for s in list_sessions()[:50]:
            label = f"{s['updated'][5:16].replace('T', ' ')} · [{s['agent']}] · {s['preview'][:40]}"
            out.append((label, s["id"]))
        return out

    def _refresh_sessions_table(self):
        return gr.Dropdown(choices=self._session_choices(), value="")

    def _load_session_into_chat(self, session_id: str = ""):
        """세션 선택 시 chatbot에 그 대화를 로드한다. 빈 입력도 안전 처리."""
        sid = session_id or ""
        if not sid:
            return [], "_새 대화 시작_", ""
        from core.session_store import Session
        s = Session.load(sid)
        if s is None:
            return [], f"세션 {sid} 없음", sid
        history = []
        for m in s.conversation:
            role = m.get("role")
            content = m.get("content", "")
            if role in ("user", "assistant"):
                history.append({"role": role, "content": content})
        info = f"**{s.id}** · agent={s.agent} · turns={sum(1 for m in s.conversation if m.get('role')=='user')} · {s.updated}"
        return history, info, sid

    def _delete_session(self, session_id: str = ""):
        from core.session_store import delete_session
        sid = session_id or ""
        if not sid:
            return gr.Radio(choices=self._sessions_options(), value=""), "(선택된 세션 없음)"
        ok = delete_session(sid)
        msg = "삭제됨" if ok else "존재하지 않음"
        return gr.Radio(choices=self._sessions_options(), value=""), msg

    # ── 라우팅 JSON 헬퍼 (Dataframe 대신 Code 컴포넌트) ────

    # ── 상황 슬롯 정의 (UI에서 사용자가 모델만 고르면 됨) ─────
    ROUTING_SLOTS = [
        # (slot_id, 라벨, 매칭 조건 dict, 기본 prefer_agent or "")
        ("short", "🚀 짧은 입력 (60 토큰 미만)",
         {"token_estimate_lt": 60}, ""),
        ("review", "🔍 리뷰/분석/디버깅 키워드 포함",
         {"contains_any": ["리뷰", "분석", "버그", "최적화", "리팩토링", "review", "analyze", "debug"]}, ""),
        ("project", "🏗 큰 작업 (만들기/프로젝트 키워드 + 긴 입력)",
         {"contains_any": ["만들어줘", "전체", "프로젝트", "사이트", "구현", "build", "create"],
          "token_estimate_gt": 150}, "planner"),
        ("long_chat", "💬 긴 대화 (10턴 이상, coding 에이전트)",
         {"agent": "coding", "min_messages": 10}, ""),
        ("default", "🎯 기본값 (위 조건 모두 미매칭)",
         {"default": True}, ""),
    ]

    def _slot_models(self) -> list[str]:
        """슬롯 드롭다운 선택지 — 비어있음(=라우팅 안함) + 등록된 모든 모델."""
        return [""] + list(self.router.list_models().keys())

    def _routing_load_slots(self) -> tuple:
        """현재 저장된 rules → 슬롯별 (model, agent) 매핑으로 변환.

        Returns: (strategy, slot1_model, slot2_model, slot3_model, slot4_model, slot5_model)
        """
        from core.router_strategy import load_config
        cfg = load_config()
        # 슬롯별 모델 매핑 — 매치 조건이 동일한 규칙을 찾음
        slot_models = []
        for slot_id, _, match, _ in self.ROUTING_SLOTS:
            found = ""
            for r in cfg["rules"]:
                if r.get("match") == match:
                    found = r.get("prefer_model", "") or ""
                    break
            slot_models.append(found)
        return (cfg["strategy"], *slot_models)

    def _routing_save_slots(
        self,
        strategy: str = "manual",
        m_short: str = "",
        m_review: str = "",
        m_project: str = "",
        m_long_chat: str = "",
        m_default: str = "",
    ) -> str:
        """슬롯별 모델 선택을 rules로 직렬화해 저장."""
        from core.router_strategy import save_config
        strategy = strategy or "manual"
        slot_values = [m_short, m_review, m_project, m_long_chat, m_default]
        rules = []
        for (slot_id, _, match, default_agent), model in zip(self.ROUTING_SLOTS, slot_values):
            model = (model or "").strip()
            if not model:
                continue  # 모델 안 고르면 해당 슬롯은 비활성
            rule = {"match": match, "prefer_model": model}
            if default_agent:
                rule["prefer_agent"] = default_agent
            rules.append(rule)
        save_config(strategy=strategy, rules=rules)
        reload_settings()
        return (
            f"✓ 저장됨\n"
            f"  전략: {strategy}\n"
            f"  활성 규칙: {len(rules)}개\n"
            + "\n".join(
                f"  · {label} → {model or '(미설정)'}"
                for (_, label, _, _), model in zip(self.ROUTING_SLOTS, slot_values)
            )
        )

    # ── 에이전트 정의 헬퍼 ────────────────────────────────

    def _all_agent_defs(self) -> list[dict]:
        try:
            from core.agent_definitions import list_definitions
            return [
                {"name": d.name, "description": d.description, "tools": d.tools}
                for d in list_definitions()
            ]
        except Exception:
            return []

    def _active_agent_names(self) -> list[str]:
        try:
            from core.agent_definitions import load_active_agents
            return sorted(load_active_agents())
        except Exception:
            return []

    def _save_active_agents(self, names: list[str] = None) -> str:
        from core.agent_definitions import save_active_agents
        names = names or []
        # main은 항상 포함
        full = set(names) | {"main"}
        save_active_agents(full)
        return f"✓ 저장됨: 활성 전문가 {len(full) - 1}개 + main"

    def _refresh_agent_choices(self):
        defs = self._all_agent_defs()
        active = self._active_agent_names()
        choices = [
            (f"{d['name']} — {d['description'][:50]}", d["name"])
            for d in defs if d["name"] != "main"
        ]
        return gr.CheckboxGroup(choices=choices, value=[n for n in active if n != "main"])

    def _show_recommendations(self) -> str:
        from core.agent_definitions import load_active_agents, get_recommendations
        recs = get_recommendations(load_active_agents())
        if not recs:
            return "_사용 패턴 누적 후 추천이 표시됩니다._"
        lines = ["**추천 전문가:**"]
        for name, reason in recs:
            lines.append(f"- `{name}` — {reason}")
        return "\n".join(lines)

    def _routing_apply_recommended(self):
        """추천 기본 매핑."""
        return (
            "auto",
            "gemma4-e2b",     # 짧은 입력 → 빠른 로컬
            "claude-sonnet",  # 리뷰/분석 → claude
            "claude-opus",    # 큰 작업 → claude opus + planner
            "gemma4-26b",     # 긴 대화 → 큰 로컬
            "gemma4-e4b",     # 기본 → 균형 로컬
        )

    def build(self) -> gr.Blocks:
        """Gradio UI 재설계.

        - 채팅 + 세션 통합 (좌측 세션 사이드바 / 우측 채팅창)
        - 사이드바는 Accordion 으로 접기 가능 (최소화)
        - 라우팅: Dataframe 대신 Code(JSON) 컴포넌트로 안정성 ↑
        """
        agents = [a["name"] for a in self.orchestrator.list_agents()]

        with gr.Blocks(title="Raphael AI Agent") as demo:
            gr.Markdown(f"# Raphael v{self.settings['raphael']['version']}")

            # 브라우저 localStorage 지속 저장
            try:
                persisted_chat = gr.BrowserState([], storage_key="raphael-chat-history")
            except AttributeError:
                persisted_chat = gr.State([])

            current_session_id = gr.State("")
            model_choices = list(self.router.list_models().keys())

            with gr.Tabs():
                # ── 채팅 + 세션 통합 ───────────────────────
                with gr.Tab("💬 채팅"):
                    # 사이드바 열림 상태
                    sidebar_open = gr.State(True)

                    with gr.Row():
                        # ── 좌측 사이드바 (모델/에이전트 → 세션 → 내보내기/통계) ──
                        with gr.Column(scale=1, min_width=280, visible=True) as sidebar_col:
                            # ─ 1) 모델 ─
                            with gr.Accordion("⚙️ 모델", open=True):
                                model_dropdown = gr.Dropdown(
                                    choices=model_choices,
                                    value=self.router.current_key,
                                    label="모델 (✓=설치됨)",
                                )
                                btn_refresh_models = gr.Button("🔄 모델 목록 새로고침", size="sm")
                                model_status = gr.Markdown(
                                    f"현재 모델: **{self.router.current_key}**"
                                )

                            # ─ 1-1) 활성 전문가 (체크박스) ─
                            with gr.Accordion("🤖 활성 전문가 (main이 위임할 대상)", open=True):
                                gr.Markdown(
                                    "메인 에이전트가 위임할 수 있는 전문가들. "
                                    "체크된 것만 카탈로그에 노출됩니다."
                                )
                                _all_agent_defs = self._all_agent_defs()
                                _active = self._active_agent_names()
                                agents_checkbox = gr.CheckboxGroup(
                                    choices=[
                                        (f"{d['name']} — {d['description'][:50]}", d["name"])
                                        for d in _all_agent_defs if d["name"] != "main"
                                    ],
                                    value=[n for n in _active if n != "main"],
                                    label="전문가 활성화",
                                )
                                with gr.Row():
                                    btn_save_agents = gr.Button("💾 활성화 저장", size="sm", variant="primary")
                                    btn_refresh_agents = gr.Button("🔄", size="sm", min_width=40)
                                agent_save_result = gr.Markdown("_변경 후 저장 필요_")
                                # 추천
                                btn_show_recs = gr.Button("✨ 추천 보기", size="sm")
                                recs_display = gr.Markdown("")

                            # 채팅에서 강제로 특정 에이전트 사용 (보통은 main = 자동)
                            agent_dropdown = gr.Dropdown(
                                choices=[""] + agents,
                                value="",
                                label="(고급) 에이전트 직접 지정 — 비우면 main 자동",
                                visible=False,  # 사이드바 정리 — 필요시 visible=True
                            )

                            # ─ 2) 세션 ─
                            with gr.Accordion("📚 세션", open=True):
                                session_picker = gr.Dropdown(
                                    choices=self._session_choices(),
                                    value="",
                                    label="세션 선택",
                                    interactive=True,
                                )
                                with gr.Row():
                                    btn_refresh_sess = gr.Button("🔄", size="sm", min_width=40)
                                    btn_new_chat = gr.Button("➕ 새", size="sm")
                                    btn_del_sess = gr.Button("🗑 삭제", size="sm")
                                sess_info = gr.Markdown("_드롭다운에서 세션을 선택하세요_")

                            # ─ 3) 내보내기 / 통계 ─
                            with gr.Accordion("📤 내보내기 / 통계", open=False):
                                with gr.Row():
                                    btn_export_md = gr.Button("MD", size="sm")
                                    btn_export_json = gr.Button("JSON", size="sm")
                                    btn_tokens = gr.Button("토큰", size="sm")
                                export_output = gr.Textbox(
                                    label="결과 (복사해서 사용)",
                                    lines=10,
                                )

                            # ─ 4) 라우팅 — 상황별 모델 선택 폼 ─
                            with gr.Accordion("🔀 상황별 모델 선택 (auto-routing)", open=False):
                                gr.Markdown(
                                    "각 상황에 어떤 모델을 쓸지 골라 저장하세요. "
                                    "`auto`로 두면 매 요청마다 위→아래 평가, "
                                    "`manual`이면 비활성(현재 선택된 모델만 사용).\n\n"
                                    "비워두면 해당 상황은 라우팅하지 않습니다."
                                )

                                _init = self._routing_load_slots()
                                _init_strategy = _init[0]
                                _init_models = _init[1:]

                                routing_strategy = gr.Radio(
                                    choices=["manual", "auto"],
                                    value=_init_strategy,
                                    label="전략",
                                )

                                slot_choices = self._slot_models()
                                slot_dropdowns = []
                                for (slot_id, label, _, default_agent), init_v in zip(
                                    self.ROUTING_SLOTS, _init_models
                                ):
                                    suffix = f"  → {default_agent} 에이전트로" if default_agent else ""
                                    dd = gr.Dropdown(
                                        choices=slot_choices,
                                        value=init_v,
                                        label=label + suffix,
                                    )
                                    slot_dropdowns.append(dd)

                                with gr.Row():
                                    btn_routing_save = gr.Button("💾 저장", size="sm", variant="primary")
                                    btn_routing_reload = gr.Button("🔄 다시 불러오기", size="sm")
                                    btn_routing_template = gr.Button("📋 추천 적용", size="sm")
                                routing_save_result = gr.Textbox(
                                    label="결과", interactive=False, lines=8,
                                )

                        # ── 우측 메인 (채팅창만) ──
                        with gr.Column(scale=4):
                            btn_toggle_sidebar = gr.Button(
                                "◀ 사이드바 접기",
                                size="sm",
                            )
                            chatbot = gr.Chatbot(label="대화", height=600)
                            with gr.Row():
                                msg_input = gr.Textbox(
                                    placeholder="메시지를 입력하세요... (Enter로 전송)",
                                    show_label=False,
                                    scale=9,
                                )
                                send_btn = gr.Button("전송", variant="primary", scale=1)
                            with gr.Row():
                                clear_btn = gr.Button("대화 초기화", size="sm")

                    # ── 이벤트: 모델/에이전트 ──
                    model_dropdown.change(
                        fn=self._switch_model,
                        inputs=[model_dropdown],
                        outputs=[model_status],
                    )
                    btn_refresh_models.click(
                        fn=self._refresh_model_list,
                        outputs=[model_dropdown],
                    )

                    # ── 사이드바 토글 ──
                    def _toggle_sidebar(open_state: bool):
                        new_state = not open_state
                        return (
                            new_state,
                            gr.update(visible=new_state),
                            "◀ 사이드바 접기" if new_state else "▶ 사이드바 펼치기",
                        )
                    btn_toggle_sidebar.click(
                        fn=_toggle_sidebar,
                        inputs=[sidebar_open],
                        outputs=[sidebar_open, sidebar_col, btn_toggle_sidebar],
                    )

                    # ── 이벤트: 세션 Dropdown 선택 ──
                    def _on_session_pick(sid: str = ""):
                        return self._load_session_into_chat(sid or "")

                    session_picker.change(
                        fn=_on_session_pick,
                        inputs=[session_picker],
                        outputs=[chatbot, sess_info, current_session_id],
                    )
                    btn_refresh_sess.click(
                        fn=self._refresh_sessions_table,
                        outputs=[session_picker],
                    )

                    def _new_chat():
                        return [], "_새 대화 시작_", "", gr.Dropdown(
                            choices=self._session_choices(), value=""
                        )
                    btn_new_chat.click(
                        fn=_new_chat,
                        outputs=[chatbot, sess_info, current_session_id, session_picker],
                    )

                    def _del_then_refresh(sid: str = ""):
                        from core.session_store import delete_session
                        msg = "(선택된 세션 없음)"
                        if sid:
                            msg = "삭제됨" if delete_session(sid) else "존재하지 않음"
                        return gr.Dropdown(choices=self._session_choices(), value=""), msg
                    btn_del_sess.click(
                        fn=_del_then_refresh,
                        inputs=[current_session_id],
                        outputs=[session_picker, sess_info],
                    )

                    # ── 이벤트: 채팅 (2단계 체인) ──
                    def _sync_persist(history):
                        return history

                    msg_input.submit(
                        fn=self._add_user_message,
                        inputs=[msg_input, chatbot],
                        outputs=[msg_input, chatbot],
                        queue=False,
                    ).then(
                        fn=self._get_response,
                        inputs=[chatbot, agent_dropdown],
                        outputs=chatbot,
                    ).then(
                        fn=_sync_persist, inputs=[chatbot], outputs=[persisted_chat],
                    )
                    send_btn.click(
                        fn=self._add_user_message,
                        inputs=[msg_input, chatbot],
                        outputs=[msg_input, chatbot],
                        queue=False,
                    ).then(
                        fn=self._get_response,
                        inputs=[chatbot, agent_dropdown],
                        outputs=chatbot,
                    ).then(
                        fn=_sync_persist, inputs=[chatbot], outputs=[persisted_chat],
                    )

                    def _clear_all():
                        return [], []
                    clear_btn.click(_clear_all, outputs=[chatbot, persisted_chat])

                    def _restore(saved):
                        return saved or []
                    demo.load(fn=_restore, inputs=[persisted_chat], outputs=[chatbot])

                    # 내보내기/통계
                    btn_export_md.click(
                        fn=lambda h: self._export_history(h, "markdown"),
                        inputs=[chatbot], outputs=export_output,
                    )
                    btn_export_json.click(
                        fn=lambda h: self._export_history(h, "json"),
                        inputs=[chatbot], outputs=export_output,
                    )
                    btn_tokens.click(
                        fn=self._token_stats_text,
                        outputs=export_output,
                    )

                    # ── 활성 전문가 이벤트 ──
                    btn_save_agents.click(
                        fn=self._save_active_agents,
                        inputs=[agents_checkbox],
                        outputs=[agent_save_result],
                    )
                    btn_refresh_agents.click(
                        fn=self._refresh_agent_choices,
                        outputs=[agents_checkbox],
                    )
                    btn_show_recs.click(
                        fn=self._show_recommendations,
                        outputs=[recs_display],
                    )

                    # ── 라우팅 이벤트 바인딩 (슬롯 폼) ──
                    btn_routing_save.click(
                        fn=self._routing_save_slots,
                        inputs=[routing_strategy, *slot_dropdowns],
                        outputs=routing_save_result,
                    )
                    btn_routing_reload.click(
                        fn=self._routing_load_slots,
                        outputs=[routing_strategy, *slot_dropdowns],
                    )
                    btn_routing_template.click(
                        fn=self._routing_apply_recommended,
                        outputs=[routing_strategy, *slot_dropdowns],
                    )

                # ── 설정 탭 ──
                with gr.Tab("설정"):
                    gr.Markdown("## 초기 설정")
                    gr.Markdown("Ollama 서버, 옵시디언 볼트, 봇 토큰을 설정합니다.")

                    with gr.Group():
                        gr.Markdown("### Ollama 서버")
                        with gr.Row():
                            inp_host = gr.Textbox(
                                label="호스트 IP",
                                placeholder="192.168.0.10 또는 Tailscale IP",
                            )
                            inp_port = gr.Number(
                                label="포트",
                                precision=0,
                            )
                        with gr.Row():
                            btn_test = gr.Button("연결 테스트", variant="secondary")
                            test_result = gr.Textbox(
                                label="테스트 결과",
                                interactive=False,
                            )
                        btn_test.click(
                            fn=self._test_connection,
                            inputs=[inp_host, inp_port],
                            outputs=test_result,
                        )

                    with gr.Group():
                        gr.Markdown("### 옵시디언 볼트")
                        with gr.Row():
                            inp_vault = gr.Textbox(
                                label="볼트 경로",
                                placeholder="~/Obsidian/Vault (Mac) 또는 /home/you/Obsidian/Vault (Linux)",
                                scale=9,
                            )
                            btn_pick = gr.Button("폴더 선택", scale=1)
                        btn_pick.click(
                            fn=self._pick_vault_dir,
                            inputs=[inp_vault],
                            outputs=[inp_vault],
                        )

                    with gr.Group():
                        gr.Markdown("### 파일 접근 허용 경로")
                        gr.Markdown(
                            "에이전트의 파일 도구가 접근할 수 있는 경로. "
                            "줄바꿈으로 여러 개 지정. `~` 홈 확장 지원.\n"
                            "비어있으면 기본값: 홈 디렉토리 + /tmp + 현재 작업 디렉토리."
                        )
                        inp_allowed_paths = gr.Textbox(
                            label="허용 경로 (한 줄에 하나씩)",
                            placeholder="~/workspace\n~/Documents/projects\n/tmp/my_output",
                            lines=5,
                        )

                    with gr.Group():
                        gr.Markdown("### 봇 토큰 (선택)")
                        inp_telegram = gr.Textbox(
                            label="텔레그램 봇 토큰",
                            placeholder="123456:ABC-DEF...",
                            type="password",
                        )
                        inp_discord = gr.Textbox(
                            label="디스코드 봇 토큰",
                            placeholder="MTIx...",
                            type="password",
                        )

                    with gr.Row():
                        btn_save = gr.Button("설정 저장", variant="primary", size="lg")
                        btn_reload = gr.Button("현재 설정 불러오기", variant="secondary")

                    save_result = gr.Textbox(
                        label="결과",
                        interactive=False,
                        lines=6,
                    )
                    btn_save.click(
                        fn=self._save_settings,
                        inputs=[inp_host, inp_port, inp_vault, inp_telegram, inp_discord, inp_allowed_paths],
                        outputs=save_result,
                    )

                    # 설정 필드 출력 목록
                    setting_outputs = [inp_host, inp_port, inp_vault, inp_telegram, inp_discord, inp_allowed_paths]

                    # "현재 설정 불러오기" 버튼 → 디스크에서 재로드
                    btn_reload.click(
                        fn=self._load_current_settings,
                        outputs=setting_outputs,
                    )

                    # 페이지 로드 시 자동으로 최신 설정값 채우기
                    demo.load(
                        fn=self._load_current_settings,
                        outputs=setting_outputs,
                    )

            # 페이지 로드 시 설치된 모델로 드롭다운 갱신
            demo.load(
                fn=self._refresh_model_list,
                outputs=[model_dropdown],
            )

        return demo

    def launch(self) -> None:
        """웹 UI를 실행한다."""
        ui_cfg = self.settings["interfaces"]["web_ui"]
        demo = self.build()
        logger.info(f"웹 UI 시작: {ui_cfg['host']}:{ui_cfg['port']}")

        launch_kwargs = {
            "server_name": ui_cfg.get("host", "0.0.0.0"),
            "server_port": ui_cfg.get("port", 7860),
            "share": ui_cfg.get("share", False),
        }
        # Gradio 6.0+ 에서는 theme이 launch()에 있음
        try:
            demo.launch(theme=gr.themes.Soft(), **launch_kwargs)
        except TypeError:
            # Gradio 4/5 fallback
            demo.launch(**launch_kwargs)
