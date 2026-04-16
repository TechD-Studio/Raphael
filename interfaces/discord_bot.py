"""디스코드 봇 인터페이스.

보안:
- settings.interfaces.discord.allowed_users 목록의 user_id만 허용
- 사용자별(또는 channel별) 세션으로 대화 분리
- 긴 응답은 2000자 청크로 분할 전송
- 응답 생성 중 "typing..." 표시
"""

from __future__ import annotations

import discord
from discord.ext import commands
from loguru import logger

from config.settings import get_settings
from core.input_guard import InputSource
from core.model_router import ModelRouter
from core.orchestrator import Orchestrator

MAX_DISCORD_MSG = 1900  # 2000 한도에서 여유


class DiscordBot:
    """디스코드 봇."""

    def __init__(self, router: ModelRouter, orchestrator: Orchestrator) -> None:
        self.router = router
        self.orchestrator = orchestrator
        self.settings = get_settings()
        cfg = self.settings["interfaces"]["discord"]
        self.allowed_users: set[int] = set(cfg.get("allowed_users") or [])
        self._verbose_mode: dict[str, bool] = {}

        intents = discord.Intents.default()
        intents.message_content = True
        self.bot = commands.Bot(command_prefix="/", intents=intents)

        self._register_commands()
        self._register_events()

    # ── 권한 ──────────────────────────────────────────────

    def _is_authorized(self, user: discord.User | discord.Member) -> bool:
        if not self.allowed_users:
            return False
        return int(user.id) in self.allowed_users

    @staticmethod
    def _session_id(ctx_or_message) -> str:
        """채널 ID 기반 세션 (DM은 channel.id가 곧 user)."""
        channel = getattr(ctx_or_message, "channel", None)
        if channel:
            return f"dc:{channel.id}"
        return "dc:unknown"

    # ── 긴 메시지 분할 ─────────────────────────────────────

    @staticmethod
    def _chunk(text: str, size: int = MAX_DISCORD_MSG) -> list[str]:
        if len(text) <= size:
            return [text]
        out = []
        i = 0
        while i < len(text):
            chunk = text[i : i + size]
            if len(chunk) == size and "\n" in chunk:
                nl = chunk.rfind("\n")
                if nl > size // 2:
                    chunk = chunk[:nl]
            out.append(chunk)
            i += len(chunk)
        return out

    # ── 명령어 ────────────────────────────────────────────

    def _register_commands(self) -> None:
        bot = self.bot

        @bot.command(name="status")
        async def status_cmd(ctx: commands.Context) -> None:
            if not self._is_authorized(ctx.author):
                await ctx.send(f"⛔ 권한 없음. user_id={ctx.author.id}")
                return
            health = await self.router.health_check()
            agents = [a["name"] for a in self.orchestrator.list_agents()]
            await ctx.send(
                f"**Raphael**\nOllama: {health['status']}\n"
                f"Model: {self.router.current_key}\n"
                f"Agents: {', '.join(agents)}\n"
                f"Session: {self._session_id(ctx)}"
            )

        @bot.command(name="model")
        async def model_cmd(ctx: commands.Context, sub: str = "list", key: str = "") -> None:
            if not self._is_authorized(ctx.author):
                await ctx.send(f"⛔ 권한 없음")
                return
            if sub == "list":
                models = self.router.list_models()
                lines = []
                for k, c in models.items():
                    marker = "**" if k == self.router.current_key else ""
                    lines.append(f"{marker}{k}{marker}: {c['description']}")
                await ctx.send("\n".join(lines))
            elif sub == "use" and key:
                try:
                    self.router.switch_model(key)
                    await ctx.send(f"모델 전환: {key}")
                except ValueError as e:
                    await ctx.send(str(e))

        @bot.command(name="agent")
        async def agent_cmd(ctx: commands.Context) -> None:
            if not self._is_authorized(ctx.author):
                await ctx.send(f"⛔ 권한 없음")
                return
            agents = self.orchestrator.list_agents()
            lines = [f"- **{a['name']}**: {a['description']}" for a in agents]
            await ctx.send("\n".join(lines))

        @bot.command(name="reset")
        async def reset_cmd(ctx: commands.Context) -> None:
            if not self._is_authorized(ctx.author):
                await ctx.send(f"⛔ 권한 없음")
                return
            self.orchestrator.reset_session(self._session_id(ctx))
            await ctx.send("대화 기록을 초기화했습니다.")

        @bot.command(name="verbose")
        async def verbose_cmd(ctx: commands.Context, sub: str = "status") -> None:
            if not self._is_authorized(ctx.author):
                await ctx.send(f"⛔ 권한 없음")
                return
            sid = self._session_id(ctx)
            if sub == "status":
                on = self._verbose_mode.get(sid, False)
                await ctx.send(f"진행 로그: {'켜짐' if on else '꺼짐'}\n사용: `/verbose on` | `/verbose off`")
            elif sub == "on":
                self._verbose_mode[sid] = True
                await ctx.send("✓ 진행 로그 켜짐 — 🧠 thinking, 🔧 도구 실행 등 중간 과정 전송")
            elif sub == "off":
                self._verbose_mode[sid] = False
                await ctx.send("✓ 진행 로그 꺼짐 — 최종 응답만 전송")
            else:
                await ctx.send("사용: `/verbose on` | `/verbose off` | `/verbose status`")

        @bot.command(name="settings")
        async def settings_cmd(ctx: commands.Context, sub: str = "", val: str = "", val2: str = "") -> None:
            if not self._is_authorized(ctx.author):
                await ctx.send("⛔ 권한 없음")
                return
            from config.settings import get_settings, save_local_settings, reload_settings

            if not sub or sub == "help":
                await ctx.send(
                    "사용법:\n"
                    "`/settings show` — 현재 설정\n"
                    "`/settings model <key>` — 기본 모델 변경\n"
                    "`/settings escalation on|off` — 에스컬레이션 토글\n"
                    "`/settings server <host> [port]` — Ollama 서버\n"
                    "`/settings default_agent <name>` — 기본 에이전트"
                )
            elif sub == "show":
                s = get_settings()
                m = s.get("models", {})
                o = m.get("ollama", {})
                ladder = m.get("escalation_ladder", [])
                await ctx.send(
                    f"모델: {m.get('default', '?')}\n"
                    f"서버: {o.get('host', 'localhost')}:{o.get('port', 11434)}\n"
                    f"에스컬레이션: {'→'.join(ladder) if ladder else 'OFF'}"
                )
            elif sub == "model" and val:
                try:
                    self.router.switch_model(val)
                    save_local_settings({"models": {"default": val}})
                    reload_settings()
                    await ctx.send(f"✓ 모델 → {val}")
                except ValueError as e:
                    await ctx.send(f"✗ {e}")
            elif sub == "escalation":
                if val.lower() == "off":
                    save_local_settings({"models": {"escalation_ladder": []}})
                    reload_settings()
                    await ctx.send("✓ 에스컬레이션 OFF")
                elif val.lower() == "on":
                    s = get_settings()
                    available = list((s.get("models", {}).get("ollama", {}).get("available") or {}).keys())
                    ladder = [k for k in available if not k.startswith("claude")]
                    save_local_settings({"models": {"escalation_ladder": ladder}})
                    reload_settings()
                    await ctx.send(f"✓ 에스컬레이션 ON: {'→'.join(ladder)}")
                else:
                    await ctx.send("사용: `/settings escalation on|off`")
            elif sub == "server" and val:
                port = int(val2) if val2 else 11434
                save_local_settings({"models": {"ollama": {"host": val, "port": port}}})
                reload_settings()
                await ctx.send(f"✓ 서버 → {val}:{port}")
            elif sub == "default_agent" and val:
                try:
                    self.orchestrator.set_default(val)
                    await ctx.send(f"✓ 기본 에이전트 → {val}")
                except ValueError as e:
                    await ctx.send(f"✗ {e}")
            else:
                await ctx.send("알 수 없는 설정. `/settings help`")

    # ── 이벤트 ─────────────────────────────────────────────

    def _register_events(self) -> None:
        bot = self.bot

        @bot.event
        async def on_ready() -> None:
            logger.info(f"디스코드 봇 로그인: {bot.user} (허용 사용자: {len(self.allowed_users)})")

        @bot.event
        async def on_message(message: discord.Message) -> None:
            if message.author == bot.user:
                return
            if message.content.startswith("/"):
                await bot.process_commands(message)
                return

            mentioned = bot.user in message.mentions
            is_dm = isinstance(message.channel, discord.DMChannel)
            if not (mentioned or is_dm):
                return

            if not self._is_authorized(message.author):
                await message.reply(f"⛔ 권한 없음. user_id={message.author.id}")
                return

            content = message.content.replace(f"<@{bot.user.id}>", "").strip()
            if not content:
                return

            sid = self._session_id(message)
            verbose = self._verbose_mode.get(sid, False)
            import asyncio as _asyncio

            def on_event(entry: dict) -> None:
                if not verbose:
                    return
                t = entry.get("type")
                data = entry.get("data", {})
                text: str | None = None
                if t == "model_call_start":
                    it = data.get("iteration", 1)
                    it_str = f" (반복 {it})" if it > 1 else ""
                    text = f"🧠 thinking... {data.get('model', '?')}{it_str}"
                elif t == "tool_call":
                    args = data.get("args", {})
                    args_str = ", ".join(f"{k}={v!r}" for k, v in list(args.items())[:2])
                    text = f"🔧 {data.get('name', '?')}({args_str[:120]})"
                elif t == "tool_result":
                    icon = "✗" if data.get("error") else "✓"
                    out = (data.get("output") or "")[:120].replace("\n", " ")
                    text = f"{icon} {data.get('name', '?')}: {out}"
                if text:
                    async def _send(t=text):
                        try:
                            await message.channel.send(t)
                        except Exception as e:
                            logger.debug(f"중간 메시지 전송 실패: {e}")
                    _asyncio.create_task(_send())

            async with message.channel.typing():
                try:
                    response = await self.orchestrator.route(
                        content,
                        source=InputSource.DISCORD,
                        session_id=sid,
                        activity_callback=on_event if verbose else None,
                    )
                except Exception as e:
                    logger.error(f"디스코드 메시지 오류: {e}")
                    response = f"오류: {e}"

            for chunk in self._chunk(response):
                await message.reply(chunk)

    def run(self) -> None:
        token = self.settings["interfaces"]["discord"]["token"]
        if not token or token.startswith("$"):
            logger.warning("디스코드 봇 토큰이 설정되지 않았습니다.")
            return
        if not self.allowed_users:
            logger.warning(
                "디스코드 봇: allowed_users가 비어있어 모든 요청을 거부합니다. "
                "settings.yaml의 interfaces.discord.allowed_users에 user_id를 추가하세요."
            )
        logger.info("디스코드 봇 시작")
        self.bot.run(token)
