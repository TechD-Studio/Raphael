"""Ollama 서버 풀 — 여러 머신에 분산된 Ollama 인스턴스 관리.

각 서버는 자기가 보유한 모델 목록과 가중치/활성요청 카운터를 가진다.
RouterStrategy가 작업 컨텍스트(에이전트, 메시지수, 도구 등)를 받아
적합한 (모델, 서버) 쌍을 결정한다.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field

import httpx
from loguru import logger

from config.settings import get_settings


@dataclass
class OllamaServer:
    name: str
    host: str
    port: int = 11434
    weight: int = 1
    declared_models: list[str] = field(default_factory=list)  # 설정상의 보유 모델
    timeout: int = 120
    _client: httpx.AsyncClient | None = field(default=None, repr=False)
    _client_loop: asyncio.AbstractEventLoop | None = field(default=None, repr=False)
    _active: int = field(default=0, repr=False)
    _installed_cache: list[str] = field(default_factory=list, repr=False)
    _last_health: str = field(default="unknown", repr=False)

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def active_requests(self) -> int:
        return self._active

    def _get_client(self) -> httpx.AsyncClient:
        try:
            cur = asyncio.get_running_loop()
        except RuntimeError:
            cur = None
        need_new = (
            self._client is None or self._client.is_closed
            or (cur is not None and self._client_loop is not cur)
        )
        if need_new:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout, connect=10),
            )
            self._client_loop = cur
        return self._client

    async def health(self) -> str:
        try:
            r = await self._get_client().get("/")
            self._last_health = "ok" if r.status_code == 200 else "error"
        except Exception:
            self._last_health = "unreachable"
        return self._last_health

    async def installed_models(self, refresh: bool = False) -> list[str]:
        if self._installed_cache and not refresh:
            return self._installed_cache
        try:
            r = await self._get_client().get("/api/tags")
            r.raise_for_status()
            self._installed_cache = [m["name"] for m in r.json().get("models", [])]
        except Exception as e:
            logger.warning(f"[{self.name}] /api/tags 실패: {e}")
            self._installed_cache = []
        return self._installed_cache

    async def has_model(self, model_name: str) -> bool:
        installed = await self.installed_models()
        return model_name in installed or any(m.split(":")[0] == model_name.split(":")[0] for m in installed)

    async def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        self._active += 1
        try:
            return await self._get_client().request(method, url, **kwargs)
        finally:
            self._active -= 1

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            try:
                await self._client.aclose()
            except Exception:
                pass


class OllamaPool:
    """다중 서버 관리 + least-busy 선택."""

    def __init__(self) -> None:
        self.servers: list[OllamaServer] = []
        self._build_from_settings()

    def _build_from_settings(self) -> None:
        s = get_settings()
        pool_cfg = (s.get("models") or {}).get("ollama_pool")
        if pool_cfg:
            for cfg in pool_cfg:
                self.servers.append(OllamaServer(
                    name=cfg["name"],
                    host=cfg["host"],
                    port=int(cfg.get("port", 11434)),
                    weight=int(cfg.get("weight", 1)),
                    declared_models=list(cfg.get("models", [])),
                    timeout=int(cfg.get("timeout", 120)),
                ))
        else:
            # 단일 서버 — 기존 ollama 설정 변환
            ol = s["models"]["ollama"]
            self.servers.append(OllamaServer(
                name="default",
                host=ol["host"],
                port=int(ol.get("port", 11434)),
                weight=1,
                timeout=int(ol.get("timeout", 120)),
            ))

    async def select_for_model(self, model_name: str) -> OllamaServer | None:
        """해당 모델을 가진 서버 중 least-busy / 가중치 적용 선택."""
        candidates = []
        for srv in self.servers:
            # declared_models 우선 (네트워크 호출 없이 빠르게)
            if srv.declared_models:
                if model_name in srv.declared_models or any(
                    m.split(":")[0] == model_name.split(":")[0] for m in srv.declared_models
                ):
                    candidates.append(srv)
            else:
                # declared 없으면 실제 설치 확인
                if await srv.has_model(model_name):
                    candidates.append(srv)

        if not candidates:
            return None

        # least-busy / 가중치 (active/weight 가 작을수록 선택)
        return min(candidates, key=lambda s: s.active_requests / max(s.weight, 1))

    async def health_all(self) -> list[dict]:
        out = []
        for srv in self.servers:
            h = await srv.health()
            out.append({
                "name": srv.name,
                "url": srv.base_url,
                "health": h,
                "active": srv.active_requests,
                "weight": srv.weight,
                "declared_models": srv.declared_models,
            })
        return out

    async def close_all(self) -> None:
        for srv in self.servers:
            await srv.close()
