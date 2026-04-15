"""웹 검색 도구 — DuckDuckGo HTML 프론트엔드 기반 (API 키 불필요)."""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx
from loguru import logger


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str


class WebSearch:
    """DuckDuckGo HTML 검색 결과를 파싱한다."""

    BASE_URL = "https://html.duckduckgo.com/html/"
    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    def __init__(self, timeout: float = 15.0) -> None:
        self.timeout = timeout

    async def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        """다중 백엔드 자동 fallback. 우선순위:

        1. brave (BRAVE_API_KEY 시크릿 있을 때) — 한국어/유튜브 등 정확
        2. tavily (TAVILY_API_KEY)
        3. serper (SERPER_API_KEY) — Google 결과
        4. searxng (settings.searxng_url 있을 때)
        5. ddg_html (DuckDuckGo HTML 스크래핑, 무료)
        6. ddgs 라이브러리
        """
        if not query.strip():
            return []
        logger.debug(f"웹 검색: {query[:60]}")

        from config.settings import get_settings
        from core.secrets import get_secret
        cfg = (get_settings().get("tools") or {}).get("web_search") or {}
        searxng_url = (cfg.get("searxng_url") or "").rstrip("/")
        brave_key = get_secret("BRAVE_API_KEY")
        tavily_key = get_secret("TAVILY_API_KEY")
        serper_key = get_secret("SERPER_API_KEY")

        # 동적 우선순위
        order = cfg.get("backend_order")
        if not order:
            order = []
            if brave_key: order.append("brave")
            if tavily_key: order.append("tavily")
            if serper_key: order.append("serper")
            if searxng_url: order.append("searxng")
            order += ["ddg_html", "ddgs"]

        for backend in order:
            try:
                if backend == "brave" and brave_key:
                    hits = await self._search_brave(brave_key, query, max_results)
                elif backend == "tavily" and tavily_key:
                    hits = await self._search_tavily(tavily_key, query, max_results)
                elif backend == "serper" and serper_key:
                    hits = await self._search_serper(serper_key, query, max_results)
                elif backend == "searxng" and searxng_url:
                    hits = await self._search_searxng(searxng_url, query, max_results)
                elif backend == "ddg_html":
                    hits = await self._search_html(query, max_results)
                elif backend == "ddgs":
                    hits = await self._search_ddgs(query, max_results)
                else:
                    continue
                if hits:
                    logger.debug(f"검색 백엔드 성공: {backend} ({len(hits)}건)")
                    return hits
            except Exception as e:
                logger.warning(f"백엔드 {backend} 실패: {e}")
        return []

    async def _search_brave(self, api_key: str, query: str, max_results: int) -> list[SearchHit]:
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            resp = await c.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": max_results, "country": "KR"},
                headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
        out = []
        for r in (data.get("web", {}).get("results") or [])[:max_results]:
            out.append(SearchHit(title=r.get("title", ""), url=r.get("url", ""), snippet=r.get("description", "")))
        return out

    async def _search_tavily(self, api_key: str, query: str, max_results: int) -> list[SearchHit]:
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            resp = await c.post(
                "https://api.tavily.com/search",
                json={"api_key": api_key, "query": query, "max_results": max_results, "search_depth": "basic"},
            )
            resp.raise_for_status()
            data = resp.json()
        out = []
        for r in (data.get("results") or [])[:max_results]:
            out.append(SearchHit(title=r.get("title", ""), url=r.get("url", ""), snippet=r.get("content", "")))
        return out

    async def _search_serper(self, api_key: str, query: str, max_results: int) -> list[SearchHit]:
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            resp = await c.post(
                "https://google.serper.dev/search",
                json={"q": query, "num": max_results, "gl": "kr", "hl": "ko"},
                headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
        out = []
        for r in (data.get("organic") or [])[:max_results]:
            out.append(SearchHit(title=r.get("title", ""), url=r.get("link", ""), snippet=r.get("snippet", "")))
        return out

    async def _search_searxng(self, base_url: str, query: str, max_results: int) -> list[SearchHit]:
        """SearXNG 인스턴스 검색 (JSON API)."""
        url = f"{base_url}/search"
        params = {"q": query, "format": "json", "language": "ko"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(url, params=params, headers={"User-Agent": self.USER_AGENT})
            resp.raise_for_status()
            data = resp.json()
        out: list[SearchHit] = []
        for r in (data.get("results") or [])[:max_results]:
            out.append(SearchHit(
                title=r.get("title", "") or "",
                url=r.get("url", "") or "",
                snippet=r.get("content", "") or "",
            ))
        return out

    async def _search_html(self, query: str, max_results: int) -> list[SearchHit]:
        """DuckDuckGo HTML 프론트엔드 스크래핑."""
        headers = {"User-Agent": self.USER_AGENT}
        data = {"q": query, "kl": "wt-wt"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers=headers) as client:
                resp = await client.post(self.BASE_URL, data=data)
                resp.raise_for_status()
                html = resp.text
        except Exception as e:
            logger.warning(f"HTML 검색 실패: {e}")
            return []
        return self._parse_results(html, max_results)

    async def _search_ddgs(self, query: str, max_results: int) -> list[SearchHit]:
        """ddgs 라이브러리 기반 검색 (있으면). 없으면 빈 리스트."""
        try:
            from ddgs import DDGS  # type: ignore
        except ImportError:
            try:
                from duckduckgo_search import DDGS  # type: ignore
            except ImportError:
                logger.info("ddgs/duckduckgo_search 라이브러리 미설치. pip install ddgs 로 설치 가능.")
                return []

        import asyncio
        loop = asyncio.get_running_loop()

        def _blocking_search():
            try:
                with DDGS() as ddg:
                    return list(ddg.text(query, max_results=max_results))
            except Exception as e:
                logger.warning(f"ddgs 검색 실패: {e}")
                return []

        raw = await loop.run_in_executor(None, _blocking_search)
        hits: list[SearchHit] = []
        for r in raw:
            hits.append(SearchHit(
                title=r.get("title", ""),
                url=r.get("href", "") or r.get("url", ""),
                snippet=r.get("body", "") or r.get("snippet", ""),
            ))
        return hits

    def _parse_results(self, html: str, max_results: int) -> list[SearchHit]:
        """DuckDuckGo HTML에서 검색 결과 추출."""
        # result block: <a class="result__a" href="URL">TITLE</a> ... <a class="result__snippet">SNIPPET</a>
        pattern = re.compile(
            r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>'
            r'.*?<a[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>',
            re.DOTALL,
        )

        hits: list[SearchHit] = []
        for m in pattern.finditer(html):
            url, title_html, snippet_html = m.groups()
            title = _strip_html(title_html)
            snippet = _strip_html(snippet_html)
            url = _clean_url(url)

            if url and title:
                hits.append(SearchHit(title=title, url=url, snippet=snippet))
                if len(hits) >= max_results:
                    break

        return hits

    async def summarize(self, query: str, max_results: int = 5) -> str:
        """검색 결과를 LLM이 읽기 좋은 텍스트로 요약.

        외부 콘텐츠이므로 명령어/인젝션 패턴을 sanitize_external_text로 정제해서 반환.
        """
        from core.input_guard import sanitize_external_text

        hits = await self.search(query, max_results)
        if not hits:
            return f"'{query}'에 대한 검색 결과를 찾지 못했습니다."

        lines = [f"검색 결과: {query}\n"]
        for i, h in enumerate(hits, 1):
            safe_title = sanitize_external_text(h.title)
            safe_snippet = sanitize_external_text(h.snippet)
            lines.append(f"[{i}] {safe_title}")
            lines.append(f"    URL: {h.url}")
            if safe_snippet:
                lines.append(f"    {safe_snippet}")
            lines.append("")

        return "\n".join(lines).rstrip()


# ── 헬퍼 ──────────────────────────────────────────────────


def _strip_html(s: str) -> str:
    """간단한 HTML 태그/엔티티 제거."""
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'")
    s = s.replace("&lt;", "<").replace("&gt;", ">").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", s).strip()


def _clean_url(url: str) -> str:
    """DuckDuckGo의 리다이렉트 URL에서 실제 URL 추출."""
    # /l/?uddg=https%3A%2F%2Fexample.com → https://example.com
    m = re.search(r"uddg=([^&]+)", url)
    if m:
        from urllib.parse import unquote
        return unquote(m.group(1))
    return url
