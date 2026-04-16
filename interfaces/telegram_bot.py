"""텔레그램 봇 인터페이스.

보안:
- settings.interfaces.telegram.allowed_users 목록의 user_id만 허용
- 사용자별 세션(chat_id)으로 대화 분리
- 긴 응답은 4000자 청크로 분할 전송
- 응답 생성 중 "타이핑 중..." 표시
"""

from __future__ import annotations

from loguru import logger
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config.settings import get_settings
from core.input_guard import InputSource
from core.model_router import ModelRouter
from core.orchestrator import Orchestrator

# 텔레그램 메시지 상한 4096자. 여유 두고 4000자로 분할.
MAX_TELEGRAM_MSG = 4000


class TelegramBot:
    """텔레그램 봇."""

    def __init__(self, router: ModelRouter, orchestrator: Orchestrator) -> None:
        self.router = router
        self.orchestrator = orchestrator
        self.settings = get_settings()
        cfg = self.settings["interfaces"]["telegram"]
        self.allowed_users: set[int] = set(cfg.get("allowed_users") or [])
        # 세션별 verbose 모드 ({session_id: bool})
        self._verbose_mode: dict[str, bool] = {}

    # ── 권한 ──────────────────────────────────────────────

    def _is_authorized(self, update: Update) -> bool:
        user = update.effective_user
        if not user:
            return False
        if not self.allowed_users:
            return False  # 빈 목록 = 모두 거부
        return user.id in self.allowed_users

    async def _reject(self, update: Update) -> None:
        user = update.effective_user
        uid = user.id if user else "?"
        logger.warning(f"텔레그램 미허가 접근: user_id={uid}")
        if update.message:
            await update.message.reply_text(
                f"⛔ 권한이 없습니다. 당신의 user_id: {uid}\n"
                "소유자에게 연락해 settings.yaml의 telegram.allowed_users에 추가하도록 요청하세요."
            )

    # ── 세션 ID ────────────────────────────────────────────

    @staticmethod
    def _session_id(update: Update) -> str:
        """chat_id 기반 세션 (1:1 DM은 user_id == chat_id, 그룹은 chat_id)."""
        chat = update.effective_chat
        return f"tg:{chat.id}" if chat else "tg:unknown"

    # ── 긴 메시지 분할 ─────────────────────────────────────

    @staticmethod
    def _chunk(text: str, size: int = MAX_TELEGRAM_MSG) -> list[str]:
        if len(text) <= size:
            return [text]
        out = []
        i = 0
        while i < len(text):
            chunk = text[i : i + size]
            # 가능하면 줄바꿈 경계에서 자름
            if len(chunk) == size and "\n" in chunk:
                nl = chunk.rfind("\n")
                if nl > size // 2:
                    chunk = chunk[:nl]
            out.append(chunk)
            i += len(chunk)
        return out

    async def _send_chunked(self, update: Update, text: str) -> None:
        for i, chunk in enumerate(self._chunk(text)):
            prefix = f"({i+1}/_)" if len(text) > MAX_TELEGRAM_MSG else ""
            if prefix:
                chunk = prefix + "\n" + chunk
            await update.message.reply_text(chunk)

    # ── 핸들러 ─────────────────────────────────────────────

    async def _start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            await self._reject(update)
            return
        await update.message.reply_text(
            f"Raphael v{self.settings['raphael']['version']}\n"
            f"모델: {self.router.current_key}\n\n"
            "명령어: /status, /model, /agent, /reset, /settings, /verbose"
        )

    async def _status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            await self._reject(update)
            return
        health = await self.router.health_check()
        agents = [a["name"] for a in self.orchestrator.list_agents()]
        await update.message.reply_text(
            f"Ollama: {health['status']}\n"
            f"Model: {self.router.current_key}\n"
            f"Agents: {', '.join(agents)}\n"
            f"Session: {self._session_id(update)}"
        )

    async def _model_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            await self._reject(update)
            return
        args = context.args or []
        if not args or args[0] == "list":
            models = self.router.list_models()
            lines = [f"{'*' if k == self.router.current_key else ' '} {k}" for k in models]
            await update.message.reply_text("\n".join(lines))
        elif args[0] == "use" and len(args) > 1:
            try:
                self.router.switch_model(args[1])
                await update.message.reply_text(f"모델 전환: {args[1]}")
            except ValueError as e:
                await update.message.reply_text(str(e))
        elif args[0] == "status":
            health = await self.router.health_check()
            await update.message.reply_text(f"{health['status']} — {self.router.current_key}")

    async def _agent_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            await self._reject(update)
            return
        agents = self.orchestrator.list_agents()
        lines = [f"- {a['name']}: {a['description']}" for a in agents]
        await update.message.reply_text("\n".join(lines))

    async def _reset(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            await self._reject(update)
            return
        self.orchestrator.reset_session(self._session_id(update))
        await update.message.reply_text("대화 기록을 초기화했습니다.")

    async def _verbose_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """진행 로그 표시 토글. /verbose on | off | status"""
        if not self._is_authorized(update):
            await self._reject(update)
            return
        sid = self._session_id(update)
        args = context.args or []
        if not args or args[0] == "status":
            on = self._verbose_mode.get(sid, False)
            await update.message.reply_text(f"진행 로그: {'켜짐' if on else '꺼짐'}\n사용: /verbose on | off")
            return
        if args[0] == "on":
            self._verbose_mode[sid] = True
            await update.message.reply_text("✓ 진행 로그 켜짐 — 이제 🧠 thinking, 🔧 도구 실행 등 중간 과정을 전송합니다.")
        elif args[0] == "off":
            self._verbose_mode[sid] = False
            await update.message.reply_text("✓ 진행 로그 꺼짐 — 최종 응답만 전송합니다.")
        else:
            await update.message.reply_text("사용: /verbose on | off | status")

    async def _settings_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """설정 변경. /settings <key> [value]"""
        if not self._is_authorized(update):
            await self._reject(update)
            return
        args = context.args or []
        if not args:
            await update.message.reply_text(
                "사용법:\n"
                "/settings model <key> — 기본 모델 변경\n"
                "/settings escalation on|off — 자동 에스컬레이션 토글\n"
                "/settings server <host> [port] — Ollama 서버 변경\n"
                "/settings default_agent <name> — 기본 에이전트 변경\n"
                "/settings show — 현재 설정 표시"
            )
            return
        sub = args[0].lower()
        from config.settings import get_settings, save_local_settings, reload_settings

        if sub == "show":
            s = get_settings()
            m = s.get("models", {})
            o = m.get("ollama", {})
            ladder = m.get("escalation_ladder", [])
            await update.message.reply_text(
                f"기본 모델: {m.get('default', '?')}\n"
                f"서버: {o.get('host', 'localhost')}:{o.get('port', 11434)}\n"
                f"에스컬레이션: {'→'.join(ladder) if ladder else 'OFF'}\n"
                f"기본 에이전트: {self.orchestrator._default_agent}"
            )
        elif sub == "model" and len(args) > 1:
            key = args[1]
            try:
                self.router.switch_model(key)
                save_local_settings({"models": {"default": key}})
                reload_settings()
                await update.message.reply_text(f"✓ 기본 모델 → {key}")
            except ValueError as e:
                await update.message.reply_text(f"✗ {e}")
        elif sub == "escalation" and len(args) > 1:
            if args[1].lower() == "off":
                save_local_settings({"models": {"escalation_ladder": []}})
                reload_settings()
                await update.message.reply_text("✓ 에스컬레이션 OFF")
            elif args[1].lower() == "on":
                s = get_settings()
                available = list((s.get("models", {}).get("ollama", {}).get("available") or {}).keys())
                ladder = [k for k in available if not k.startswith("claude")]
                save_local_settings({"models": {"escalation_ladder": ladder}})
                reload_settings()
                await update.message.reply_text(f"✓ 에스컬레이션 ON: {'→'.join(ladder)}")
            else:
                await update.message.reply_text("사용: /settings escalation on|off")
        elif sub == "server" and len(args) > 1:
            host = args[1]
            port = int(args[2]) if len(args) > 2 else 11434
            save_local_settings({"models": {"ollama": {"host": host, "port": port}}})
            reload_settings()
            await update.message.reply_text(f"✓ 서버 → {host}:{port} (재시작 필요)")
        elif sub == "default_agent" and len(args) > 1:
            name = args[1]
            try:
                self.orchestrator.set_default(name)
                await update.message.reply_text(f"✓ 기본 에이전트 → {name}")
            except ValueError as e:
                await update.message.reply_text(f"✗ {e}")
        else:
            await update.message.reply_text("알 수 없는 설정. /settings 로 도움말 확인")

    async def _message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            await self._reject(update)
            return

        user_input = update.message.text
        sid = self._session_id(update)
        verbose = self._verbose_mode.get(sid, False)

        try:
            await context.bot.send_chat_action(
                chat_id=update.effective_chat.id,
                action=ChatAction.TYPING,
            )
        except Exception:
            pass

        # verbose ON이면 주요 이벤트를 중간 메시지로 전송
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
                # 비동기 전송을 현재 루프 태스크로 스케줄 (fire-and-forget)
                _asyncio.create_task(self._safe_send(update, text))

        try:
            response = await self.orchestrator.route(
                user_input,
                source=InputSource.TELEGRAM,
                session_id=sid,
                activity_callback=on_event if verbose else None,
            )
        except Exception as e:
            logger.error(f"텔레그램 메시지 처리 오류: {e}")
            response = f"오류: {e}"

        await self._send_chunked(update, response)

    async def _safe_send(self, update: Update, text: str) -> None:
        try:
            await update.message.reply_text(text)
        except Exception as e:
            logger.debug(f"중간 메시지 전송 실패(무시): {e}")

    def run(self) -> None:
        token = self.settings["interfaces"]["telegram"]["token"]
        if not token or token.startswith("$"):
            logger.warning("텔레그램 봇 토큰이 설정되지 않았습니다.")
            return

        if not self.allowed_users:
            logger.warning(
                "텔레그램 봇: allowed_users가 비어있어 모든 요청을 거부합니다. "
                "settings.yaml의 interfaces.telegram.allowed_users에 user_id를 추가하세요."
            )

        app = Application.builder().token(token).build()
        app.add_handler(CommandHandler("start", self._start))
        app.add_handler(CommandHandler("status", self._status))
        app.add_handler(CommandHandler("model", self._model_cmd))
        app.add_handler(CommandHandler("agent", self._agent_cmd))
        app.add_handler(CommandHandler("reset", self._reset))
        app.add_handler(CommandHandler("verbose", self._verbose_cmd))
        app.add_handler(CommandHandler("settings", self._settings_cmd))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._message))

        logger.info(f"텔레그램 봇 시작 (허용 사용자 수: {len(self.allowed_users)})")
        app.run_polling()
