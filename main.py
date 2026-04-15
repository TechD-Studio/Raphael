"""Raphael — AI 에이전트 프레임워크 엔트리포인트."""

from __future__ import annotations

import sys

import typer
from loguru import logger

from config.settings import (
    get_current_onboard_values,
    get_settings,
    save_env,
    save_local_settings,
)
from core.model_router import ModelRouter
from core.orchestrator import Orchestrator
from agents.coding_agent import CodingAgent
from agents.research_agent import ResearchAgent
from agents.note_agent import NoteAgent
from agents.task_agent import TaskAgent
from agents.planner_agent import PlannerAgent
from agents.reviewer_agent import ReviewerAgent
from interfaces import cli as cli_module
from tools.tool_registry import create_default_registry

app = typer.Typer(
    name="raphael",
    help="Raphael AI Agent Framework — 인자 없이 실행하면 대화 모드로 진입합니다.",
    invoke_without_command=True,
    no_args_is_help=False,
)

# CLI 서브그룹 마운트
app.add_typer(cli_module.app, name="cli")


def _setup_logging() -> None:
    settings = get_settings()
    log_cfg = settings.get("logging", {})
    level = log_cfg.get("level", "INFO")
    log_file = log_cfg.get("file", "./logs/raphael.log")

    logger.remove()
    logger.add(sys.stderr, level=level, format="<level>{level:<8}</level> | {message}")
    logger.add(log_file, level=level, rotation="10 MB", retention="7 days")


def _init() -> tuple[ModelRouter, Orchestrator]:
    """코어 모듈을 초기화하고 에이전트를 등록한다.

    동적 에이전트(~/.raphael/agents/*.md)를 우선 로드.
    하위 호환을 위해 기존 하드코딩 에이전트도 등록 (이름 충돌 시 동적 우선).
    """
    router = ModelRouter()
    orchestrator = Orchestrator(router=router)

    registry = create_default_registry()
    registry.register("_orchestrator", orchestrator, "내부 오케스트레이터 참조 (delegate용)")

    # 기본 에이전트 md 자동 설치 (첫 실행)
    from core.agent_definitions import (
        install_defaults_if_empty, list_definitions, GenericAgent
    )
    install_defaults_if_empty()

    # 동적 에이전트 등록
    registered = set()
    for d in list_definitions():
        try:
            agent = GenericAgent.from_definition(d, router, tool_registry=registry)
            orchestrator.register(agent)
            registered.add(d.name)
        except Exception as e:
            logger.warning(f"에이전트 '{d.name}' 등록 실패: {e}")

    # main을 기본 에이전트로
    if "main" in registered:
        orchestrator.set_default("main")

    # 하위 호환 — 기존 하드코딩 에이전트 (md에 동일 이름이 있으면 스킵)
    for cls, name in [
        (CodingAgent, "coding"), (ResearchAgent, "research"),
        (NoteAgent, "note"), (TaskAgent, "task"),
        (PlannerAgent, "planner"), (ReviewerAgent, "reviewer"),
    ]:
        if name not in registered:
            try:
                orchestrator.register(cls(router, tool_registry=registry))
            except Exception:
                pass

    # 플러그인 자동 로드 (raphael.tools / raphael.agents entry_points)
    try:
        from core.plugin_loader import load_tool_plugins, load_agent_plugins
        load_tool_plugins(registry)
        load_agent_plugins(orchestrator, router, registry)
    except Exception as e:
        logger.debug(f"플러그인 로드 스킵: {e}")

    cli_module.init(router, orchestrator)
    return router, orchestrator


@app.callback()
def main_callback(ctx: typer.Context) -> None:
    """Raphael AI Agent Framework. 인자 없이 실행하면 바로 대화 모드."""
    _setup_logging()
    _init()

    # 하위 명령어가 지정되지 않았으면 자동으로 cli chat 진입
    # 기본 동작 변경: 마지막 세션이 있으면 자동 이어가기 (--continue 상응)
    if ctx.invoked_subcommand is None:
        from core.session_store import Session as _Sess
        _cont = _Sess.latest() is not None
        cli_module.chat(agent="", resume="", cont=_cont, quiet=False)
        raise typer.Exit()


@app.command("web")
def run_web() -> None:
    """웹 UI 시작."""
    from interfaces.web_ui import WebUI
    web = WebUI(cli_module._router, cli_module._orchestrator)
    web.launch()


@app.command("telegram")
def run_telegram() -> None:
    """텔레그램 봇 시작."""
    from interfaces.telegram_bot import TelegramBot
    bot = TelegramBot(cli_module._router, cli_module._orchestrator)
    bot.run()


