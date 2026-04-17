"""계층적 기억 시스템 — Daily Log, Project Context, 성공 패턴.

[2] 단기 기억: ~/.raphael/logs/YYYY-MM-DD.md (오늘 작업 요약)
[3] 장기 기억: ~/.raphael/context.md (프로젝트 컨텍스트)
[4] 학습 기억: ~/.raphael/patterns.md (성공 패턴)
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from loguru import logger


def _raphael_dir() -> Path:
    d = Path.home() / ".raphael"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── [2] Daily Log ──────────────────────────────────────


def _logs_dir() -> Path:
    d = _raphael_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _today_log_path() -> Path:
    return _logs_dir() / f"{datetime.now().strftime('%Y-%m-%d')}.md"


def append_daily_log(entry: str) -> None:
    """오늘의 작업 일지에 항목 추가."""
    p = _today_log_path()
    if not p.exists():
        p.write_text(
            f"# {datetime.now().strftime('%Y-%m-%d')} 작업 일지\n\n",
            encoding="utf-8",
        )
    with open(p, "a", encoding="utf-8") as f:
        ts = datetime.now().strftime("%H:%M")
        f.write(f"- [{ts}] {entry}\n")


def get_daily_log() -> str:
    """오늘의 작업 일지 반환. 없으면 빈 문자열."""
    p = _today_log_path()
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def get_recent_logs(days: int = 3) -> str:
    """최근 N일 작업 일지 반환."""
    parts = []
    d = _logs_dir()
    files = sorted(d.glob("*.md"), reverse=True)[:days]
    for f in files:
        parts.append(f.read_text(encoding="utf-8").strip())
    return "\n\n---\n\n".join(parts)


def summarize_session_for_log(user_input: str, response: str, agent: str, model: str) -> str:
    """세션 턴을 일지 항목으로 요약."""
    q = user_input[:80].replace("\n", " ")
    a_len = len(response)
    return f"{agent}({model}): \"{q}\" → {a_len}자 응답"


# ── [3] Project Context ────────────────────────────────


def _context_path() -> Path:
    return _raphael_dir() / "context.md"


def get_project_context() -> str:
    """프로젝트 컨텍스트 반환."""
    p = _context_path()
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def update_project_context(text: str) -> None:
    """프로젝트 컨텍스트 전체 교체."""
    _context_path().write_text(text, encoding="utf-8")


def append_project_decision(decision: str) -> None:
    """프로젝트 컨텍스트에 결정 사항 추가."""
    p = _context_path()
    if not p.exists():
        p.write_text("# 프로젝트 컨텍스트\n\n## 주요 결정\n\n", encoding="utf-8")
    with open(p, "a", encoding="utf-8") as f:
        ts = datetime.now().strftime("%Y-%m-%d")
        f.write(f"- [{ts}] {decision}\n")


def auto_extract_decisions(user_input: str, response: str) -> list[str]:
    """대화에서 주요 결정 사항을 자동 추출."""
    decisions = []
    decision_markers = [
        "으로 하겠습니다", "로 결정", "으로 진행", "보류하겠습니다",
        "추가해 주세요", "삭제합니다", "변경합니다",
        "decided", "let's go with", "we'll use",
    ]
    combined = user_input + " " + response
    for marker in decision_markers:
        if marker in combined.lower():
            # 마커를 포함하는 문장 추출
            for sentence in re.split(r"[.!?\n]", combined):
                if marker in sentence.lower() and 10 < len(sentence.strip()) < 200:
                    decisions.append(sentence.strip())
                    break
    return decisions[:2]


# ── [4] 성공 패턴 ──────────────────────────────────────


def _patterns_path() -> Path:
    return _raphael_dir() / "patterns.md"


def get_success_patterns() -> str:
    """성공 패턴 반환."""
    p = _patterns_path()
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def learn_from_feedback() -> str:
    """피드백 +1 받은 응답에서 패턴 추출."""
    feedback_path = _raphael_dir() / "feedback.jsonl"
    if not feedback_path.exists():
        return ""

    positive = []
    for line in feedback_path.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
            if e.get("score", 0) > 0:
                q = e.get("question", "")[:100]
                a = e.get("response", "")[:200]
                if q and a:
                    positive.append({"q": q, "a": a})
        except Exception:
            pass

    if not positive:
        return ""

    patterns = ["## 성공 패턴 (피드백 +1 기반)\n"]
    for p in positive[-10:]:
        patterns.append(f"- Q: {p['q']}\n  A(요약): {p['a'][:100]}")

    text = "\n".join(patterns)
    _patterns_path().write_text(f"# 성공 패턴\n\n{text}\n", encoding="utf-8")
    return text


# ── 통합 컨텍스트 빌더 ─────────────────────────────────


def build_memory_context(max_chars: int = 2000) -> str:
    """에이전트 시스템 프롬프트에 주입할 기억 컨텍스트 조합."""
    parts = []

    ctx = get_project_context()
    if ctx:
        parts.append(ctx[:600])

    log = get_daily_log()
    if log:
        lines = log.strip().split("\n")
        recent = "\n".join(lines[:1] + lines[-8:])
        parts.append(recent[:600])

    patterns = get_success_patterns()
    if patterns:
        lines = patterns.strip().split("\n")
        parts.append("\n".join(lines[-6:])[:400])

    combined = "\n\n".join(parts)
    if len(combined) > max_chars:
        combined = combined[:max_chars] + "\n..."
    return combined
