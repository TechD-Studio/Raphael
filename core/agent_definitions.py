"""에이전트 정의 파일 (~/.raphael/agents/<name>.md) 로더 + 동적 GenericAgent 생성.

frontmatter 예시:
---
name: web-researcher
description: 웹에서 최신 정보를 찾고 출처와 함께 요약
tools: [web_search, read_file]
model: claude-sonnet           # (선택)
default_enabled: true
---

본문 = system prompt
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml
from loguru import logger

from core.agent_base import AgentBase
from core.model_router import ModelRouter
from core.prompts import TOOL_USAGE_PROMPT
from tools.tool_registry import ToolRegistry


def agents_dir() -> Path:
    p = os.environ.get("RAPHAEL_AGENTS_DIR")
    path = Path(p).expanduser() if p else (Path.home() / ".raphael" / "agents")
    path.mkdir(parents=True, exist_ok=True)
    return path


def active_state_path() -> Path:
    return agents_dir() / "_active.json"


# ── 활성 에이전트 상태 영속화 ──────────────────────────────


def load_active_agents() -> set[str]:
    p = active_state_path()
    if not p.exists():
        # 첫 실행 — md 파일 중 default_enabled=True 들로 초기화
        return {d.name for d in list_definitions() if d.default_enabled}
    try:
        return set(json.loads(p.read_text(encoding="utf-8")) or [])
    except Exception:
        return set()


def save_active_agents(names: set[str]) -> None:
    active_state_path().write_text(
        json.dumps(sorted(list(names)), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def is_enabled(name: str) -> bool:
    return name in load_active_agents()


def set_enabled(name: str, enabled: bool) -> None:
    cur = load_active_agents()
    if enabled:
        cur.add(name)
    else:
        cur.discard(name)
    save_active_agents(cur)


# ── 정의 ───────────────────────────────────────────────────


@dataclass
class AgentDefinition:
    name: str
    description: str
    tools: list[str] = field(default_factory=list)
    model: str | None = None
    default_enabled: bool = False
    system_prompt: str = ""
    path: Path | None = None

    def to_markdown(self) -> str:
        meta = {
            "name": self.name,
            "description": self.description,
            "tools": self.tools,
            "default_enabled": self.default_enabled,
        }
        if self.model:
            meta["model"] = self.model
        return (
            "---\n"
            + yaml.dump(meta, allow_unicode=True, sort_keys=False).strip()
            + "\n---\n\n"
            + self.system_prompt.strip()
            + "\n"
        )


def parse_definition(path: Path) -> AgentDefinition | None:
    """단일 md 파일 → AgentDefinition."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"에이전트 파일 읽기 실패: {path} — {e}")
        return None

    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
    if m:
        try:
            meta = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError as e:
            logger.warning(f"frontmatter YAML 오류: {path} — {e}")
            meta = {}
        body = m.group(2).strip()
    else:
        meta = {}
        body = text.strip()

    name = meta.get("name") or path.stem
    return AgentDefinition(
        name=name,
        description=meta.get("description", "") or "",
        tools=list(meta.get("tools") or []),
        model=meta.get("model"),
        default_enabled=bool(meta.get("default_enabled", False)),
        system_prompt=body,
        path=path,
    )


def list_definitions() -> list[AgentDefinition]:
    out = []
    for p in sorted(agents_dir().glob("*.md")):
        d = parse_definition(p)
        if d:
            out.append(d)
    return out


def get_definition(name: str) -> AgentDefinition | None:
    for d in list_definitions():
        if d.name == name:
            return d
    return None


def save_definition(d: AgentDefinition) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_\-]", "_", d.name)
    path = agents_dir() / f"{safe}.md"
    path.write_text(d.to_markdown(), encoding="utf-8")
    d.path = path
    return path


def delete_definition(name: str) -> bool:
    d = get_definition(name)
    if not d or not d.path:
        return False
    d.path.unlink()
    set_enabled(name, False)
    return True


# ── 동적 GenericAgent ──────────────────────────────────────