@app.command("log")
def run_log(
    follow: bool = typer.Option(False, "--follow", "-f", help="tail -f 처럼 실시간 추적"),
    tail: int = typer.Option(20, "--tail", "-n", help="최근 N줄 출력"),
    session: str = typer.Option("", "--session", help="특정 세션만 필터"),
    no_color: bool = typer.Option(False, "--no-color", help="색상 끄기"),
) -> None:
    """활동 로그 출력 (CLI/웹/봇의 모든 에이전트 이벤트 통합)."""
    import json
    import time as _time
    from core.activity_log import format_entry, log_path

    path = log_path()
    if not path.exists():
        typer.echo(f"활동 로그가 아직 없습니다: {path}")
        typer.echo("에이전트 호출이 발생하면 자동 생성됩니다.")
        raise typer.Exit(0)

    def _print_line(line: str) -> None:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            return
        if session and entry.get("session") != session:
            return
        typer.echo(format_entry(entry, color=not no_color))

    # 최근 N줄
    lines = path.read_text(encoding="utf-8").splitlines()[-tail:]
    for line in lines:
        _print_line(line)

    if follow:
        typer.echo("\n── follow 모드 (Ctrl+C로 종료) ──", err=True)
        try:
            with open(path, "r", encoding="utf-8") as f:
                f.seek(0, 2)  # 끝으로 이동
                while True:
                    line = f.readline()
                    if line:
                        _print_line(line.rstrip())
                    else:
                        _time.sleep(0.3)
        except KeyboardInterrupt:
            typer.echo("\n종료.", err=True)


@app.command("watch")
def run_watch_cmd() -> None:
    """settings.yaml의 hooks.watches 규칙에 따라 파일 변경을 감시하고 에이전트를 자동 호출한다."""
    from interfaces.file_watcher import run_watch
    run_watch(cli_module._orchestrator)


@app.command("health")
def run_health(
    host: str = typer.Option("127.0.0.1", help="바인딩 주소"),
    port: int = typer.Option(7861, help="포트"),
) -> None:
    """헬스/메트릭 HTTP API 시작 (/health, /metrics, /tokens, /agents)."""
    from interfaces.health_api import run_health_server
    run_health_server(cli_module._router, cli_module._orchestrator, host=host, port=port)


@app.command("voice")
def run_voice() -> None:
    """음성 대화 모드 (마이크 → STT → 에이전트 → TTS)."""
    import asyncio
    from interfaces.voice import voice_session
    asyncio.run(voice_session(cli_module._orchestrator))


@app.command("tray")
def run_tray_cmd() -> None:
    """시스템 트레이/메뉴바 앱 (macOS rumps / Linux pystray)."""
    from interfaces.tray_app import run_tray
    run_tray(cli_module._orchestrator, cli_module._router)


@app.command("slack")
def run_slack() -> None:
    """Slack 봇 (Socket Mode) 시작."""
    from interfaces.slack_bot import SlackBot
    bot = SlackBot(cli_module._router, cli_module._orchestrator)
    bot.run()


@app.command("discord")
def run_discord() -> None:
    """디스코드 봇 시작."""
    from interfaces.discord_bot import DiscordBot
    bot = DiscordBot(cli_module._router, cli_module._orchestrator)
    bot.run()


@app.command("status")
def show_status() -> None:
    """라파엘 전체 상태 출력."""
    import asyncio

    router = cli_module._router
    orchestrator = cli_module._orchestrator

    async def _print_status() -> None:
        health = await router.health_check()
        settings = get_settings()

        print(f"\n{'='*50}")
        print(f"  Raphael v{settings['raphael']['version']}")
        print(f"{'='*50}")
        print(f"  Ollama: {health['status']} ({health['ollama_url']})")
        print(f"  Model: {router.current_key} → {router.current_model_name}")
        print(f"\n  Models:")
        for key, cfg in router.list_models().items():
            marker = " *" if key == router.current_key else "  "
            print(f"   {marker} {key}: {cfg['description']} ({cfg['vram']})")
        print(f"\n  Agents:")
        for a in orchestrator.list_agents():
            print(f"    - {a['name']}: {a['description']}")
        print(f"{'='*50}\n")

        await router.close()

    asyncio.run(_print_status())


