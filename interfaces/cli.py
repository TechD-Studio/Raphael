"""CLI 인터페이스 — Typer 기반 대화/명령어 모드."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from config.settings import get_settings
from core.input_guard import InputSource
from core.model_router import ModelRouter
from core.orchestrator import Orchestrator
from core.session_store import Session, delete_session, list_sessions
from core.skills import delete_skill, get_skill, list_skills as _list_skills, save_skill

app = typer.Typer(help="CLI 대화/명령어 모드")
model_app = typer.Typer(help="모델 관리")
memory_app = typer.Typer(help="메모리 관리")
session_app = typer.Typer(help="세션 관리")
skill_app = typer.Typer(help="스킬 관리")
profile_app = typer.Typer(help="사용자 장기 프로필 관리")
routing_app = typer.Typer(help="상황별 모델 자동 라우팅 설정")
app.add_typer(model_app, name="model")
app.add_typer(memory_app, name="memory")
app.add_typer(session_app, name="session")
app.add_typer(skill_app, name="skill")
app.add_typer(profile_app, name="profile")
app.add_typer(routing_app, name="routing")


# ── 라우팅 설정 ────────────────────────────────────────────


@routing_app.command("show")
def routing_show() -> None:
    """현재 라우팅 전략 + 규칙 출력."""
    from core.router_strategy import load_config
    cfg = load_config()
    typer.echo(f"strategy: {cfg['strategy']}")
    typer.echo(f"rules ({len(cfg['rules'])}개):")
    for i, r in enumerate(cfg["rules"]):
        match = r.get("match", {})
        out = f"  [{i}] "
        parts = [f"{k}={v}" for k, v in match.items()]
        out += ", ".join(parts) if parts else "(empty)"
        if r.get("prefer_model"):
            out += f"  → model={r['prefer_model']}"
        if r.get("prefer_agent"):
            out += f"  → agent={r['prefer_agent']}"
        typer.echo(out)


@routing_app.command("enable")
def routing_enable() -> None:
    """auto 모드 활성화."""
    from core.router_strategy import save_config
    save_config(strategy="auto")
    typer.echo("✓ auto 라우팅 활성 — 매 요청마다 규칙 평가")


@routing_app.command("disable")
def routing_disable() -> None:
    """manual 모드 (현재 선택된 모델만 사용)."""
    from core.router_strategy import save_config
    save_config(strategy="manual")
    typer.echo("✓ manual 모드 — 라우팅 비활성")


@routing_app.command("add")
def routing_add(
    model: str = typer.Option("", "--model", "-m", help="prefer_model"),
    agent: str = typer.Option("", "--agent", "-a", help="prefer_agent"),
    contains: str = typer.Option("", "--contains", help="키워드 쉼표 구분 (contains_any)"),
    min_messages: int = typer.Option(0, "--min-messages", help="min_messages 임계값"),
    token_gt: int = typer.Option(0, "--token-gt", help="token_estimate_gt"),
    token_lt: int = typer.Option(0, "--token-lt", help="token_estimate_lt"),
    match_agent: str = typer.Option("", "--match-agent", help="현재 에이전트가 이 값과 같을 때만"),
    default: bool = typer.Option(False, "--default", help="fallback 규칙 (모든 조건 무시, 맨 뒤에 추가)"),
    position: int = typer.Option(-1, "--position", help="삽입 위치 (기본: 맨 뒤)"),
) -> None:
    """라우팅 규칙 추가. 예: raphael cli routing add --contains 리뷰,분석 -m claude-sonnet"""
    from core.router_strategy import load_config, save_config
    cfg = load_config()

    match: dict = {}
    if contains:
        match["contains_any"] = [k.strip() for k in contains.split(",") if k.strip()]
    if min_messages > 0:
        match["min_messages"] = min_messages
    if token_gt > 0:
        match["token_estimate_gt"] = token_gt
    if token_lt > 0:
        match["token_estimate_lt"] = token_lt
    if match_agent:
        match["agent"] = match_agent
    if default:
        match = {"default": True}

    if not match:
        typer.echo("조건을 하나 이상 지정하세요 (--contains/--min-messages/--token-gt/--token-lt/--match-agent/--default)")
        raise typer.Exit(1)

    rule: dict = {"match": match}
    if model:
        rule["prefer_model"] = model
    if agent:
        rule["prefer_agent"] = agent
    if not model and not agent:
        typer.echo("-m 또는 -a 중 하나는 지정해야 합니다.")
        raise typer.Exit(1)

    rules = cfg["rules"]
    if position < 0 or position > len(rules):
        rules.append(rule)
    else:
        rules.insert(position, rule)
    save_config(rules=rules)
    typer.echo(f"✓ 규칙 추가됨 ({len(rules)}개): match={match}, model={model or '-'}, agent={agent or '-'}")


@routing_app.command("remove")
def routing_remove(index: int = typer.Argument(..., help="규칙 인덱스 (show 로 확인)")) -> None:
    from core.router_strategy import load_config, save_config
    cfg = load_config()
    rules = cfg["rules"]
    if not (0 <= index < len(rules)):
        typer.echo(f"인덱스 범위 밖: 0..{len(rules) - 1}")
        raise typer.Exit(1)
    removed = rules.pop(index)
    save_config(rules=rules)
    typer.echo(f"✓ 삭제됨 [{index}]: {removed.get('match')}")


@routing_app.command("clear")
def routing_clear(yes: bool = typer.Option(False, "--yes", "-y")) -> None:
    from core.router_strategy import load_config, save_config
    cfg = load_config()
    if not yes and not typer.confirm(f"정말 {len(cfg['rules'])}개 규칙을 모두 삭제할까요?"):
        return
    save_config(rules=[])
    typer.echo("✓ 모든 규칙 삭제")


@routing_app.command("test")
def routing_test(
    text: str = typer.Argument(..., help="테스트할 사용자 입력"),
    agent: str = typer.Option("coding", "--agent"),
    messages: int = typer.Option(1, "--messages"),
) -> None:
    """어떤 규칙이 매칭되고 어떤 모델/에이전트로 라우팅되는지 미리보기 (실제 호출 안함)."""
    from core.router_strategy import RouterStrategy, TaskContext
    strat = RouterStrategy()
    ctx = TaskContext(user_input=text, agent=agent, messages_count=messages)
    if strat.strategy != "auto":
        typer.echo(f"strategy가 '{strat.strategy}'입니다. 'raphael cli routing enable' 로 auto 활성화 필요.")
        return
    decision = strat.decide(ctx)
    typer.echo(f"입력: {text[:60]}...")
    typer.echo(f"  에이전트(입력): {agent}  메시지수: {messages}")
    if decision.model_key or decision.agent_name:
        typer.echo(f"  → model: {decision.model_key or '(유지)'}")
        typer.echo(f"  → agent: {decision.agent_name or '(유지)'}")
        typer.echo(f"  rule:  {decision.rule_name}")
    else:
        typer.echo("  → 매칭 규칙 없음 (기본 모델/에이전트 사용)")


@profile_app.command("show")
def profile_show() -> None:
    """저장된 프로필 facts 출력."""
    from core.profile import Profile
    p = Profile.load()
    if not p.facts:
        typer.echo("저장된 프로필이 없습니다. 'raphael cli profile add \"...\"' 또는 대화 중 'remember' 도구로 추가됩니다.")
        return
    for f in p.facts:
        typer.echo(f"  [{f.id}] {f.text}  ({f.source}, {f.added})")


@profile_app.command("add")
def profile_add(text: str = typer.Argument(...)) -> None:
    from core.profile import Profile
    p = Profile.load()
    f = p.add(text, source="cli")
    typer.echo(f"기억됨: [{f.id}] {f.text}")


@profile_app.command("forget")
def profile_forget(pattern: str = typer.Argument(...)) -> None:
    from core.profile import Profile
    p = Profile.load()
    n = p.forget(pattern)
    typer.echo(f"{n}개 fact 삭제됨")


@profile_app.command("clear")
def profile_clear(yes: bool = typer.Option(False, "--yes", "-y")) -> None:
    from core.profile import Profile
    p = Profile.load()
    if not yes and not typer.confirm(f"정말 {len(p.facts)}개 fact를 모두 삭제할까요?"):
        return
    n = p.clear()
    typer.echo(f"{n}개 fact 모두 삭제됨")

# 전역 상태 — main.py에서 초기화
_router: ModelRouter | None = None
_orchestrator: Orchestrator | None = None


def init(router: ModelRouter, orchestrator: Orchestrator) -> None:
    """CLI에 라우터와 오케스트레이터를 연결한다."""
    global _router, _orchestrator
    _router = router
    _orchestrator = orchestrator


# ── 대화 모드 ──────────────────────────────────────────────


@app.command()
def chat(
    agent: str = typer.Option("", help="사용할 에이전트 이름"),
    resume: str = typer.Option("", "--resume", help="이어갈 세션 ID"),
    cont: bool = typer.Option(False, "--continue", help="가장 최근 세션 이어가기"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="실시간 진행 출력 끄기 (최종 응답만)"),
) -> None:
    """대화 모드 시작. 기본은 실시간 진행 표시(thinking/tools/tokens). -q로 끄기."""
    verbose = not quiet
    settings = get_settings()

    # 세션 로드 또는 새로 생성
    session: Session | None = None
    if resume:
        session = Session.load(resume)
        if session is None:
            typer.echo(f"세션을 찾을 수 없습니다: {resume}")
            raise typer.Exit(1)
        typer.echo(f"세션 재개: {session.id} (agent={session.agent})")
    elif cont:
        session = Session.latest()
        if session is None:
            typer.echo("이어갈 세션이 없습니다. 새로 시작합니다.")
        else:
            typer.echo(f"최근 세션 재개: {session.id} (agent={session.agent})")

    if session is None:
        session = Session.new(agent or (_orchestrator.default_agent.name if _orchestrator.default_agent else "coding"))

    target_agent_name = agent or session.agent
    resolved_agent = _orchestrator.get_agent(target_agent_name)

    # 저장된 대화 복원
    if session.conversation:
        resolved_agent._conversation = list(session.conversation)

    typer.echo(f"Raphael v{settings['raphael']['version']} — 대화 모드")
    typer.echo(f"세션 ID: {session.id} | 모델: {_router.current_key} | 에이전트: {target_agent_name}")
    typer.echo("종료: quit / exit / Ctrl+C  |  슬래시 명령: /help")
    if _router.current_key == "gemma4-e2b":
        typer.echo("⚠ gemma4-e2b는 도구 호출 형식이 약합니다. /model gemma4-e4b 또는 /model claude-haiku 권장.\n")
    else:
        typer.echo("")

    # prompt_toolkit 입력 (멀티라인 편집/이전 명령 히스토리/커서 이동 안정)
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import FileHistory
        hist_file = Path.home() / ".raphael" / "cli_history"
        hist_file.parent.mkdir(parents=True, exist_ok=True)
        pt_session = PromptSession(history=FileHistory(str(hist_file)))

        def _read_input() -> str:
            return pt_session.prompt("You > ")
    except ImportError:
        def _read_input() -> str:
            return typer.prompt("You", prompt_suffix=" > ")

    try:
        while True:
            try:
                user_input = _read_input()
            except (EOFError, KeyboardInterrupt):
                raise
            stripped = user_input.strip()
            if stripped.lower() in ("quit", "exit"):
                break

            # ── 인라인 슬래시 명령 ──────────────────────────
            if stripped.startswith("/"):
                parts = stripped[1:].split(maxsplit=1)
                cmd = parts[0].lower() if parts else ""
                arg = parts[1] if len(parts) > 1 else ""
                handled = True
                if cmd == "help":
                    typer.echo(
                        "  /agent X      에이전트 전환\n"
                        "  /model X      모델 전환\n"
                        "  /skill X      스킬 적용\n"
                        "  /save         현재 세션 저장\n"
                        "  /clear        대화 초기화\n"
                        "  /verbose on|off  진행 표시 토글\n"
                        "  /quit         종료"
                    )
                elif cmd == "agent" and arg:
                    try:
                        target_agent_name = arg
                        resolved_agent = _orchestrator.get_agent(arg)
                        typer.echo(f"에이전트 전환: {arg}")
                    except ValueError as e:
                        typer.echo(f"오류: {e}")
                elif cmd == "model" and arg:
                    try:
                        _router.switch_model(arg)
                        typer.echo(f"모델 전환: {arg}")
                    except ValueError as e:
                        typer.echo(f"오류: {e}")
                elif cmd == "skill" and arg:
                    sk = get_skill(arg)
                    if sk is None:
                        typer.echo(f"스킬 없음: {arg}")
                    else:
                        resolved_agent.system_prompt += sk.to_system_addendum()
                        typer.echo(f"스킬 적용됨: {arg}")
                elif cmd == "save":
                    session.conversation = list(resolved_agent._conversation)
                    session.save()
                    typer.echo(f"저장됨: {session.id}")
                elif cmd == "clear":
                    resolved_agent.clear_conversation()
                    session.conversation = []
                    typer.echo("대화 초기화됨")
                elif cmd == "verbose":
                    if arg in ("on", "off"):
                        verbose = (arg == "on")
                        typer.echo(f"verbose {arg}")
                    else:
                        typer.echo(f"verbose: {'on' if verbose else 'off'} (사용: /verbose on|off)")
                elif cmd in ("quit", "exit"):
                    break
                else:
                    handled = False

                if handled:
                    continue

            try:
                response = asyncio.run(
                    _orchestrator.route(
                        user_input,
                        agent_name=target_agent_name,
                        source=InputSource.CLI,
                        verbose=verbose,
                    )
                )
                # verbose 시 stderr 마지막 줄이 prompt와 충돌하지 않도록 명시 개행
                import sys as _sys
                if verbose:
                    print("", file=_sys.stderr, flush=True)
                    typer.echo("")  # stdout에도 빈 줄로 prompt 격리
                else:
                    typer.echo(f"\nRaphael > {response}\n")
            except Exception as e:
                typer.echo(f"\n오류: {e}\n")

            # 세션 저장
            session.conversation = list(resolved_agent._conversation)
            session.save()

    except (KeyboardInterrupt, EOFError):
        typer.echo("\n대화 종료.")

    session.conversation = list(resolved_agent._conversation)

    # 세션 자동 태깅 (LLM에 짧게 요약 요청)
    try:
        if not session.tags and len(session.conversation) > 2:
            user_turns = [m["content"] for m in session.conversation if m.get("role") == "user"][:5]
            if user_turns:
                prompt = (
                    "아래 사용자 질문들을 분석해 핵심 토픽 태그를 1~3개 영문 소문자(공백은 _)로만 답해. "
                    "예: python,debug,refactor\n\n질문:\n" + "\n".join(f"- {q[:200]}" for q in user_turns)
                )
                tag_resp = asyncio.run(_router.chat(
                    [{"role": "user", "content": prompt}],
                    options={"temperature": 0.2},
                ))
                tags_text = tag_resp.get("message", {}).get("content", "").strip()
                tags = [t.strip().lower() for t in tags_text.replace("\n", ",").split(",") if t.strip()][:5]
                session.tags = tags
    except Exception:
        pass

    session.save()
    typer.echo(f"세션 저장됨: {session.id} (tags={session.tags})")


@app.command()
def ask(
    question: str = typer.Argument(..., help="질문"),
    agent: str = typer.Option("", help="에이전트"),
    json_output: bool = typer.Option(False, "--json", help="JSON 형식으로 출력"),
    resume: str = typer.Option("", "--resume", help="이어갈 세션 ID"),
    cont: bool = typer.Option(False, "--continue", help="가장 최근 세션 이어가기"),
    skill: str = typer.Option("", "--skill", help="적용할 스킬 이름"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="실시간 진행 출력 끄기"),
    image: list[str] = typer.Option([], "--image", help="첨부 이미지 파일 경로 (vision 모델 필요)"),
) -> None:
    """단발성 질문. --image로 이미지 첨부 (vision 모델 필요)."""
    # json 출력 모드에서는 stderr 혼선 피하기 위해 자동 quiet
    verbose = (not quiet) and (not json_output)
    import time
    session: Session | None = None
    if resume:
        session = Session.load(resume)
    elif cont:
        session = Session.latest()

    target_agent = agent or (session.agent if session else "")
    resolved_agent = _orchestrator.get_agent(
        target_agent or (_orchestrator.default_agent.name if _orchestrator.default_agent else "coding")
    )

    if session and session.conversation:
        resolved_agent._conversation = list(session.conversation)

    # 스킬 적용: 시스템 프롬프트에 덧붙임 (이 호출에 한해 임시)
    _saved_system = resolved_agent.system_prompt
    if skill:
        sk = get_skill(skill)
        if sk is None:
            typer.echo(f"스킬 '{skill}'를 찾을 수 없습니다.")
            raise typer.Exit(1)
        resolved_agent.system_prompt = _saved_system + sk.to_system_addendum()
        # conversation이 비어있으면 시스템 메시지 재설정
        if not resolved_agent._conversation or resolved_agent._conversation[0]["role"] != "system":
            resolved_agent._conversation.insert(0, {"role": "system", "content": resolved_agent.system_prompt})

    tokens_before = _router.get_token_stats()
    start = time.monotonic()
    error_msg: str | None = None
    try:
        route_kwargs = {
            "agent_name": (target_agent or None),
            "source": InputSource.CLI,
            "verbose": verbose,
        }
        if image:
            route_kwargs["images"] = list(image)
        response = asyncio.run(_orchestrator.route(question, **route_kwargs))
    except Exception as e:
        response = f"오류: {e}"
        error_msg = str(e)
    duration = round(time.monotonic() - start, 3)

    # 세션 저장 (resume/continue 경로라면)
    if session is not None:
        session.conversation = list(resolved_agent._conversation)
        session.save()

    # 스킬 임시 주입 원복
    if skill:
        resolved_agent.system_prompt = _saved_system

    # 터미널 + verbose 면 토큰 스트림으로 이미 응답 봤으므로 stdout 중복 생략
    import sys as _sys
    skip_stdout = verbose and _sys.stdout.isatty() and not json_output

    if json_output:
        import json as _json
        tokens_after = _router.get_token_stats()
        # diff
        token_diff = {}
        for model, after in tokens_after.items():
            before = tokens_before.get(model, {"prompt": 0, "completion": 0, "calls": 0})
            token_diff[model] = {
                "prompt": after["prompt"] - before["prompt"],
                "completion": after["completion"] - before["completion"],
                "calls": after["calls"] - before["calls"],
            }
        payload = {
            "response": response,
            "agent": resolved_agent.name,
            "model": _router.current_key,
            "duration_seconds": duration,
            "tokens": token_diff,
            "error": error_msg,
            "session_id": session.id if session else None,
        }
        typer.echo(_json.dumps(payload, ensure_ascii=False, indent=2))
    elif skip_stdout:
        # 토큰 스트림으로 이미 출력됨 — 마지막 개행만 보장
        typer.echo("", err=False)
    else:
        typer.echo(response)


# ── 모델 관리 ──────────────────────────────────────────────


@model_app.command("list")
def model_list() -> None:
    """사용 가능한 모델 목록."""
    for key, cfg in _router.list_models().items():
        marker = "*" if key == _router.current_key else " "
        typer.echo(f"  {marker} {key}: {cfg['description']} ({cfg['vram']})")


@model_app.command("use")
def model_use(model_key: str = typer.Argument(..., help="모델 키")) -> None:
    """모델 전환."""
    try:
        cfg = _router.switch_model(model_key)
        typer.echo(f"모델 전환 완료: {model_key} ({cfg['name']})")
    except ValueError as e:
        typer.echo(f"오류: {e}")


@model_app.command("status")
def model_status() -> None:
    """현재 모델 + Ollama 서버 상태."""
    health = asyncio.run(_router.health_check())
    typer.echo(f"Ollama: {health['status']} ({health['ollama_url']})")
    typer.echo(f"Current: {_router.current_key} → {_router.current_model_name}")


# ── 세션 관리 ──────────────────────────────────────────────


@session_app.command("list")
def session_list() -> None:
    """저장된 세션 목록."""
    sessions = list_sessions()
    if not sessions:
        typer.echo("저장된 세션이 없습니다.")
        return
    for s in sessions:
        typer.echo(f"  {s['id']}  [{s['agent']}]  {s['updated']}  turns={s['turns']}  | {s['preview']}")


@session_app.command("show")
def session_show(session_id: str = typer.Argument(..., help="세션 ID")) -> None:
    """세션 전체 대화 출력."""
    s = Session.load(session_id)
    if s is None:
        typer.echo(f"세션을 찾을 수 없습니다: {session_id}")
        raise typer.Exit(1)
    typer.echo(f"# 세션 {s.id} (agent={s.agent}, updated={s.updated})\n")
    for m in s.conversation:
        typer.echo(f"[{m['role']}] {m['content']}\n")


@session_app.command("delete")
def session_delete(session_id: str = typer.Argument(..., help="세션 ID")) -> None:
    """세션 삭제."""
    if delete_session(session_id):
        typer.echo(f"삭제됨: {session_id}")
    else:
        typer.echo(f"존재하지 않음: {session_id}")


@session_app.command("search")
def session_search(query: str = typer.Argument(...), n: int = typer.Option(5, "--n")) -> None:
    """모든 세션 대화에서 의미 검색."""
    from memory.conversation_index import ConversationIndex
    idx = ConversationIndex(_router)
    hits = asyncio.run(idx.search(query, n))
    if not hits:
        typer.echo("결과 없음. 'raphael cli session reindex'로 인덱스를 먼저 만들어보세요.")
        return
    for h in hits:
        typer.echo(f"  [{h.session_id}] ({h.role}, dist={h.distance:.3f}) {h.content[:120]}")


@session_app.command("reindex")
def session_reindex() -> None:
    """모든 세션을 검색 인덱스에 추가."""
    from memory.conversation_index import ConversationIndex
    idx = ConversationIndex(_router)
    n = asyncio.run(idx.index_all())
    typer.echo(f"인덱싱된 메시지: {n}")


@session_app.command("export")
def session_export(
    session_id: str = typer.Argument(..., help="세션 ID"),
    fmt: str = typer.Option("markdown", "--format", help="markdown 또는 json"),
) -> None:
    """세션을 마크다운/JSON으로 내보내기."""
    s = Session.load(session_id)
    if s is None:
        typer.echo(f"세션을 찾을 수 없습니다: {session_id}")
        raise typer.Exit(1)
    if fmt == "json":
        import json as _json
        typer.echo(_json.dumps(s.__dict__, ensure_ascii=False, indent=2))
    else:
        lines = [f"# Raphael 세션 {s.id}\n", f"에이전트: {s.agent}  |  {s.updated}\n"]
        for m in s.conversation:
            role = m["role"]
            content = m["content"]
            if role == "user":
                lines.append(f"\n## 🧑 User\n\n{content}\n")
            elif role == "assistant":
                lines.append(f"\n## 🤖 {s.agent}\n\n{content}\n")
            else:
                lines.append(f"\n*{role}*: {content[:200]}\n")
        typer.echo("\n".join(lines))


# ── 스킬 관리 ──────────────────────────────────────────────


@skill_app.command("list")
def skill_list() -> None:
    """설치된 스킬 목록."""
    skills = _list_skills()
    if not skills:
        typer.echo("스킬이 없습니다. raphael cli skill create 로 추가하세요.")
        return
    for s in skills:
        agent_tag = f" [{s.agent}]" if s.agent else ""
        typer.echo(f"  {s.name}{agent_tag}: {s.description}")


@skill_app.command("show")
def skill_show(name: str = typer.Argument(...)) -> None:
    """스킬 본문 출력."""
    s = get_skill(name)
    if s is None:
        typer.echo(f"스킬을 찾을 수 없습니다: {name}")
        raise typer.Exit(1)
    typer.echo(f"# {s.name}\n{s.description}\nagent: {s.agent}\ntags: {s.tags}\n\n{s.prompt}")


@skill_app.command("create")
def skill_create(
    name: str = typer.Argument(...),
    description: str = typer.Option("", "--description", "-d"),
    agent: str = typer.Option("", "--agent", "-a", help="기본 적용 에이전트 (선택)"),
) -> None:
    """대화형으로 스킬 생성."""
    typer.echo("스킬 본문(시스템 프롬프트)을 입력하세요. 빈 줄 두 번이면 종료:")
    lines = []
    blank = 0
    while True:
        try:
            line = input()
        except EOFError:
            break
        if not line.strip():
            blank += 1
            if blank >= 2:
                break
            lines.append(line)
            continue
        blank = 0
        lines.append(line)
    body = "\n".join(lines).strip()
    if not body:
        typer.echo("본문이 비어있어 취소되었습니다.")
        raise typer.Exit(1)
    path = save_skill(name, description, body, agent=agent)
    typer.echo(f"스킬 저장됨: {path}")


@skill_app.command("delete")
def skill_delete(name: str = typer.Argument(...)) -> None:
    if delete_skill(name):
        typer.echo(f"삭제됨: {name}")
    else:
        typer.echo(f"존재하지 않음: {name}")


# ── 메모리 관리 ────────────────────────────────────────────


@memory_app.command("index")
def memory_index() -> None:
    """옵시디언 볼트 인덱싱."""
    typer.echo("메모리 인덱싱은 Phase 2 연결 후 사용 가능합니다.")


@memory_app.command("search")
def memory_search(query: str = typer.Argument(..., help="검색 쿼리")) -> None:
    """RAG 검색 테스트."""
    typer.echo("메모리 검색은 Phase 2 연결 후 사용 가능합니다.")
