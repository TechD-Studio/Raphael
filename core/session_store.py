"""CLI 세션 영속화 — 대화 히스토리를 JSON 파일로 저장/복원.

세션 파일: ~/.raphael/sessions/<session_id>.json
구조:
  {
    "id": "abc123",
    "agent": "coding",
    "created": "2026-04-15T00:00:00",
    "updated": "2026-04-15T00:05:12",
    "conversation": [...]
  }
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from loguru import logger


def sessions_dir() -> Path:
    """세션 저장소 경로. 환경변수 RAPHAEL_SESSIONS_DIR 로 오버라이드 가능."""
    import os
    base = os.environ.get("RAPHAEL_SESSIONS_DIR")
    if base:
        path = Path(base)
    else:
        path = Path.home() / ".raphael" / "sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class Session:
    id: str
    agent: str
    created: str
    updated: str
    conversation: list[dict]
    tags: list[str] = None  # 자동 태깅 결과 (없으면 None)

    def __post_init__(self):
        if self.tags is None:
            self.tags = []

    @classmethod
    def new(cls, agent: str) -> "Session":
        now = datetime.now().isoformat(timespec="seconds")
        return cls(
            id=uuid.uuid4().hex[:12],
            agent=agent,
            created=now,
            updated=now,
            conversation=[],
        )

    def save(self) -> Path:
        self.updated = datetime.now().isoformat(timespec="seconds")
        path = sessions_dir() / f"{self.id}.json"
        path.write_text(
            json.dumps(self.__dict__, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    @classmethod
    def load(cls, session_id: str) -> "Session | None":
        path = sessions_dir() / f"{session_id}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(**data)

    @classmethod
    def latest(cls) -> "Session | None":
        """가장 최근에 업데이트된 세션을 반환 (--continue용)."""
        files = sorted(sessions_dir().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            return None
        try:
            data = json.loads(files[0].read_text(encoding="utf-8"))
            return cls(**data)
        except Exception as e:
            logger.warning(f"최근 세션 로드 실패: {e}")
            return None


def list_sessions() -> list[dict]:
    """저장된 세션 요약 목록을 반환한다."""
    out = []
    for p in sorted(sessions_dir().glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            first_user = next(
                (m["content"] for m in data.get("conversation", []) if m.get("role") == "user"),
                "(대화 없음)",
            )
            out.append({
                "id": data["id"],
                "agent": data["agent"],
                "updated": data.get("updated", ""),
                "turns": sum(1 for m in data.get("conversation", []) if m.get("role") == "user"),
                "preview": first_user[:60],
            })
        except Exception:
            continue
    return out


def delete_session(session_id: str) -> bool:
    path = sessions_dir() / f"{session_id}.json"
    if path.exists():
        path.unlink()
        return True
    return False
