"""음성 입출력 인터페이스.

TTS: macOS `say`, Linux `espeak`/`spd-say`
STT: whisper.cpp 또는 openai-whisper 라이브러리 (있으면)
"""

from __future__ import annotations

import asyncio
import platform
import shutil
import tempfile
from pathlib import Path

from loguru import logger

from core.input_guard import InputSource


async def tts_speak(text: str) -> str:
    """텍스트를 OS TTS로 발화."""
    system = platform.system()
    if system == "Darwin":
        cmd = ["say", text]
    elif system == "Linux":
        for t in ("spd-say", "espeak"):
            if shutil.which(t):
                cmd = [t, text]
                break
        else:
            return "TTS 도구 미설치 (apt install espeak 또는 speech-dispatcher)"
    else:
        return f"TTS 미지원 OS: {system}"

    proc = await asyncio.create_subprocess_exec(*cmd)
    await proc.communicate()
    return "발화 완료"


def stt_transcribe(audio_path: str) -> str:
    """오디오 파일을 텍스트로. whisper 설치 시 사용."""
    try:
        import whisper  # type: ignore
    except ImportError:
        return "whisper 미설치 (pip install openai-whisper)"
    model = whisper.load_model("base")
    result = model.transcribe(audio_path)
    return result["text"]


async def voice_session(orchestrator, listen_seconds: int = 5) -> None:
    """간이 음성 대화 — 마이크 녹음 → STT → 에이전트 → TTS.

    의존: sox 또는 ffmpeg (마이크 녹음용).
    """
    if not (shutil.which("sox") or shutil.which("ffmpeg") or shutil.which("rec")):
        logger.error("녹음 도구 없음 (brew install sox 또는 apt install sox)")
        return

    print("🎙  말씀하세요... (Ctrl+C로 종료)")
    while True:
        try:
            tmp = tempfile.mktemp(suffix=".wav")
            # sox로 5초 녹음
            cmd = ["rec", "-q", tmp, "trim", "0", str(listen_seconds)]
            proc = await asyncio.create_subprocess_exec(*cmd)
            await proc.communicate()

            text = stt_transcribe(tmp)
            Path(tmp).unlink(missing_ok=True)
            if not text.strip():
                continue
            print(f"🧑 {text}")
            response = await orchestrator.route(text, source=InputSource.CLI)
            print(f"🤖 {response}")
            await tts_speak(response)
        except KeyboardInterrupt:
            print("\n음성 세션 종료")
            break
        except Exception as e:
            logger.error(f"음성 루프 오류: {e}")
            break