@app.command("parallel")
def run_parallel(
    task: str = typer.Argument(..., help="모든 에이전트에 동시에 던질 질문/작업"),
    agents: str = typer.Option("", "--agents", help="쉼표로 구분된 에이전트 목록. 비우면 전체"),
) -> None:
    """여러 에이전트에 동일 작업을 동시 전달하고 결과를 취합 출력."""
    import asyncio

    orch = cli_module._orchestrator

    if agents:
        agent_names = [a.strip() for a in agents.split(",") if a.strip()]
    else:
        agent_names = [a["name"] for a in orch.list_agents()]

    async def _one(name: str) -> tuple[str, str, float]:
        import time
        from core.input_guard import InputSource
        start = time.monotonic()
        try:
            r = await orch.route(task, agent_name=name, source=InputSource.CLI, session_id=f"parallel-{name}")
            return (name, r, time.monotonic() - start)
        except Exception as e:
            return (name, f"오류: {e}", time.monotonic() - start)

    async def _all():
        return await asyncio.gather(*(_one(n) for n in agent_names))

    typer.echo(f"\n=== {len(agent_names)}개 에이전트 동시 실행: {task[:60]} ===\n")
    results = asyncio.run(_all())

    for name, resp, dur in results:
        typer.echo(f"\n── {name} ({dur:.1f}s) ──")
        typer.echo(resp)

    typer.echo(f"\n=== 완료: {sum(1 for _, r, _ in results if not r.startswith('오류'))}/{len(results)} 성공 ===")


@app.command("secret")
def run_secret(
    action: str = typer.Argument(..., help="set | get | delete"),
    key: str = typer.Argument(...),
    value: str = typer.Argument("", help="set 일 때 값"),
) -> None:
    """OS Keychain에 시크릿 저장/조회/삭제."""
    from core.secrets import set_secret, get_secret, delete_secret
    if action == "set":
        if not value:
            value = typer.prompt(f"{key} 값", hide_input=True)
        backend = set_secret(key, value)
        typer.echo(f"저장됨 (backend={backend})")
    elif action == "get":
        v = get_secret(key)
        typer.echo(v if v else "(없음)")
    elif action == "delete":
        ok = delete_secret(key)
        typer.echo("삭제됨" if ok else "(존재하지 않음)")
    else:
        typer.echo("action: set | get | delete")


@app.command("rollback")
def run_rollback(
    action: str = typer.Argument("list", help="list | restore | cleanup"),
    arg: str = typer.Argument("", help="restore 시 체크포인트 ID, cleanup 시 일수"),
) -> None:
    """파일 작업 체크포인트 관리."""
    from core import checkpoint
    if action == "list":
        for cp in checkpoint.list_checkpoints():
            typer.echo(f"  {cp.id}  [{cp.operation}]  {cp.created}  {cp.target}  {cp.note}")
    elif action == "restore" and arg:
        typer.echo(checkpoint.restore(arg))
    elif action == "cleanup":
        days = int(arg or 7)
        n = checkpoint.cleanup_old(days)
        typer.echo(f"{n}개 체크포인트 삭제됨 (>{days}일)")
    else:
        typer.echo("action: list | restore <id> | cleanup [days]")


@app.command("audit")
def run_audit(
    action: str = typer.Argument("show", help="show | verify"),
    n: int = typer.Option(50, "--tail", help="show 시 최근 N줄"),
) -> None:
    """Audit log 조회/검증."""
    from core import audit
    if action == "verify":
        ok, count, msg = audit.verify()
        typer.echo(f"{'✓' if ok else '✗'} {count}줄 검증 — {msg}")
    elif action == "show":
        for e in audit.show(n):
            typer.echo(f"  {e.get('ts')} [{e.get('type')}] {e.get('data', {})}")
    else:
        typer.echo("action: show | verify")


@app.command("feedback")
def run_feedback_stats() -> None:
    """피드백 통계."""
    from core import feedback
    s = feedback.stats()
    typer.echo(f"전체 {s['total']} | 👍 {s['positive']} | 👎 {s['negative']} | 중립 {s['neutral']}")


@app.command("update")
def run_update() -> None:
    """git pull + pip install -e . 로 자체 업데이트."""
    import subprocess
    from pathlib import Path
    project = Path(__file__).resolve().parent
    typer.echo("git pull...")
    r = subprocess.run(["git", "-C", str(project), "pull"], capture_output=True, text=True)
    typer.echo(r.stdout + r.stderr)
    if r.returncode != 0:
        typer.echo("git pull 실패 — 종료")
        raise typer.Exit(1)
    typer.echo("pip install -e .")
    venv_pip = project / ".venv" / "bin" / "pip"
    pip_cmd = [str(venv_pip)] if venv_pip.exists() else ["pip"]
    r2 = subprocess.run(pip_cmd + ["install", "-e", str(project), "-q"], capture_output=True, text=True)
    typer.echo(r2.stdout + r2.stderr)
    typer.echo("✓ 업데이트 완료" if r2.returncode == 0 else "✗ pip 실패")


agent_app = typer.Typer(help="에이전트 정의 관리 (md 파일)")
app.add_typer(agent_app, name="agent")


