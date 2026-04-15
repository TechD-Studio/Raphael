"""테스트 시나리오 자동 실행 — 사전 설정 + 채팅 호출.

각 시나리오:
  1. 작업 폴더 생성 (~/raphael-test-N)
  2. allowed_paths 자동 추가 (path_guard 통과 보장)
  3. 필요한 에이전트 자동 활성화
  4. 사전 안내 출력
  5. 사용자 확인 후 채팅 명령 실행
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger


@dataclass
class Scenario:
    id: int
    level: str
    title: str
    description: str
    workspace: str
    required_agents: list[str] = field(default_factory=list)
    prompt: str = ""
    expected_tools: list[str] = field(default_factory=list)
    # 시나리오에 권장되는 최소 모델 (작은 모델은 도구 태그 형식 실패)
    recommended_model: str = "gemma4-e4b"


SCENARIOS: list[Scenario] = [
    Scenario(
        id=1, level="🟢 L1",
        title="자기소개 페이지",
        description="HTML+CSS 두 파일 + 브라우저 열기 (단일 전문가)",
        workspace="raphael-test-1",
        required_agents=["code-writer"],
        prompt=(
            "{workspace} 폴더에 index.html과 style.css로 자기소개 페이지를 만들어줘.\n"
            "- 이름, 한 줄 소개, 좋아하는 것 3개 섹션\n"
            "- 사용자 정보를 묻지 말고 임의의 샘플로 채워서 바로 만들어줘\n"
            "- style.css로 깔끔하게 스타일링\n"
            "- 만든 후 브라우저로 index.html 열어줘"
        ),
        expected_tools=["mkdir", "write_file", "open_in_browser"],
        recommended_model="claude-haiku",
    ),
    Scenario(
        id=2, level="🟢 L1",
        title="Python 유틸 + pytest",
        description="fibonacci 구현 + 테스트 + 실행",
        workspace="raphael-test-2",
        required_agents=["code-writer"],
        prompt=(
            "{workspace} 에 fibonacci.py 와 test_fibonacci.py 만들어줘:\n"
            "- fibonacci.py: 반복(fib_iter)과 메모이제이션(fib_memo) 두 가지 구현\n"
            "- test_fibonacci.py: pytest 5개 케이스\n"
            "- 만든 후 cd {workspace} && python -m pytest 실행해서 다 통과하는지 확인"
        ),
        expected_tools=["write_file", "python", "execute"],
        recommended_model="claude-sonnet",
    ),
    Scenario(
        id=3, level="🟡 L2",
        title="웹 검색 + 코드 결합",
        description="web-researcher → code-writer 위임",
        workspace="raphael-test-3",
        required_agents=["web-researcher", "code-writer"],
        prompt=(
            "asyncio.gather와 asyncio.TaskGroup의 차이를 웹에서 찾아보고,\n"
            "{workspace}/comparison.md 에 마크다운 표로 정리해줘.\n"
            "출처 URL을 표 아래에 명시해줘."
        ),
        expected_tools=["web_search", "write_file"],
        recommended_model="claude-sonnet",
    ),
    Scenario(
        id=4, level="🟡 L2",
        title="CLI 도구 + 자동 README",
        description="코드 작성 + 웹 검색해서 README 구조 적용",
        workspace="raphael-test-4",
        required_agents=["web-researcher", "code-writer"],
        prompt=(
            "{workspace} 에 wc.py 만들어줘 — 파일 경로 받아서 단어 수 출력하는 CLI.\n"
            "그리고 좋은 README.md 구조를 웹에서 찾아 적용해서 README.md 도 작성해줘."
        ),
        expected_tools=["web_search", "write_file"],
        recommended_model="claude-sonnet",
    ),
    Scenario(
        id=5, level="🟠 L3",
        title="플래시카드 웹앱 + 검토",
        description="planner → code-writer → reviewer 체인",
        workspace="raphael-test-5",
        required_agents=["planner", "code-writer", "reviewer"],
        prompt=(
            "{workspace} 에 영어 단어 플래시카드 웹앱 만들어줘:\n"
            "- HTML+CSS+JS 한 페이지\n"
            "- localStorage에 학습 진도 저장\n"
            "- 5개 샘플 단어 미리 포함\n"
            "- 만든 후 브라우저로 열기\n"
            "- 완료되면 reviewer에게 코드 검토 요청해서 보완점 정리"
        ),
        expected_tools=["delegate", "write_file", "open_in_browser", "read_file"],
        recommended_model="claude-sonnet",
    ),
    Scenario(
        id=6, level="🔴 L4",
        title="Todo CLI (풀스택)",
        description="planner → code-writer (다파일) → git → reviewer",
        workspace="raphael-test-7",
        required_agents=["planner", "code-writer", "reviewer"],
        prompt=(
            "{workspace} 에 todo CLI 앱(Python typer)을 단계적으로 만들어줘:\n"
            "1. todo.py — add/list/done/delete 명령, ~/.todos.json 에 저장\n"
            "2. test_todo.py — pytest 5개\n"
            "3. README.md — 사용법 + 예시\n"
            "4. git init + 첫 커밋\n"
            "5. reviewer로 검토 후 보완점 정리"
        ),
        expected_tools=["delegate", "write_file", "execute", "git_status", "git_commit"],
        recommended_model="claude-opus",
    ),
    Scenario(
        id=7, level="🔴 L4",
        title="데이터 분석 (CSV → 차트)",
        description="CSV 생성 + matplotlib 차트 + 브라우저",
        workspace="raphael-test-8",
        required_agents=["code-writer"],
        prompt=(
            "{workspace}/sales.csv 만들어줘 (월별 매출 12행, 헤더: month,sales).\n"
            "그 다음 python으로 matplotlib 막대 차트 만들어서 chart.png 저장.\n"
            "마지막에 chart.png 를 브라우저로 열기.\n"
            "(pandas/matplotlib 미설치면 pip install 후 진행)"
        ),
        expected_tools=["write_file", "python", "execute", "open_in_browser"],
        recommended_model="claude-sonnet",
    ),
]


def find_scenario(scenario_id: int) -> Scenario | None:
    for s in SCENARIOS:
        if s.id == scenario_id:
            return s
    return None


def list_scenarios_text() -> str:
    lines = ["사용 가능한 테스트 시나리오:\n"]
    for s in SCENARIOS:
        lines.append(f"  #{s.id}  {s.level}  {s.title}")
        lines.append(f"        {s.description}")
        lines.append(f"        에이전트: {', '.join(s.required_agents)}")
        lines.append("")
    lines.append("실행: raphael testbench <id>")
    return "\n".join(lines)


def prepare(scenario: Scenario) -> dict:
    """사전 설정 자동 처리.

    Returns: {workspace_path, allowed_added, agents_enabled, prompt}
    """
    from config.settings import get_settings, save_local_settings, reload_settings
    from core.agent_definitions import is_enabled, set_enabled, get_definition

    # 1. 작업 폴더 생성
    workspace = Path("~").expanduser() / scenario.workspace
    workspace.mkdir(parents=True, exist_ok=True)

    # 2. allowed_paths 추가 (이미 있으면 skip)
    settings = get_settings()
    allowed = list(settings.get("tools", {}).get("file", {}).get("allowed_paths") or [])
    workspace_str = str(workspace)
    allowed_added = False
    if workspace_str not in allowed and not any(
        workspace_str.startswith(p.rstrip("/")) for p in allowed
    ):
        allowed.append(workspace_str)
        save_local_settings({"tools": {"file": {"allowed_paths": allowed}}})
        reload_settings()
        allowed_added = True

    # 3. 필요한 에이전트 활성화 (없는 건 경고)
    agents_enabled = []
    agents_missing = []
    for name in scenario.required_agents:
        if get_definition(name) is None:
            agents_missing.append(name)
            continue
        if not is_enabled(name):
            set_enabled(name, True)
            agents_enabled.append(name)

    # 4. 프롬프트 완성
    prompt = scenario.prompt.format(workspace=workspace_str)

    return {
        "workspace": workspace_str,
        "allowed_added": allowed_added,
        "agents_enabled": agents_enabled,
        "agents_missing": agents_missing,
        "prompt": prompt,
    }
