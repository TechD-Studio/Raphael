"""Audit log — 모든 도구 실행을 변조 방지 해시 체인으로 기록.

저장: ~/.raphael/audit.log (JSONL)
각 엔트리: {ts, type, agent, session, data, prev_hash, hash}
verify: hash 체인 무결성 검증.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path


def audit_path() -> Path:
    p = os.environ.get("RAPHAEL_AUDIT_LOG")
    if p:
        return Path(p).expanduser()
    return Path.home() / ".raphael" / "audit.log"


def _last_hash(path: Path) -> str:
    if not path.exists():
        return "0" * 64
    last = ""
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            last = line
    if not last.strip():
        return "0" * 64
    try:
        entry = json.loads(last)
        return entry.get("hash", "0" * 64)
    except Exception:
        return "0" * 64


def _hash(prev: str, payload: dict) -> str:
    raw = prev + "|" + json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def append(event_type: str, data: dict, agent: str = "", session: str = "") -> None:
    """audit log에 한 줄 추가."""
    path = audit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    prev = _last_hash(path)
    payload = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "type": event_type,
        "agent": agent,
        "session": session,
        "data": data,
    }
    h = _hash(prev, payload)
    payload["prev_hash"] = prev
    payload["hash"] = h
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def verify() -> tuple[bool, int, str]:
    """체인 무결성 검증. (정상여부, 검증된 줄 수, 메시지) 반환."""
    path = audit_path()
    if not path.exists():
        return True, 0, "audit log 없음"
    prev = "0" * 64
    n = 0
    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                return False, n, f"line {i}: JSON 파싱 실패"
            if entry.get("prev_hash") != prev:
                return False, n, f"line {i}: prev_hash 불일치"
            payload = {k: entry[k] for k in ("ts", "type", "agent", "session", "data") if k in entry}
            expected = _hash(prev, payload)
            if entry.get("hash") != expected:
                return False, n, f"line {i}: hash 위변조 감지"
            prev = entry["hash"]
            n += 1
    return True, n, "OK"


def show(since_lines: int = 50) -> list[dict]:
    """최근 N줄 반환."""
    path = audit_path()
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()[-since_lines:]
    out = []
    for l in lines:
        try:
            out.append(json.loads(l))
        except Exception:
            continue
    return out