@dataclass
class GenericAgent(AgentBase):
    """md 정의에서 생성되는 동적 에이전트.

    AgentBase를 상속하지만 자체 _is_tool_allowed override 없음 — 부모의 매핑 활용.
    """

    definition: AgentDefinition | None = None

    @classmethod
    def from_definition(
        cls,
        d: AgentDefinition,
        router: ModelRouter,
        tool_registry: ToolRegistry | None = None,
    ) -> "GenericAgent":
        prompt = d.system_prompt
        if d.tools:
            prompt = prompt.rstrip() + "\n\n" + TOOL_USAGE_PROMPT
        agent = cls(
            name=d.name,
            description=d.description or f"사용자 정의: {d.name}",
            router=router,
            tools=list(d.tools),
            system_prompt=prompt,
            tool_registry=tool_registry,
            definition=d,
        )
        return agent

    async def handle(self, user_input: str, **kwargs) -> str:
        # 정의에 model 지정 시 임시 전환 (호출 후 원복)
        if self.definition and self.definition.model:
            saved = self.router.current_key
            try:
                self.router.switch_model(self.definition.model)
                return await self._call_model(user_input, **kwargs)
            finally:
                try:
                    self.router.switch_model(saved)
                except Exception:
                    pass
        return await self._call_model(user_input, **kwargs)


# ── 기본 에이전트 7개 ──────────────────────────────────────


# 기본 모델 — 도구 호출 안정적으로 동작하는 최소 모델
RECOMMENDED_MIN_MODEL = "gemma4-e4b"


def _default_definitions() -> list[AgentDefinition]:
    return [
        AgentDefinition(
            name="main",
            description="사용자와 대화하는 메인 에이전트 — 모든 도구 직접 사용 가능, 필요 시 페르소나 에이전트에게 위임",
            tools=[],  # 빈 리스트 = 전체 도구 허용 (페르소나 모드)
            default_enabled=True,
            system_prompt=(
                "당신은 Raphael의 메인 에이전트입니다. **모든 도구를 직접 사용할 수 있습니다.**\n\n"
                "## 핵심 사실\n"
                "당신은 **실제 로컬 컴퓨터**에서 실행됩니다. 가상 환경이 아닙니다.\n"
                "write_file로 실제 파일 생성, execute로 실제 명령 실행, mkdir로 실제 폴더 생성이 가능합니다.\n"
                "'접근 불가', '가상 환경', '직접 실행 불가' 같은 답변은 **거짓이므로 절대 하지 마라.**\n"
                "코드를 텍스트로 보여주지 말고 **write_file로 실제 파일을 생성**하라.\n\n"
                "## 핵심 동작 원칙\n"
                "1. **도구를 직접 호출하는 것이 기본.** 위임은 역할 전문성이 실제로 필요할 때만.\n"
                "   - URL 있음 → fetch_url 직접 호출 (위임 금지).\n"
                "   - 파일 작성/실행 → write_file/execute 직접 호출.\n"
                "   - 웹 검색 → web_search 직접 호출.\n"
                "   - 브라우저 열기 → open_in_browser 직접 호출.\n"
                "   - 이미지/그림 생성 → generate_image 직접 호출 ('그릴 수 없다' 답변 금지).\n"
                "2. **페르소나 에이전트가 필요한 경우만 delegate** (예: '마케팅 관점으로 검토해줘' → marketer 에이전트).\n"
                "3. 사용자가 자기 정보를 알려주면 `remember` 도구로 저장.\n\n"
                "## 도구 호출 형식\n"
                "<tool name=\"write_file\"><arg name=\"path\">/abs/path</arg><arg name=\"content\">...</arg></tool>\n"
                "한 응답에 여러 tool 블록 포함 가능 (병렬 실행).\n\n"
                "## 위임 형식 (꼭 필요할 때만)\n"
                "<tool name=\"delegate\">\n"
                "<arg name=\"agent\">페르소나-이름</arg>\n"
                "<arg name=\"task\">자기 완결적 작업 설명 (경로/URL은 그대로 복사)</arg>\n"
                "</tool>\n\n"
                "절대 금지:\n"
                "- <tool name=\"페르소나-이름\">  ← name은 반드시 \"delegate\"\n"
                "- 같은 도구/task를 한 응답에 중복 호출\n\n"
                "## 기본 규칙\n"
                "- 사용자 메시지의 경로/URL/이름은 그대로 보존해 도구에 전달.\n"
                "- 세부 정보 부족 시 합리적 기본값으로 진행하고 가정만 보고. 매번 묻지 말 것.\n"
                "- 활성화된 페르소나 목록은 아래 [AVAILABLE AGENTS]에 주입됨.\n\n"
                "## 확인 게이트 (매우 중요)\n"
                "사용자 메시지에 **명시적 승인 요구**가 있으면 그 지점에서 반드시 멈춰라:\n"
                "  - '확인 한 후에 시작할게', '확인하고 진행해', '내가 승인하면'\n"
                "  - '가져온 정보가 맞는지 확인', '검토 후 진행'\n"
                "이런 문구가 있으면 정보 수집까지만 수행 → 요약 제시 → 사용자의 '진행해'/'맞아' 응답 대기.\n"
                "그 전까지 **파일 생성/실행/브라우저 열기 도구는 호출 금지**."
            ),
        ),
        AgentDefinition(
            name="researcher",
            description="웹/URL에서 정보를 수집하고 분석 — 모든 도구 사용 가능",
            tools=[],
            default_enabled=True,
            system_prompt=(
                "당신은 정보 수집/분석 전문가입니다.\n\n"
                "- 특정 URL은 `fetch_url`로 직접 가져옴 (유튜브는 제목/설명/최근 영상 자동 추출).\n"
                "- 일반 키워드는 `web_search`로 검색 후 상위 결과를 `fetch_url`로 본문 추출.\n"
                "- 핵심 사실만 추려서 출처 URL과 함께 요약. 추측 금지."
            ),
        ),
        AgentDefinition(
            name="coder",
            description="코드 작성/실행/디버깅 전문가 — 모든 도구 사용 가능",
            tools=[],
            default_enabled=True,
            system_prompt=(
                "당신은 10년차 풀스택 개발자입니다.\n\n"
                "- 여러 파일이 필요하면 한 응답에 여러 write_file 블록 모두 포함.\n"
                "- 코드 블록은 언어를 명시. 에러는 원인 분석 후 수정안 제시.\n"
                "- 실행 결과를 확인하려면 execute/python 사용. 브라우저 확인은 open_in_browser."
            ),
        ),
        AgentDefinition(
            name="writer",
            description="옵시디언/마크다운 노트 작성 전문가 — 모든 도구 사용 가능",
            tools=[],
            default_enabled=True,
            system_prompt=(
                "당신은 노트 작성 전문가입니다.\n\n"
                "- 마크다운 형식, [[링크]] 문법과 #태그 활용.\n"
                "- 사용자의 옵시디언 볼트 경로 기준 작업."
            ),
        ),
        AgentDefinition(
            name="planner",
            description="작업을 단계로 분해하고 실행 조율",
            tools=[],
            default_enabled=False,
            system_prompt=(
                "당신은 작업 계획 전문가입니다.\n"
                "1. 사용자 요청을 3~6개 단계로 분해.\n"
                "2. 단순 단계는 직접 실행. 역할 전문성이 필요하면 delegate.\n"
                "3. 모든 단계 완료 후 사용자에게 종합 보고."
            ),
        ),
        AgentDefinition(
            name="reviewer",
            description="산출물 비판적 검토",
            tools=[],
            default_enabled=False,
            system_prompt=(
                "당신은 산출물 검토 전문가입니다.\n"
                "1. read_file로 산출물 직접 확인.\n"
                "2. 평가: 요구사항 충족도, 완성도, 정확성, 사용성.\n"
                "3. 형식: ✅ 좋은 점 / ⚠ 보완 필요 / 🔧 권장 다음 작업.\n"
                "4. 추측 금지 — 실제 파일을 읽어 평가."
            ),
        ),
    ]


