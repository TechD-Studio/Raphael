"""사용자 피드백 — 응답 평가 기록.

저장: ~/.raphael/feedback.jsonl
구조: {ts, session, agent, question, response, score, comment}
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path


def feedback_path() -> Path:
    p = os.environ.get("RAPHAEL_FEEDBACK_LOG")
    return Path(p).expanduser() if p else Path.home() / ".raphael" / "feedback.jsonl"


def record(session: str, agent: str, question: str, response: str, score: int, comment: str = "") -> None:
    """score: +1 (좋음) / -1 (나쁨) / 0 (중립)"""
    path = feedback_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "session": session,
        "agent": agent,
        "question": question[:500],
        "response": response[:500],
        "score": int(score),
        "comment": comment,
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def stats() -> dict:
    path = feedback_path()
    if not path.exists():
        return {"total": 0, "positive": 0, "negative": 0, "neutral": 0}
    counts = {"total": 0, "positive": 0, "negative": 0, "neutral": 0}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
            counts["total"] += 1
            s = e.get("score", 0)
            if s > 0:
                counts["positive"] += 1
            elif s < 0:
                counts["negative"] += 1
            else:
                counts["neutral"] += 1
        except Exception:
            pass
    return counts
