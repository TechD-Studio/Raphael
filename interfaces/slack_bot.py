"""Slack 봇 인터페이스 (Socket Mode).

설정:
  interfaces:
    slack:
      enabled: true
      bot_token: "${SLACK_BOT_TOKEN}"     # xoxb-
      app_token: "${SLACK_APP_TOKEN}"     # xapp-
      allowed_users: ["U12345"]
"""

from __future__ import annotations

from loguru import logger

from config.settings import get_settings
from core.input_guard import InputSource
from core.model_router import ModelRouter
from core.orchestrator import Orchestrator


class SlackBot:
    def __init__(self, router: ModelRouter, orchestrator: Orchestrator) -> None:
        self.router = router
        self.orchestrator = orchestrator
        self.settings = get_settings()
        cfg = self.settings.get("interfaces", {}).get("slack", {})
        self.allowed_users: set[str] = set(cfg.get("allowed_users") or [])

    def run(self) -> None:
        try:
            from slack_bolt import App
            from slack_bolt.adapter.socket_mode import SocketModeHandler
        except ImportError:
            logger.error("slack_bolt 미설치. pip install slack-bolt")
            return

        cfg = self.settings.get("interfaces", {}).get("slack", {})
        bot_token = cfg.get("bot_token")
        app_token = cfg.get("app_token")
        if not bot_token or bot_token.startswith("$"):
            logger.warning("Slack bot_token 미설정")
            return

        app = App(token=bot_token)

        @app.event("app_mention")
        def on_mention(event, say):
            user = event.get("user", "")
            if self.allowed_users and user not in self.allowed_users:
                say(f"⛔ 권한 없음 (user_id={user})")
                return
            text = event.get("text", "").split(">", 1)[-1].strip()
            channel = event.get("channel", "")
            try:
                import asyncio
                response = asyncio.run(self.orchestrator.route(
                    text, source=InputSource.EXTERNAL, session_id=f"sk:{channel}",
                ))
                say(response)
            except Exception as e:
                say(f"오류: {e}")

        if app_token and not app_token.startswith("$"):
            logger.info("Slack 봇 시작 (Socket Mode)")
            SocketModeHandler(app, app_token).start()
        else:
            logger.warning("Slack app_token 미설정 (Socket Mode 사용 불가)")