@agent_app.command("list")
def agent_list() -> None:
    """정의된 모든 에이전트 + 활성 상태."""
    from core.agent_definitions import list_definitions, load_active_agents
    active = load_active_agents()
    defs = list_definitions()
    if not defs:
        typer.echo("정의된 에이전트가 없습니다.")
        return
    for d in defs:
        mark = "✓" if d.name in active else " "
        model_str = f" [model={d.model}]" if d.model else ""
        typer.echo(f"  [{mark}] {d.name:20} {d.description}{model_str}")
        typer.echo(f"        tools: {d.tools}")


@agent_app.command("show")
def agent_show(name: str = typer.Argument(...)) -> None:
    from core.agent_definitions import get_definition
    d = get_definition(name)
    if not d:
        typer.echo(f"없음: {name}")
        raise typer.Exit(1)
    typer.echo(f"# {d.name}")
    typer.echo(f"description: {d.description}")
    typer.echo(f"tools: {d.tools}")
    typer.echo(f"model: {d.model or '(기본)'}")
    typer.echo(f"path: {d.path}")
    typer.echo(f"\n{d.system_prompt}")


@agent_app.command("create")
def agent_create(
    name: str = typer.Argument(...),
    description: str = typer.Option("", "--description", "-d"),
    tools: str = typer.Option("", "--tools", "-t", help="쉼표 구분"),
    model: str = typer.Option("", "--model", "-m"),
    enabled: bool = typer.Option(False, "--enabled"),
) -> None:
    """새 에이전트 정의 생성. 본문은 입력 모드(빈 줄 두 번 종료)."""
    from core.agent_definitions import AgentDefinition, save_definition, set_enabled
    typer.echo("system prompt 본문 (빈 줄 두 번이면 종료):")
    lines, blank = [], 0
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
        typer.echo("본문 비어있어 취소.")
        raise typer.Exit(1)
    d = AgentDefinition(
        name=name, description=description,
        tools=[t.strip() for t in tools.split(",") if t.strip()],
        model=model or None,
        default_enabled=enabled,
        system_prompt=body,
    )
    path = save_definition(d)
    if enabled:
        set_enabled(name, True)
    typer.echo(f"저장됨: {path}")


@agent_app.command("edit")
def agent_edit(name: str = typer.Argument(...)) -> None:
    """$EDITOR 로 에이전트 md 파일 편집."""
    import os, subprocess
    from core.agent_definitions import get_definition
    d = get_definition(name)
    if not d or not d.path:
        typer.echo(f"없음: {name}")
        raise typer.Exit(1)
    editor = os.environ.get("EDITOR", "vi")
    subprocess.run([editor, str(d.path)])


@agent_app.command("enable")
def agent_enable(name: str = typer.Argument(...)) -> None:
    from core.agent_definitions import get_definition, set_enabled
    if not get_definition(name):
        typer.echo(f"없음: {name}")
        raise typer.Exit(1)
    set_enabled(name, True)
    typer.echo(f"✓ {name} 활성화")


@agent_app.command("disable")
def agent_disable(name: str = typer.Argument(...)) -> None:
    from core.agent_definitions import set_enabled
    set_enabled(name, False)
    typer.echo(f"✓ {name} 비활성화")


