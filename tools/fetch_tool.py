"""URL fetch + 본문 추출 + (선택) LLM 요약 — Claude의 WebFetch 동등 구현.

흐름:
  1. httpx로 페이지 다운로드 (User-Agent 위장, 타임아웃, 리다이렉트 추적)
  2. content-type 분기:
     - HTML → BeautifulSoup으로 본문/제목 추출 + 노이즈 제거 (script/style/nav/footer)
     - PDF → pymupdf 텍스트 추출
     - JSON/text → 그대로
  3. 너무 길면 잘라 반환
  4. LLM 요약 옵션 (use_llm=True) — ModelRouter로 추가 호출
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx
from loguru import logger


@dataclass
class FetchTool:
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    timeout: float = 30.0
    max_chars: int = 8000

    async def fetch(
        self,
        url: str,
        max_chars: int | None = None,
        prompt: str | None = None,   # 주어지면 LLM으로 컨텐츠 요약
    ) -> str:
        if not url.strip():
            return "URL이 비어있습니다."
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        max_chars = max_chars or self.max_chars

        headers = {"User-Agent": self.user_agent, "Accept-Language": "ko,en;q=0.9"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, headers=headers) as c:
                resp = await c.get(url)
                resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            return f"HTTP {e.response.status_code} — {url}"
        except Exception as e:
            return f"fetch 실패: {e}"

        ctype = (resp.headers.get("content-type") or "").lower()
        body = resp.content
        text = ""

        if "application/pdf" in ctype or url.lower().endswith(".pdf"):
            text = self._extract_pdf(body)
        elif "youtube.com" in url or "youtu.be" in url:
            text = self._extract_youtube(resp.text) or self._extract_html(resp.text, base_url=str(resp.url))
        elif "html" in ctype or "xml" in ctype:
            text = self._extract_html(resp.text, base_url=str(resp.url))
        elif "json" in ctype:
            text = resp.text
        else:
            try:
                text = resp.text
            except Exception:
                text = "(바이너리 콘텐츠)"

        text = text.strip()
        if not text:
            return f"본문 추출 실패 ({url})"

        truncated = ""
        if len(text) > max_chars:
            truncated = f"\n\n... (잘림, 전체 {len(text):,}자 중 {max_chars:,}자만)"
            text = text[:max_chars]

        out = f"# {url}\n\n{text}{truncated}"

        # LLM 요약 옵션
        if prompt:
            try:
                from core.model_router import ModelRouter
                router = ModelRouter()
                r = await router.chat([
                    {"role": "system", "content": "다음 웹 페이지 내용에 대한 사용자 질문에 답하라. 출처는 항상 명시."},
                    {"role": "user", "content": f"질문: {prompt}\n\n페이지 ({url}):\n{text[:6000]}"},
                ])
                summary = r.get("message", {}).get("content", "").strip()
                if summary:
                    out = f"# {url}\n\n## 요약 (질문: {prompt})\n{summary}\n\n## 본문 일부\n{text[:2000]}{truncated}"
            except Exception as e:
                logger.warning(f"fetch 요약 실패: {e}")
        return out

    # ── 본문 추출 ──────────────────────────────────────────

    def _extract_html(self, html: str, base_url: str = "") -> str:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            # fallback — 매우 거친 태그 제거
            return re.sub(r"<[^>]+>", "", html)

        soup = BeautifulSoup(html, "lxml" if self._has_lxml() else "html.parser")

        # 노이즈 제거
        for tag in soup(["script", "style", "noscript", "nav", "footer", "aside",
                         "form", "iframe", "svg", "header"]):
            tag.decompose()

        # 제목
        title_el = soup.find("title")
        title = title_el.get_text(strip=True) if title_el else ""

        # 본문 우선순위: <main>, <article>, <div role="main">, body
        body = (
            soup.find("main")
            or soup.find("article")
            or soup.find(attrs={"role": "main"})
            or soup.body
            or soup
        )

        # 텍스트 + 줄바꿈 보존
        text = body.get_text("\n", strip=True)
        # 연속 빈 줄 정리
        text = re.sub(r"\n{3,}", "\n\n", text)

        return f"제목: {title}\n\n{text}" if title else text

    def _extract_youtube(self, html: str) -> str:
        """유튜브는 JS 렌더 기반 — 초기 HTML의 ytInitialData JSON과 meta 태그에서 추출."""
        import json as _json
        out_parts: list[str] = []

        # og:/twitter meta
        for pat, label in [
            (r'<meta\s+property="og:title"\s+content="([^"]+)"', "제목"),
            (r'<meta\s+property="og:description"\s+content="([^"]+)"', "설명"),
            (r'<meta\s+property="og:image"\s+content="([^"]+)"', "이미지"),
            (r'<meta\s+name="description"\s+content="([^"]+)"', "meta설명"),
            (r'<meta\s+name="keywords"\s+content="([^"]+)"', "키워드"),
            (r'<link\s+rel="canonical"\s+href="([^"]+)"', "정식URL"),
        ]:
            m = re.search(pat, html)
            if m:
                out_parts.append(f"{label}: {m.group(1)}")

        # ytInitialData JSON
        m = re.search(r"var ytInitialData\s*=\s*(\{.*?\});\s*</script>", html, re.DOTALL)
        if m:
            try:
                data = _json.loads(m.group(1))
                header = data.get("header", {})
                meta = data.get("metadata", {})
                mr = meta.get("channelMetadataRenderer", {}) if isinstance(meta, dict) else {}
                if mr:
                    for k in ("title", "description", "externalId", "keywords", "vanityChannelUrl", "channelUrl"):
                        v = mr.get(k)
                        if v:
                            out_parts.append(f"채널.{k}: {v}")
                # subscriber / video count — c4TabbedHeaderRenderer
                h = header.get("c4TabbedHeaderRenderer", {}) if isinstance(header, dict) else {}
                for k in ("title", "subscriberCountText", "videosCountText"):
                    v = h.get(k)
                    if isinstance(v, dict):
                        v = v.get("simpleText") or v.get("accessibility", {}).get("accessibilityData", {}).get("label")
                    if v:
                        out_parts.append(f"{k}: {v}")
                # 최근 탭의 비디오 제목 몇 개
                try:
                    tabs = data["contents"]["twoColumnBrowseResultsRenderer"]["tabs"]
                    videos: list[str] = []
                    def _walk(obj):
                        if len(videos) >= 10:
                            return
                        if isinstance(obj, dict):
                            if "videoRenderer" in obj or "gridVideoRenderer" in obj:
                                r = obj.get("videoRenderer") or obj.get("gridVideoRenderer")
                                t = r.get("title", {})
                                txt = t.get("simpleText") or "".join(
                                    run.get("text", "") for run in t.get("runs", [])
                                )
                                if txt:
                                    videos.append(txt)
                                return
                            for v in obj.values():
                                _walk(v)
                        elif isinstance(obj, list):
                            for v in obj:
                                _walk(v)
                    _walk(tabs)
                    if videos:
                        out_parts.append("최근 영상:\n" + "\n".join(f"  - {v}" for v in videos[:10]))
                except Exception:
                    pass
            except Exception as e:
                logger.debug(f"ytInitialData 파싱 실패: {e}")

        return "\n".join(out_parts) if out_parts else ""

    def _extract_pdf(self, data: bytes) -> str:
        try:
            import pymupdf
            doc = pymupdf.open(stream=data, filetype="pdf")
            pages = []
            for i, page in enumerate(doc, 1):
                pages.append(f"-- page {i} --\n{page.get_text()}")
                if i >= 30:  # 너무 큰 PDF 방어
                    break
            doc.close()
            return "\n\n".join(pages)
        except ImportError:
            return "PDF 처리에 pymupdf 필요"

    @staticmethod
    def _has_lxml() -> bool:
        try:
            import lxml  # noqa
            return True
        except ImportError:
            return False
