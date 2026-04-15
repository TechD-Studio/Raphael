"""스킬(Skills) 시스템 — 사용자 정의 프롬프트 템플릿 등록.

스킬 파일: ~/.raphael/skills/<name>.md
구조(YAML 프론트매터 + 본문):

  ---
  name: code-review
  description: 코드 리뷰 전문가 모드
  agent: coding
  tags: [review, quality]
  ---
  당신은 시니어 코드 리뷰어입니다. 다음 기준으로 평가하세요:
  - 가독성
  - 성능
  - 보안
  - 테스트 커버리지
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from loguru import logger


def skills_dir() -> Path:
    base = os.environ.get("RAPHAEL_SKILLS_DIR")
    if base:
        path = Path(base)
    else:
        path = Path.home() / ".raphael" / "skills"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class Skill:
    name: str
    description: str
    agent: str  # 기본 적용 에이전트 (없으면 "")
    prompt: str
    tags: list[str]
    path: Path

    def to_system_addendum(self) -> str:
        """에이전트 system_prompt에 덧붙일 텍스트."""
        return f"\n\n## 스킬: {self.name}\n{self.description}\n\n{self.prompt}"


def load_skill(path: Path) -> Skill | None:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"스킬 읽기 실패: {path} — {e}")
        return None

    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
    if m:
        try:
            meta = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            meta = {}
        body = m.group(2).strip()
    else:
        meta = {}
        body = text.strip()

    name = meta.get("name") or path.stem
    return Skill(
        name=name,
        description=meta.get("description", "") or "",
        agent=meta.get("agent", "") or "",
        prompt=body,
        tags=list(meta.get("tags") or []),
        path=path,
    )


def list_skills() -> list[Skill]:
    """설치된 스킬 전체."""
    result = []
    for p in sorted(skills_dir().glob("*.md")):
        s = load_skill(p)
        if s:
            result.append(s)
    return result


def get_skill(name: str) -> Skill | None:
    for s in list_skills():
        if s.name == name:
            return s
    return None


def save_skill(name: str, description: str, prompt: str, agent: str = "", tags: list[str] | None = None) -> Path:
    """스킬을 파일로 저장. 이름은 파일명으로도 사용됨 (영숫자/-/_만)."""
    safe_name = re.sub(r"[^A-Za-z0-9_\-]", "_", name)
    path = skills_dir() / f"{safe_name}.md"
    meta = {
        "name": name,
        "description": description,
        "agent": agent,
        "tags": tags or [],
    }
    content = (
        "---\n"
        + yaml.dump(meta, allow_unicode=True).strip()
        + "\n---\n\n"
        + prompt.strip()
        + "\n"
    )
    path.write_text(content, encoding="utf-8")
    return path


def delete_skill(name: str) -> bool:
    s = get_skill(name)
    if not s:
        return False
    s.path.unlink()
    return True