@agent_app.command("delete")
def agent_delete(
    name: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    from core.agent_definitions import delete_definition
    if not yes and not typer.confirm(f"정말 '{name}' 에이전트를 삭제할까요?"):
        return
    if delete_definition(name):
        typer.echo(f"✓ 삭제됨: {name}")
    else:
        typer.echo(f"없음: {name}")


@agent_app.command("install")
def agent_install(source: str = typer.Argument(..., help="GitHub raw URL 또는 로컬 .md 경로")) -> None:
    """외부 정의 파일을 ~/.raphael/agents/ 로 가져오기."""
    import shutil, urllib.request
    from pathlib import Path as _P
    from core.agent_definitions import agents_dir, parse_definition

    target_dir = agents_dir()
    if source.startswith(("http://", "https://")):
        try:
            with urllib.request.urlopen(source, timeout=30) as resp:
                content = resp.read().decode("utf-8")
        except Exception as e:
            typer.echo(f"다운로드 실패: {e}")
            raise typer.Exit(1)
        # 파일명 추출
        fname = source.rsplit("/", 1)[-1] or "downloaded.md"
        if not fname.endswith(".md"):
            fname += ".md"
        path = target_dir / fname
        path.write_text(content, encoding="utf-8")
    else:
        src = _P(source).expanduser()
        if not src.exists():
            typer.echo(f"파일 없음: {src}")
            raise typer.Exit(1)
        path = target_dir / src.name
        shutil.copy(src, path)

    # 검증
    d = parse_definition(path)
    if not d:
        path.unlink(missing_ok=True)
        typer.echo("유효한 에이전트 정의 아님 — 삭제됨")
        raise typer.Exit(1)
    typer.echo(f"✓ 설치됨: {d.name} ({path})")
    typer.echo(f"  활성화하려면: raphael agent enable {d.name}")


@agent_app.command("recommend")
def agent_recommend() -> None:
    """사용 패턴 기반 추천 (비활성 + 자주 호출됨)."""
    from core.agent_definitions import load_active_agents, get_recommendations
    recs = get_recommendations(load_active_agents())
    if not recs:
        typer.echo("추천 없음 (사용 패턴 누적 후 확인)")
        return
    for name, reason in recs:
        typer.echo(f"  {name}: {reason}")


@app.command("mcp")
def run_mcp_list() -> None:
    """등록된 MCP 서버와 노출된 도구를 출력."""
    import asyncio
    from core.mcp_client import MCPClientManager

    async def _list():
        mgr = MCPClientManager()
        # registry에 mcp 도구 임시 등록을 위해 빈 registry 생성
        from tools.tool_registry import ToolRegistry
        reg = ToolRegistry()
        await mgr.start(reg)
        items = mgr.list_tools()
        if not items:
            typer.echo("등록된 MCP 서버 없음. settings.yaml의 mcp.servers를 채우세요.")
        else:
            for it in items:
                typer.echo(f"  {it['server']}: {it['tool']}")
        await mgr.stop()

    asyncio.run(_list())


@app.command("pool")
def run_pool_health() -> None:
    """다중 Ollama 서버 풀 상태."""
    import asyncio
    from core.ollama_pool import OllamaPool
    pool = OllamaPool()
    for s in asyncio.run(pool.health_all()):
        typer.echo(f"  {s['name']:12} {s['url']:30} {s['health']:12} active={s['active']} weight={s['weight']} models={s['declared_models']}")
    asyncio.run(pool.close_all())


@app.command("testbench")
def run_testbench(
    scenario: int = typer.Argument(0, help="시나리오 번호 (0 또는 미지정 = 목록)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="확인 없이 바로 실행"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="실시간 진행 표시 끄기"),
) -> None:
    """동적 에이전트 + 도구 통합 테스트 시나리오 자동 실행 (사전 설정 포함)."""
    import asyncio
    from core.testbench import find_scenario, list_scenarios_text, prepare
    from core.input_guard import InputSource

    if scenario == 0:
        typer.echo(list_scenarios_text())
        return

    s = find_scenario(scenario)
    if not s:
        typer.echo(f"시나리오 #{scenario} 없음. raphael testbench (인자 없이)로 목록 확인.")
        raise typer.Exit(1)

    typer.echo(f"\n=== {s.level}  #{s.id}  {s.title} ===")
    typer.echo(f"  {s.description}\n")

    info = prepare(s)
    typer.echo(f"📁 작업 폴더: {info['workspace']}")
    if info["allowed_added"]:
        typer.echo(f"   ↳ allowed_paths에 자동 추가")
    if info["agents_enabled"]:
        typer.echo(f"🤖 활성화된 에이전트: {', '.join(info['agents_enabled'])}")
    if info["agents_missing"]:
        typer.echo(f"⚠ 정의 없는 에이전트: {', '.join(info['agents_missing'])}")
        typer.echo(f"   ↳ 'raphael agent list' 로 확인하세요")

    # 권장 모델 자동 전환 (시나리오마다 최소 모델 명시)
    router = cli_module._router
    saved_model = router.current_key
    if s.recommended_model and s.recommended_model != saved_model:
        try:
            router.switch_model(s.recommended_model)
            typer.echo(f"🧠 모델 자동 전환: {saved_model} → {s.recommended_model}")
        except ValueError:
            typer.echo(f"⚠ 권장 모델 '{s.recommended_model}' 전환 실패 — {saved_model} 사용")

    typer.echo(f"\n📝 프롬프트:\n{info['prompt']}\n")

    if not yes and not typer.confirm("이 작업을 main 에이전트에게 전달할까요?", default=True):
        typer.echo("취소됨.")
        # 원복
        try: router.switch_model(saved_model)
        except Exception: pass
        return

    typer.echo("\n--- 실행 시작 ---")
    try:
        response = asyncio.run(
            cli_module._orchestrator.route(
                info["prompt"],
                agent_name="main",
                source=InputSource.CLI,
                verbose=not quiet,
                session_id=f"testbench-{s.id}",
            )
        )
    finally:
        # 원래 모델로 원복
        try: router.switch_model(saved_model)
        except Exception: pass
    typer.echo("\n--- 결과 ---")
    typer.echo(response)
    typer.echo(f"\n✓ 시나리오 #{s.id} 완료")
    typer.echo(f"  세션: testbench-{s.id} (이어가려면 raphael cli chat --resume testbench-{s.id})")
    typer.echo(f"  활동 로그: raphael log --tail 30")


@app.command("failures")
def show_failures(
    n: int = typer.Option(10, "--n", help="최근 N개"),
    clear: bool = typer.Option(False, "--clear", help="모두 삭제"),
) -> None:
    """수집된 실패 케이스(~/.raphael/failures/) 조회."""
    from pathlib import Path
    d = Path.home() / ".raphael" / "failures"
    if not d.exists():
        typer.echo("실패 케이스 없음.")
        return
    files = sorted(d.glob("*.json"), reverse=True)
    if clear:
        for f in files:
            f.unlink()
        typer.echo(f"🗑 {len(files)}개 삭제됨")
        return
    if not files:
        typer.echo("실패 케이스 없음.")
        return
    typer.echo(f"최근 실패 {min(n, len(files))}건 (전체 {len(files)}건):\n")
    import json
    for f in files[:n]:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            typer.echo(f"  {f.name}")
            typer.echo(f"    model={data.get('model')} reason={data.get('reason')}")
            typer.echo(f"    input: {(data.get('user_input') or '')[:80]}...")
        except Exception as e:
            typer.echo(f"  {f.name} (읽기 실패: {e})")


@app.command("ab-test")
def run_ab_test(
    scenario: int = typer.Argument(..., help="시나리오 번호"),
    models: str = typer.Option("gemma4-e2b,gemma4-e4b,gemma4-26b", "--models", help="쉼표 구분 모델 리스트"),
) -> None:
    """같은 시나리오를 여러 모델로 돌려 성공률 비교. 결과는 ~/.raphael/ab_results/."""
    import asyncio, json, time
    from datetime import datetime
    from pathlib import Path
    from core.testbench import find_scenario, prepare
    from core.input_guard import InputSource

    s = find_scenario(scenario)
    if not s:
        typer.echo(f"시나리오 #{scenario} 없음.")
        raise typer.Exit(1)

    model_list = [m.strip() for m in models.split(",") if m.strip()]
    typer.echo(f"\n=== A/B 테스트: #{s.id} {s.title} ===")
    typer.echo(f"모델: {', '.join(model_list)}\n")

    info = prepare(s)
    router = cli_module._router
    saved = router.current_key
    out_dir = Path.home() / ".raphael" / "ab_results"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    results = []

    # A/B 테스트 중에는 auto-route 끄기 (모델 고정)
    from core.router_strategy import load_config, save_config
    saved_routing = load_config()
    save_config(strategy="manual")
    try:
        for m in model_list:
            typer.echo(f"--- {m} ---")
            try:
                router.switch_model(m)
            except ValueError:
                typer.echo(f"  전환 실패 (미설치?): {m}")
                continue
            start = time.monotonic()
            try:
                response = asyncio.run(
                    cli_module._orchestrator.route(
                        info["prompt"], agent_name="main",
                        source=InputSource.CLI, verbose=False,
                        session_id=f"abtest-{s.id}-{m}",
                    )
                )
                duration = time.monotonic() - start
                # 성공 기준 강화: 응답 길이 + 에러 키워드 부재 + 실제 모델이 고정된 모델
                bad_kw = ("⚠", "실패", "오류", "ESCALATE", "최대 반복", "command not found", "No module named")
                success = (
                    len(response) > 50
                    and all(kw not in response for kw in bad_kw)
                    and router.current_key == m  # 에스컬레이션으로 바뀌지 않았는지
                )
                results.append({"model": m, "success": success, "duration": round(duration, 1),
                                "response_len": len(response),
                                "final_model": router.current_key})
                typer.echo(f"  {'✓' if success else '✗'} {duration:.1f}s  len={len(response)}  final={router.current_key}")
            except Exception as e:
                results.append({"model": m, "success": False, "error": str(e)})
                typer.echo(f"  ✗ 예외: {e}")
    finally:
        save_config(strategy=saved_routing["strategy"], rules=saved_routing["rules"])

    try: router.switch_model(saved)
    except Exception: pass

    out_path = out_dir / f"{ts}_scenario{s.id}.json"
    out_path.write_text(json.dumps(
        {"scenario_id": s.id, "title": s.title, "results": results},
        ensure_ascii=False, indent=2), encoding="utf-8")
    typer.echo(f"\n📊 결과 저장: {out_path}")


@app.command("plan")
def run_plan(
    task: str = typer.Argument(..., help="실행할 작업"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    """planner 에이전트에 작업을 던져 자동 분해/위임/실행."""
    import asyncio
    from core.input_guard import InputSource
    response = asyncio.run(
        cli_module._orchestrator.route(
            task,
            agent_name="planner",
            source=InputSource.CLI,
            verbose=not quiet,
        )
    )
    if quiet:
        typer.echo(response)


@app.command("review")
def run_review(
    context: str = typer.Argument(..., help="검토할 작업 컨텍스트"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    """reviewer 에이전트로 작업 결과 비판적 검토."""
    import asyncio
    from core.input_guard import InputSource
    response = asyncio.run(
        cli_module._orchestrator.route(
            context,
            agent_name="reviewer",
            source=InputSource.CLI,
            verbose=not quiet,
        )
    )
    if quiet:
        typer.echo(response)


@app.command("commit")
def run_commit(
    message: str = typer.Option("", "--message", "-m", help="커밋 메시지. 비우면 AI가 제안"),
    cwd: str = typer.Option(".", "--cwd", help="Git 작업 디렉토리"),
) -> None:
    """스테이지된 변경에 대해 커밋. 메시지를 주지 않으면 AI가 자동 생성."""
    import asyncio
    from tools.git_tool import GitTool

    git = GitTool()

    if not message:
        # 1. staged diff 가져오기
        diff = asyncio.run(git.diff(cwd=cwd, staged=True))
        if "(diff 없음)" in diff or not diff.strip():
            typer.echo("스테이지된 변경이 없습니다. 먼저 git add 하세요.")
            raise typer.Exit(1)

        # 2. LLM에 커밋 메시지 생성 요청
        router = cli_module._router
        prompt = (
            "다음 git diff를 분석하여 커밋 메시지를 작성하라. "
            "형식: 첫 줄은 50자 이내의 요약, 빈 줄, 필요시 상세 설명.\n"
            "영문 imperative mood 권장. 도구 태그는 사용하지 말 것.\n\n"
            f"{diff[:6000]}"
        )
        typer.echo("커밋 메시지 생성 중...")
        result = asyncio.run(router.chat([
            {"role": "system", "content": "너는 Git 커밋 메시지 작성 전문가다."},
            {"role": "user", "content": prompt},
        ]))
        message = result["message"]["content"].strip()
        typer.echo(f"\n제안 메시지:\n{message}\n")
        if not typer.confirm("이 메시지로 커밋할까요?", default=True):
            typer.echo("취소됨.")
            raise typer.Exit(0)

    result = asyncio.run(git.commit(message, cwd=cwd))
    typer.echo(result)


@app.command("onboard")
def onboard() -> None:
    """초기 설정 마법사 — Ollama IP, 봇 토큰, 옵시디언 경로를 설정한다."""
    import asyncio

    current = get_current_onboard_values()

    typer.echo("\n╭──────────────────────────────────────╮")
    typer.echo("│     Raphael 초기 설정 (onboard)      │")
    typer.echo("╰──────────────────────────────────────╯")
    typer.echo("  빈 값 입력 시 현재 설정을 유지합니다.\n")

    # 1. Ollama 서버
    typer.echo("── 1. Ollama 서버 ──")
    ollama_host = typer.prompt(
        f"  Ollama 호스트 IP [{current['ollama_host']}]",
        default="",
        show_default=False,
    ).strip() or current["ollama_host"]

    ollama_port_str = typer.prompt(
        f"  Ollama 포트 [{current['ollama_port']}]",
        default="",
        show_default=False,
    ).strip()
    ollama_port = int(ollama_port_str) if ollama_port_str else current["ollama_port"]

    # 2. 옵시디언 볼트
    typer.echo("\n── 2. 옵시디언 볼트 ──")
    vault_path = typer.prompt(
        f"  볼트 경로 [{current['obsidian_vault']}]",
        default="",
        show_default=False,
    ).strip() or current["obsidian_vault"]

    # 2-1. 파일 접근 허용 경로
    typer.echo("\n── 2-1. 파일 접근 허용 경로 ──")
    typer.echo("  에이전트의 파일 도구가 접근할 경로들 (쉼표로 구분).")
    typer.echo("  빈 값이면 기본: 홈 + /tmp + 현재 작업 디렉토리")
    current_paths = current["allowed_paths"]
    current_display = ", ".join(current_paths) if current_paths else "(기본값)"
    paths_input = typer.prompt(
        f"  허용 경로 [{current_display}]",
        default="",
        show_default=False,
    ).strip()
    if paths_input:
        allowed_paths = [p.strip() for p in paths_input.split(",") if p.strip()]
    else:
        allowed_paths = current_paths

    # 3. 텔레그램
    typer.echo("\n── 3. 텔레그램 봇 (선택) ──")
    tg_display = current["telegram_token"][:8] + "..." if current["telegram_token"] else "미설정"
    telegram_token = typer.prompt(
        f"  봇 토큰 [{tg_display}]",
        default="",
        show_default=False,
    ).strip()

    # 4. 디스코드
    typer.echo("\n── 4. 디스코드 봇 (선택) ──")
    dc_display = current["discord_token"][:8] + "..." if current["discord_token"] else "미설정"
    discord_token = typer.prompt(
        f"  봇 토큰 [{dc_display}]",
        default="",
        show_default=False,
    ).strip()

    # 5. 자동 라우팅
    typer.echo("\n── 5. 상황별 모델 자동 라우팅 (선택) ──")
    typer.echo("  auto 모드면 키워드/길이 등에 따라 claude-sonnet/gemma4-26b 등으로 자동 전환합니다.")
    from core.router_strategy import load_config as _load_routing, save_config as _save_routing
    routing_cur = _load_routing()
    typer.echo(f"  현재: strategy={routing_cur['strategy']}, rules={len(routing_cur['rules'])}개")

    enable_auto = typer.confirm("  auto 라우팅을 활성화할까요?", default=(routing_cur["strategy"] == "auto"))

    new_rules = list(routing_cur["rules"])
    if enable_auto and not new_rules:
        if typer.confirm("  기본 규칙 4개(짧은입력→e2b / 리뷰·분석→claude-sonnet / 큰작업→planner+opus / 기본→e4b)를 만들어드릴까요?", default=True):
            new_rules = [
                {"match": {"token_estimate_lt": 60},
                 "prefer_model": "gemma4-e2b"},
                {"match": {"contains_any": ["리뷰", "분석", "버그", "최적화", "리팩토링"]},
                 "prefer_model": "claude-sonnet"},
                {"match": {"contains_any": ["만들어줘", "전체", "프로젝트", "사이트"],
                           "token_estimate_gt": 150},
                 "prefer_model": "claude-opus", "prefer_agent": "planner"},
                {"match": {"default": True},
                 "prefer_model": "gemma4-e4b"},
            ]

    _save_routing(
        strategy="auto" if enable_auto else "manual",
        rules=new_rules,
    )

    # 저장
    typer.echo("\n저장 중...")

    save_local_settings({
        "models": {"ollama": {"host": ollama_host, "port": ollama_port}},
        "memory": {"obsidian_vault": vault_path},
        "tools": {"file": {"allowed_paths": allowed_paths}},
    })

    if telegram_token:
        save_env("TELEGRAM_BOT_TOKEN", telegram_token)
    if discord_token:
        save_env("DISCORD_BOT_TOKEN", discord_token)

    # 연결 테스트
    from config.settings import reload_settings
    reload_settings()
    router = ModelRouter()

    typer.echo("\n연결 테스트...")
    health = asyncio.run(router.health_check())
    asyncio.run(router.close())

    if health["status"] == "ok":
        typer.echo(f"  Ollama: 연결 성공 ({health['ollama_url']})")
        # 임베딩 모델 체크
        ok, _ = asyncio.run(router.ensure_embedding_model(pull_if_missing=False))
        if ok:
            typer.echo(f"  임베딩 모델: 설치됨")
        else:
            typer.echo(f"  임베딩 모델: 미설치")
            if typer.confirm("  임베딩 모델을 지금 자동으로 설치하시겠습니까? (ollama pull 실행)", default=True):
                typer.echo("  설치 중... (시간이 걸릴 수 있습니다)")
                _, msg2 = asyncio.run(router.ensure_embedding_model(pull_if_missing=True))
                typer.echo(f"  {msg2}")
    else:
        typer.echo(f"  Ollama: {health['status']} ({health['ollama_url']})")
        typer.echo("  -> IP/포트를 확인하거나 Ollama 서버가 실행 중인지 확인하세요.")

    typer.echo(f"  볼트: {vault_path}")
    typer.echo(f"  텔레그램: {'설정됨' if telegram_token or current['telegram_token'] else '미설정'}")
    typer.echo(f"  디스코드: {'설정됨' if discord_token or current['discord_token'] else '미설정'}")
    typer.echo(f"  라우팅: {'auto (' + str(len(new_rules)) + '개 규칙)' if enable_auto else 'manual'}")
    typer.echo("\n설정 완료! `raphael status`로 전체 상태를 확인하세요.")
    if enable_auto:
        typer.echo("         `raphael cli routing show`로 규칙 편집, `raphael web`의 라우팅 탭에서도 편집 가능.\n")
    else:
        typer.echo()


if __name__ == "__main__":
    app()