def install_defaults_if_empty() -> int:
    """첫 부팅 시 ~/.raphael/agents 비어있으면 기본 7개 설치."""
    existing = list_definitions()
    if existing:
        return 0
    n = 0
    for d in _default_definitions():
        save_definition(d)
        n += 1
    # 기본 활성화도 동기화
    save_active_agents({d.name for d in _default_definitions() if d.default_enabled})
    logger.info(f"기본 에이전트 {n}개 설치됨: {agents_dir()}")
    return n


# ── 자동 추천 (사용 패턴 학습) ─────────────────────────────


def usage_log_path() -> Path:
    return agents_dir() / "_usage.json"


def record_usage(agent_name: str, was_helpful: bool = True) -> None:
    p = usage_log_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        data = {}
    entry = data.setdefault(agent_name, {"calls": 0, "helpful": 0, "last": ""})
    entry["calls"] += 1
    if was_helpful:
        entry["helpful"] += 1
    entry["last"] = datetime.now().isoformat(timespec="seconds")
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_recommendations(active: set[str], limit: int = 3) -> list[tuple[str, str]]:
    """비활성 + 최근 사용 패턴 기반으로 추천. (name, reason) 리스트."""
    p = usage_log_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    candidates = [
        (name, info) for name, info in data.items()
        if name not in active and info.get("calls", 0) >= 3
    ]
    candidates.sort(key=lambda x: x[1].get("calls", 0), reverse=True)
    out = []
    for name, info in candidates[:limit]:
        out.append((name, f"{info['calls']}회 사용됨, 마지막 {info.get('last','')[:10]}"))
    return out
