"""플러그인 로더 — entry_points로 외부 도구/에이전트 자동 등록.

외부 패키지 pyproject.toml 예시:
  [project.entry-points."raphael.tools"]
  jira_tool = "raphael_jira:JiraTool"

  [project.entry-points."raphael.agents"]
  data_agent = "raphael_data:DataAgent"
"""

from __future__ import annotations

from loguru import logger


def load_tool_plugins(registry) -> int:
    """raphael.tools 그룹의 entry_points를 등록."""
    n = 0
    try:
        from importlib.metadata import entry_points
        eps = entry_points().select(group="raphael.tools")
    except Exception as e:
        logger.debug(f"entry_points 로드 실패: {e}")
        return 0

    for ep in eps:
        try:
            cls = ep.load()
            instance = cls() if callable(cls) else cls
            registry.register(ep.name, instance, f"[plugin] {ep.value}")
            n += 1
            logger.info(f"플러그인 도구 등록: {ep.name}")
        except Exception as e:
            logger.warning(f"플러그인 도구 '{ep.name}' 로드 실패: {e}")
    return n


def load_agent_plugins(orchestrator, router, registry) -> int:
    n = 0
    try:
        from importlib.metadata import entry_points
        eps = entry_points().select(group="raphael.agents")
    except Exception as e:
        return 0

    for ep in eps:
        try:
            cls = ep.load()
            agent = cls(router, tool_registry=registry)
            orchestrator.register(agent)
            n += 1
            logger.info(f"플러그인 에이전트 등록: {ep.name}")
        except Exception as e:
            logger.warning(f"플러그인 에이전트 '{ep.name}' 로드 실패: {e}")
    return n
