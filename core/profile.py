"""사용자 장기 프로필 메모리 — facts.json 영속 저장.

모든 에이전트의 system_prompt에 자동 주입되어 매 세션 다시 알려줄 필요 없음.

저장 위치: ~/.raphael/facts.json (RAPHAEL_PROFILE_PATH로 오버라이드)
구조:
  {
    "facts": [
      {"id": "abc12", "text": "사용자 dh는 Python 개발자", "added": "2026-04-15", "source": "tool|onboard|cli"}
    ]
  }
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from loguru import logger


def profile_path() -> Path:
    p = os.environ.get("RAPHAEL_PROFILE_PATH")
    if p:
        return Path(p).expanduser()
    return Path.home() / ".raphael" / "facts.json"


@dataclass
class Fact:
    id: str
    text: str
    added: str
    source: str = "tool"


@dataclass
class Profile:
    facts: list[Fact] = field(default_factory=list)

    @classmethod
    def load(cls) -> "Profile":
        path = profile_path()
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            facts = [Fact(**f) for f in data.get("facts", [])]
            return cls(facts=facts)
        except Exception as e:
            logger.warning(f"profile 로드 실패: {e}")
            return cls()

    def save(self) -> None:
        path = profile_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"facts": [f.__dict__ for f in self.facts]}
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, text: str, source: str = "tool") -> Fact:
        text = text.strip()
        if not text:
            raise ValueError("빈 fact는 저장할 수 없습니다.")
        # 중복 방지: 동일 텍스트면 기존 반환
        for f in self.facts:
            if f.text == text:
                return f
        fact = Fact(
            id=uuid.uuid4().hex[:8],
            text=text,
            added=datetime.now().isoformat(timespec="seconds"),
            source=source,
        )
        self.facts.append(fact)
        self.save()
        return fact

    def forget(self, pattern: str) -> int:
        """텍스트에 패턴이 포함된 fact 모두 삭제. 삭제된 개수 반환."""
        before = len(self.facts)
        regex = re.compile(re.escape(pattern), re.IGNORECASE)
        self.facts = [f for f in self.facts if not regex.search(f.text)]
        removed = before - len(self.facts)
        if removed:
            self.save()
        return removed

    def clear(self) -> int:
        n = len(self.facts)
        self.facts = []
        self.save()
        return n

    def to_system_addendum(self) -> str:
        """system_prompt에 덧붙일 텍스트 — 비어있으면 빈 문자열."""
        if not self.facts:
            return ""
        lines = ["", "## 사용자 프로필 (장기 기억)"]
        lines.extend(f"- {f.text}" for f in self.facts)
        lines.append("")
        return "\n".join(lines)
