"""Ollama 모델 라우터 — 연결, 모델 선택/전환, 헬스체크, 채팅/생성 요청."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import AsyncIterator

import httpx
from loguru import logger

from config.settings import get_model_config, get_ollama_base_url, get_settings

# 네트워크 일시 오류에 대한 재시도 설정
_RETRY_EXCEPTIONS = (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError)
_MAX_RETRIES = 3
_BASE_BACKOFF = 0.5  # 초


class ModelNotInstalledError(Exception):
    """Ollama 서버에 요청한 모델이 설치되어 있지 않음."""

    def __init__(self, model_name: str, installed: list[str]) -> None:
        self.model_name = model_name
        self.installed = installed
        msg = (
            f"모델 '{model_name}'이 Ollama 서버에 설치되어 있지 않습니다.\n"
            f"다음 명령으로 설치하세요:\n"
            f"    ollama pull {model_name}"
        )
        if installed:
            msg += f"\n\n현재 설치된 모델: {', '.join(installed)}"
        else:
            msg += "\n\n설치된 모델이 없거나 Ollama 서버에 접근할 수 없습니다."
        super().__init__(msg)


@dataclass
class ModelRouter:
    """Ollama 서버와 통신하며 모델 선택/전환을 관리한다.

    httpx.AsyncClient는 생성된 이벤트 루프에 바인딩되므로, 루프가 바뀌면
    재생성한다. 이로 인해 CLI(단발 asyncio.run)와 서버(지속 루프) 양쪽에서
    안전하게 동작한다.
    """

    _current_key: str = ""
    _client: httpx.AsyncClient | None = field(default=None, repr=False)
    _client_loop: asyncio.AbstractEventLoop | None = field(default=None, repr=False)
    # 누적 토큰 통계: {model: {"prompt": int, "completion": int, "calls": int}}
    _token_stats: dict = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        settings = get_settings()
        if not self._current_key:
            self._current_key = settings["models"]["default"]
        # 클라이언트 초기화는 지연 — 첫 요청 시점의 이벤트 루프에 맞춰 생성
        self._client = None
        self._client_loop = None

    @property
    def current_key(self) -> str:
        return self._current_key

    @property
    def current_model_name(self) -> str:
        """Ollama에서 사용하는 실제 모델 이름."""
        return get_model_config(self._current_key)["name"]

    # ── 내부: 이벤트 루프에 맞는 클라이언트 보장 ────────────

    _pool: "any" = field(default=None, repr=False)

    def _ensure_pool(self):
        """OllamaPool 지연 초기화 (settings.models.ollama_pool 있을 때만 실제 의미)."""
        if self._pool is None:
            from core.ollama_pool import OllamaPool
            self._pool = OllamaPool()
        return self._pool

    def _get_client(self) -> httpx.AsyncClient:
        """현재 이벤트 루프에 바인딩된 클라이언트를 반환한다.

        루프가 바뀌었거나 클라이언트가 없으면 새로 생성한다.
        """
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        # 기존 클라이언트가 다른 루프에 바인딩되었거나 닫혔으면 재생성
        need_new = (
            self._client is None
            or self._client.is_closed
            or (current_loop is not None and self._client_loop is not current_loop)
        )

        if need_new:
            if self._client is not None and not self._client.is_closed:
                # 이전 루프의 클라이언트는 더 이상 쓸 수 없음 — 참조만 버림
                # (aclose는 기존 루프에서만 가능하므로 여기서 호출하지 않음)
                pass

            settings = get_settings()
            timeout = settings["models"]["ollama"].get("timeout", 120)
            self._client = httpx.AsyncClient(
                base_url=get_ollama_base_url(),
                timeout=httpx.Timeout(timeout, connect=10),
            )
            self._client_loop = current_loop
            logger.debug(f"httpx.AsyncClient 생성 (loop={id(current_loop)})")

        return self._client

    # ── 모델 전환 ──────────────────────────────────────────

    def switch_model(self, model_key: str) -> dict:
        """모델을 전환한다. 유효하지 않은 키면 ValueError.

        설치 여부는 여기서 체크하지 않는다(동기 메서드라 네트워크 호출 피함).
        실제 chat() 시점에 404가 나면 ModelNotInstalledError로 변환된다.
        """
        config = get_model_config(model_key)
        self._current_key = model_key
        logger.info(f"모델 전환: {model_key} ({config['name']})")
        return config

    async def switch_model_checked(self, model_key: str) -> tuple[dict, bool, list[str]]:
        """모델 전환 + 설치 여부 확인 (claude_cli는 별도 체크)."""
        config = self.switch_model(model_key)
        if config.get("provider") == "claude_cli":
            from core.claude_provider import ClaudeCodeProvider
            return config, ClaudeCodeProvider().is_available(), ["claude CLI"]
        installed = await self.list_installed_models()
        return config, (config["name"] in installed), installed

    def list_models(self) -> dict[str, dict]:
        """settings.yaml에 정의된 모델 목록을 반환한다 (메타데이터 포함)."""
        return get_settings()["models"]["ollama"]["available"]

    async def list_installed_models(self) -> list[str]:
        """Ollama 서버에 실제로 설치된 모델 이름 목록을 반환한다."""
        try:
            resp = await self._get_client().get("/api/tags")
            resp.raise_for_status()
            data = resp.json()
            return [m["name"] for m in data.get("models", [])]
        except Exception as e:
            logger.warning(f"설치 모델 목록 조회 실패: {e}")
            return []

    async def is_model_installed(self, model_name: str) -> bool:
        """Ollama에 해당 모델이 설치되어 있는지 확인한다."""
        installed = await self.list_installed_models()
        return model_name in installed

    # ── 헬스체크 ───────────────────────────────────────────

    async def health_check(self) -> dict:
        """Ollama 서버 상태를 확인한다."""
        client = self._get_client()
        try:
            resp = await client.get("/")
            return {
                "status": "ok" if resp.status_code == 200 else "error",
                "ollama_url": str(client.base_url),
                "current_model": self._current_key,
            }
        except httpx.ConnectError:
            return {
                "status": "unreachable",
                "ollama_url": str(client.base_url),
                "current_model": self._current_key,
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "ollama_url": str(client.base_url),
                "current_model": self._current_key,
            }

    # ── 채팅 (비스트리밍) ──────────────────────────────────

    # 기본 생성 옵션 — 도구 호출 태그 등에 결정적 출력을 선호
    DEFAULT_OPTIONS = {
        "temperature": 0.3,
        "top_p": 0.9,
    }

    async def chat(
        self,
        messages: list[dict],
        model_key: str | None = None,
        retry_on_empty: bool = True,
        images: list[str] | None = None,
        **kwargs,
    ) -> dict:
        """모델 호출. provider에 따라 Ollama 또는 Claude CLI로 분기.

        images: 마지막 user 메시지에 첨부할 이미지 (vision 모델 필요).
        """
        cfg = get_model_config(model_key or self._current_key)
        provider = cfg.get("provider", "ollama")

        # ── Claude CLI provider ─────────────────────────────
        if provider == "claude_cli":
            from core.claude_provider import ClaudeCodeProvider, ClaudeCLIError
            prov = ClaudeCodeProvider()
            if not prov.is_available():
                raise ModelNotInstalledError(model_name="claude (CLI)", installed=[])
            try:
                data = await prov.chat(
                    messages,
                    cli_args=cfg.get("cli_args"),
                    allowed_tools=cfg.get("allowed_tools"),
                )
            except ClaudeCLIError as e:
                # ModelNotInstalled로 변환해 동일한 에러 채널 활용
                raise ModelNotInstalledError(model_name=cfg.get("name", "claude"), installed=[]) from e
            self._record_tokens(cfg["name"], data)
            return data

        # ── Ollama provider (기본) ──────────────────────────
        model_name = cfg["name"]

        # 이미지가 있으면 마지막 user 메시지에 첨부
        if images:
            messages = [dict(m) for m in messages]  # 사본
            for m in reversed(messages):
                if m.get("role") == "user":
                    encoded = []
                    for img in images:
                        if img.startswith("data:") or len(img) > 1000:
                            # base64 또는 data URL — 그대로
                            encoded.append(img)
                        else:
                            # 파일 경로 → base64
                            import base64 as _b64
                            from pathlib import Path as _Path
                            data = _Path(img).expanduser().read_bytes()
                            encoded.append(_b64.b64encode(data).decode("ascii"))
                    m["images"] = encoded
                    break

        # 기본 옵션과 호출자 옵션 병합
        options = dict(self.DEFAULT_OPTIONS)
        if "options" in kwargs:
            options.update(kwargs.pop("options") or {})

        payload = {
            "model": model_name,
            "messages": messages,
            "stream": False,
            "options": options,
            **kwargs,
        }
        logger.debug(f"chat request → {model_name}, messages={len(messages)}")

        # OllamaPool에 다중 서버가 있으면 라우팅 사용
        pool = self._ensure_pool()
        if len(pool.servers) > 1:
            target = await pool.select_for_model(model_name)
            if target is not None:
                logger.debug(f"pool routing → {target.name}")
                try:
                    resp = await target.request("POST", "/api/chat", json=payload)
                    if resp.status_code == 404:
                        installed = await target.installed_models(refresh=True)
                        raise ModelNotInstalledError(model_name=model_name, installed=installed)
                    resp.raise_for_status()
                    data = resp.json()
                    self._record_tokens(model_name, data)
                    return data
                except ModelNotInstalledError:
                    raise
                except Exception as e:
                    logger.warning(f"pool 라우팅 실패 → fallback: {e}")

        resp = await self._request_with_retry("POST", "/api/chat", json=payload)

        if resp.status_code == 404:
            installed = await self.list_installed_models()
            raise ModelNotInstalledError(model_name=model_name, installed=installed)

        resp.raise_for_status()
        data = resp.json()
        content = data.get("message", {}).get("content", "")

        # 토큰 통계 누적
        self._record_tokens(model_name, data)

        # 빈 응답 재시도 — temperature를 약간 올려 변주
        if retry_on_empty and not content.strip():
            logger.warning(f"빈 응답 감지 ({model_name}). 재시도 (temperature↑)")
            retry_options = dict(options)
            retry_options["temperature"] = min(1.0, options.get("temperature", 0.3) + 0.3)
            return await self.chat(
                messages,
                model_key=model_key,
                retry_on_empty=False,
                options=retry_options,
                **kwargs,
            )

        return data

    # ── 재시도 + 토큰 ──────────────────────────────────────

    async def _request_with_retry(self, method: str, url: str, **kwargs) -> httpx.Response:
        """ConnectError/Timeout 등에 대해 지수 백오프로 재시도."""
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                return await self._get_client().request(method, url, **kwargs)
            except _RETRY_EXCEPTIONS as e:
                last_exc = e
                if attempt + 1 < _MAX_RETRIES:
                    delay = _BASE_BACKOFF * (2 ** attempt)
                    logger.warning(
                        f"네트워크 오류 ({type(e).__name__}), {delay}s 후 재시도 "
                        f"({attempt + 1}/{_MAX_RETRIES})"
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"최대 재시도({_MAX_RETRIES}) 초과: {e}")
        assert last_exc is not None
        raise last_exc

    def _record_tokens(self, model_name: str, data: dict) -> None:
        """Ollama 응답의 prompt_eval_count / eval_count를 누적."""
        stats = self._token_stats.setdefault(
            model_name, {"prompt": 0, "completion": 0, "calls": 0, "total_ms": 0}
        )
        stats["prompt"] += int(data.get("prompt_eval_count", 0) or 0)
        stats["completion"] += int(data.get("eval_count", 0) or 0)
        stats["calls"] += 1
        total_ns = data.get("total_duration", 0) or 0
        stats["total_ms"] += int(total_ns / 1_000_000)

    def get_token_stats(self) -> dict:
        """누적 토큰 통계를 반환한다."""
        import copy as _copy
        return _copy.deepcopy(self._token_stats)

    def reset_token_stats(self) -> None:
        self._token_stats.clear()

    # ── 채팅 (스트리밍) ────────────────────────────────────

    async def chat_stream(
        self,
        messages: list[dict],
        model_key: str | None = None,
        images: list[str] | None = None,
        **kwargs,
    ) -> AsyncIterator[dict]:
        """스트리밍. provider별 분기."""
        cfg = get_model_config(model_key or self._current_key)
        provider = cfg.get("provider", "ollama")

        if provider == "claude_cli":
            from core.claude_provider import ClaudeCodeProvider
            prov = ClaudeCodeProvider()
            if not prov.is_available():
                raise ModelNotInstalledError(model_name="claude (CLI)", installed=[])
            async for chunk in prov.chat_stream(
                messages,
                cli_args=cfg.get("cli_args"),
                allowed_tools=cfg.get("allowed_tools"),
            ):
                yield chunk
            return

        model_name = cfg["name"]

        if images:
            messages = [dict(m) for m in messages]
            for m in reversed(messages):
                if m.get("role") == "user":
                    encoded = []
                    for img in images:
                        if img.startswith("data:") or len(img) > 1000:
                            encoded.append(img)
                        else:
                            import base64 as _b64
                            from pathlib import Path as _Path
                            data = _Path(img).expanduser().read_bytes()
                            encoded.append(_b64.b64encode(data).decode("ascii"))
                    m["images"] = encoded
                    break

        payload = {
            "model": model_name,
            "messages": messages,
            "stream": True,
            **kwargs,
        }
        logger.debug(f"chat_stream request → {model_name}")
        async with self._get_client().stream("POST", "/api/chat", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.strip():
                    import json
                    yield json.loads(line)

    # ── 임베딩 ─────────────────────────────────────────────

    async def embed(self, text: str, model: str | None = None) -> list[float]:
        """텍스트를 벡터로 변환한다. 기본 모델: nomic-embed-text."""
        embed_model = model or get_settings()["memory"]["embedding_model"]
        resp = await self._get_client().post(
            "/api/embed",
            json={"model": embed_model, "input": text},
        )
        if resp.status_code == 404:
            installed = await self.list_installed_models()
            raise ModelNotInstalledError(model_name=embed_model, installed=installed)
        resp.raise_for_status()
        data = resp.json()
        return data["embeddings"][0]

    async def ensure_embedding_model(self, pull_if_missing: bool = False) -> tuple[bool, str]:
        """임베딩 모델 설치 여부를 확인한다.

        pull_if_missing=True면 `ollama pull`을 실행해 자동 설치한다.
        Returns: (설치_여부, 메시지)
        """
        embed_model = get_settings()["memory"]["embedding_model"]
        installed = await self.list_installed_models()

        # ollama tag가 ":latest"를 포함하는 경우를 고려
        if embed_model in installed or f"{embed_model}:latest" in installed:
            return True, f"임베딩 모델 {embed_model} 설치됨"

        if not pull_if_missing:
            return False, (
                f"임베딩 모델 '{embed_model}'이 설치되어 있지 않습니다.\n"
                f"설치 명령: ollama pull {embed_model}"
            )

        # 자동 설치 시도
        logger.info(f"임베딩 모델 pull 시작: {embed_model}")
        try:
            # /api/pull 은 스트리밍 응답. 길 수 있으므로 timeout 여유
            client = self._get_client()
            async with client.stream(
                "POST", "/api/pull",
                json={"name": embed_model, "stream": True},
                timeout=httpx.Timeout(600, connect=10),
            ) as resp:
                resp.raise_for_status()
                async for _ in resp.aiter_lines():
                    pass
            return True, f"임베딩 모델 {embed_model} 설치 완료"
        except Exception as e:
            return False, f"자동 설치 실패: {e}"

    # ── 정리 ───────────────────────────────────────────────

    async def close(self) -> None:
        """클라이언트를 닫는다. 이 메서드는 클라이언트가 생성된 루프에서만 호출해야 한다."""
        if self._client is not None and not self._client.is_closed:
            try:
                await self._client.aclose()
            except Exception as e:
                logger.debug(f"client close 중 예외 무시: {e}")
        self._client = None
        self._client_loop = None