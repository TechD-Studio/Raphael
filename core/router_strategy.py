"""작업 컨텍스트 → (모델, 에이전트) 라우팅 결정.

settings.yaml 의 models.routing.rules 를 읽어 매칭되는 첫 규칙을 적용.
규칙 형식:
  - match:
      agent: coding              # 현재 에이전트와 일치
      min_messages: 5            # 대화 길이 >= 5
      token_estimate_gt: 300     # 입력 추정 토큰 > 300
      contains_any: ["여러", "전체"]  # 텍스트에 키워드 포함
      tools_used: ["python"]     # 마지막 어시스턴트가 호출한 도구
    prefer_model: gemma4-26b
    prefer_agent: planner        # (선택) 에이전트 자동 전환
"""

from __future__ import annotations

from dataclasses import dataclass

from config.settings import get_settings


@dataclass
class TaskContext:
    user_input: str
    agent: str = ""
    messages_count: int = 0


@dataclass
class RouteDecision:
    model_key: str | None = None     # None이면 현재 유지
    agent_name: str | None = None    # None이면 현재 유지
    rule_name: str = ""


def _estimate_tokens(text: str) -> int:
    # 매우 거친 추정 — 한글/영문 평균 4자/토큰
    return max(1, len(text) // 4)


_WEAK_MODELS = {"gemma4-e2b", "gemma4:e2b"}


def _match_rule(rule: dict, ctx: TaskContext) -> bool:
    m = rule.get("match", {})
    # 약한 모델로의 다운그레이드는 명시적으로 agent를 지정한 규칙에서만 허용.
    # (도구 오케스트레이션 / 위임 / 코드 작성에는 e2b가 부족함)
    if rule.get("prefer_model") in _WEAK_MODELS and "agent" not in m:
        return False
    if "agent" in m and ctx.agent != m["agent"]:
        return False
    if "min_messages" in m and ctx.messages_count < int(m["min_messages"]):
        return False
    if "token_estimate_gt" in m and _estimate_tokens(ctx.user_input) <= int(m["token_estimate_gt"]):
        return False
    if "token_estimate_lt" in m and _estimate_tokens(ctx.user_input) >= int(m["token_estimate_lt"]):
        return False
    if "contains_any" in m:
        kws = [k.lower() for k in m["contains_any"]]
        if not any(k in ctx.user_input.lower() for k in kws):
            return False
    if m.get("default"):
        return True
    return True


def load_config() -> dict:
    """현재 라우팅 설정을 반환한다. {strategy, rules}"""
    s = get_settings()
    r = (s.get("models") or {}).get("routing") or {}
    return {
        "strategy": r.get("strategy", "manual"),
        "rules": list(r.get("rules") or []),
    }


def save_config(strategy: str | None = None, rules: list | None = None) -> None:
    """settings.local.yaml에 라우팅 설정을 저장한다."""
    from config.settings import save_local_settings
    current = load_config()
    new_strategy = strategy if strategy is not None else current["strategy"]
    new_rules = rules if rules is not None else current["rules"]
    save_local_settings({
        "models": {
            "routing": {
                "strategy": new_strategy,
                "rules": new_rules,
            }
        }
    })


class RouterStrategy:
    def __init__(self) -> None:
        cfg = load_config()
        self.rules = cfg["rules"]
        self.strategy = cfg["strategy"]

    def decide(self, ctx: TaskContext) -> RouteDecision:
        if self.strategy != "auto":
            return RouteDecision()
        # 명시적 규칙 우선
        for r in self.rules:
            if _match_rule(r, ctx):
                return RouteDecision(
                    model_key=r.get("prefer_model"),
                    agent_name=r.get("prefer_agent"),
                    rule_name=str(r.get("name") or r.get("match", {})),
                )
        # 휴리스틱 fallback: 입력 내용으로 gemma4-e2b vs gemma4-e4b 자동 선택
        return _heuristic_decide(ctx)


# 파일 생성/코드/여러 단계가 필요한 키워드 → e4b 필요
_E4B_KEYWORDS = [
    "만들어", "작성", "생성", "create", "구현", "디버그", "실행", "분석",
    "설치", "pytest", "git", "test", "refactor", "리뷰", "review",
    "파일", "코드", "html", "css", "python", "js",
]


def _heuristic_decide(ctx: TaskContext) -> RouteDecision:
    """입력 문자열 기반 경량 휴리스틱 — 명시 규칙 없을 때 fallback.

    - 짧고 단순한 질문 → e2b
    - 코드/파일/실행 관련 키워드 → e4b
    """
    text = ctx.user_input.lower()
    # 멀티라인 or 긴 지시 → 코딩성 작업 가능성 ↑
    is_long = len(ctx.user_input) >= 80 or "\n" in ctx.user_input
    hits_e4b = any(k.lower() in text for k in _E4B_KEYWORDS)
    if hits_e4b or is_long:
        return RouteDecision(model_key="gemma4-e4b", rule_name="heuristic:code_task")
    # 짧은 인사/질문 → e2b 허용
    if len(ctx.user_input.strip()) < 30:
        return RouteDecision(model_key="gemma4-e2b", rule_name="heuristic:short_query")
    return RouteDecision()
