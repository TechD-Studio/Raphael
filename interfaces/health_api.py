"""헬스/메트릭 HTTP 엔드포인트 — 모니터링 및 운영용.

별도 포트(기본 7861)에서 FastAPI 기반 경량 서버로 노출.
인터페이스(웹/봇)와 독립적으로 실행 가능.

엔드포인트:
  GET /health     — Ollama 연결 상태, 에이전트 수
  GET /metrics    — 요청 수, 평균 지연, 에러율 (Prometheus text format)
  GET /tokens     — ModelRouter 누적 토큰 통계
  GET /agents     — 등록된 에이전트 목록
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from fastapi import FastAPI
from loguru import logger

from core.model_router import ModelRouter
from core.orchestrator import Orchestrator


@dataclass
class MetricsCollector:
    """간이 메트릭 수집기."""

    requests_total: int = 0
    errors_total: int = 0
    latency_sum_ms: float = 0.0
    by_agent: dict = field(default_factory=dict)

    def record(self, agent: str, duration_ms: float, error: bool) -> None:
        self.requests_total += 1
        self.latency_sum_ms += duration_ms
        if error:
            self.errors_total += 1
        a = self.by_agent.setdefault(agent, {"requests": 0, "errors": 0, "latency_ms": 0.0})
        a["requests"] += 1
        a["latency_ms"] += duration_ms
        if error:
            a["errors"] += 1

    def prometheus_format(self) -> str:
        lines = []
        lines.append("# HELP raphael_requests_total 전체 요청 수")
        lines.append("# TYPE raphael_requests_total counter")
        lines.append(f"raphael_requests_total {self.requests_total}")
        lines.append("# HELP raphael_errors_total 오류 응답 수")
        lines.append("# TYPE raphael_errors_total counter")
        lines.append(f"raphael_errors_total {self.errors_total}")
        avg = self.latency_sum_ms / self.requests_total if self.requests_total else 0
        lines.append("# HELP raphael_request_latency_avg_ms 평균 응답 지연(ms)")
        lines.append("# TYPE raphael_request_latency_avg_ms gauge")
        lines.append(f"raphael_request_latency_avg_ms {avg:.2f}")
        for agent, m in self.by_agent.items():
            lines.append(f'raphael_agent_requests{{agent="{agent}"}} {m["requests"]}')
            lines.append(f'raphael_agent_errors{{agent="{agent}"}} {m["errors"]}')
            a_avg = m["latency_ms"] / m["requests"] if m["requests"] else 0
            lines.append(f'raphael_agent_latency_avg_ms{{agent="{agent}"}} {a_avg:.2f}')
        return "\n".join(lines) + "\n"


# 전역 메트릭 수집기 — 모든 인터페이스가 공유
METRICS = MetricsCollector()


def wrap_orchestrator_with_metrics(orch: Orchestrator) -> None:
    """Orchestrator.route를 메트릭 수집 버전으로 감싼다."""
    original_route = orch.route

    async def measured_route(*args, **kwargs):
        start = time.monotonic()
        agent_name = kwargs.get("agent_name") or (
            orch.default_agent.name if orch.default_agent else "unknown"
        )
        error = False
        try:
            return await original_route(*args, **kwargs)
        except Exception:
            error = True
            raise
        finally:
            duration = (time.monotonic() - start) * 1000
            METRICS.record(agent_name, duration, error)

    orch.route = measured_route  # type: ignore


def build_app(router: ModelRouter, orchestrator: Orchestrator) -> FastAPI:
    """헬스/메트릭 API 앱을 생성한다."""
    app = FastAPI(title="Raphael Health API", docs_url="/docs")

    @app.get("/health")
    async def health():
        h = await router.health_check()
        return {
            "status": h["status"],
            "ollama_url": h["ollama_url"],
            "current_model": router.current_key,
            "agents": [a["name"] for a in orchestrator.list_agents()],
            "sessions": len(orchestrator.list_sessions()),
        }

    @app.get("/agents")
    async def agents():
        return orchestrator.list_agents()

    @app.get("/tokens")
    async def tokens():
        return router.get_token_stats()

    @app.get("/metrics")
    async def metrics():
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(METRICS.prometheus_format())

    return app


def run_health_server(
    router: ModelRouter,
    orchestrator: Orchestrator,
    host: str = "127.0.0.1",
    port: int = 7861,
) -> None:
    """헬스 API 서버를 foreground로 실행한다."""
    import uvicorn

    wrap_orchestrator_with_metrics(orchestrator)
    app = build_app(router, orchestrator)
    logger.info(f"헬스 API 시작: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
