"""macOS 메뉴바 앱 / Linux 시스템 트레이.

macOS: rumps
Linux: pystray (Pillow 필요)

클릭 시 빠른 채팅 입력창. 백그라운드에서 health API/web도 실행 가능.
"""

from __future__ import annotations

import platform
import threading
import webbrowser
from loguru import logger


def run_tray(orchestrator, router) -> None:
    system = platform.system()
    if system == "Darwin":
        _run_macos(orchestrator, router)
    else:
        _run_pystray(orchestrator, router)


def _run_macos(orchestrator, router) -> None:
    try:
        import rumps
    except ImportError:
        logger.error("rumps 미설치 (pip install rumps)")
        return

    class RaphaelTray(rumps.App):
        def __init__(self):
            super().__init__("R", quit_button="종료")
            self.menu = ["빠른 질문", "웹 UI 열기", "현재 모델", None]

        @rumps.clicked("빠른 질문")
        def quick(self, _):
            response = rumps.Window(
                message="질문을 입력하세요",
                title="Raphael 빠른 질문",
                dimensions=(400, 100),
            ).run()
            if response.clicked and response.text:
                import asyncio
                from core.input_guard import InputSource
                ans = asyncio.run(orchestrator.route(
                    response.text, source=InputSource.CLI, session_id="tray:quick"
                ))
                rumps.alert("Raphael", ans[:1500])

        @rumps.clicked("웹 UI 열기")
        def open_web(self, _):
            webbrowser.open("http://localhost:7860")

        @rumps.clicked("현재 모델")
        def show_model(self, _):
            rumps.alert("현재 모델", router.current_key)

    RaphaelTray().run()


def _run_pystray(orchestrator, router) -> None:
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        logger.error("pystray/Pillow 미설치 (pip install pystray Pillow)")
        return

    img = Image.new("RGB", (64, 64), "navy")
    d = ImageDraw.Draw(img)
    d.text((20, 20), "R", fill="white")

    def open_web(icon, item):
        webbrowser.open("http://localhost:7860")

    def quit_app(icon, item):
        icon.stop()

    icon = pystray.Icon("raphael", img, "Raphael", menu=pystray.Menu(
        pystray.MenuItem("웹 UI 열기", open_web),
        pystray.MenuItem("종료", quit_app),
    ))
    icon.run()
