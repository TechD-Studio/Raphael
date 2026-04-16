# 검색 기능 개선 로드맵

## 현황 (v0.1.12)

현재 `web_search` 도구는 DuckDuckGo HTML 스크래핑을 기본으로 하고,
Brave/Tavily/Serper/SearXNG 키가 있으면 자동 우선 사용.
검색 결과는 제목+snippet+URL만 반환하므로 **가격, 스펙, 실시간 수치** 등
JS 렌더링 페이지 안의 구체적 정보를 못 읽어오는 문제 있음.

---

## ✅ 1단계 — 프롬프트 체인 강제 (완료)

`TOOL_USAGE_PROMPT`에 검색→fetch 체인 규칙 추가:
- snippet으로 구체적 정보 확인 불가 시 **반드시 fetch_url로 후속 탐색**
- "찾을 수 없다" 회피 답변 금지
- 쇼핑 질문에 `site:danawa.com` 등 도메인 힌트 포함 예시

## ✅ 2단계 — 자동 본문 수집 (완료)

`web_search` 도구에 `auto_fetch` 파라미터 추가 (기본값 2):
- 검색 후 상위 N개 URL의 본문을 FetchTool로 자동으로 읽어 결과에 포함
- snippet만으로 판단 불가한 경우에도 LLM이 본문 텍스트에서 정보 추출 가능
- `max_chars=4000`으로 제한해 컨텍스트 오버플로 방지

---

## 🔵 3단계 — 쇼핑/가격 전문 검색 (검토 대상)

### 3-A: 네이버 쇼핑 API

- **엔드포인트**: `https://openapi.naver.com/v1/search/shop.json`
- **필요**: NAVER_CLIENT_ID + NAVER_CLIENT_SECRET (무료 25,000건/일)
- **반환**: 상품명, 최저가, 카테고리, 링크, 이미지, 쇼핑몰명
- **구현 스케치**:
  ```python
  async def _search_naver_shop(self, query, max_results):
      resp = await client.get(
          "https://openapi.naver.com/v1/search/shop.json",
          params={"query": query, "display": max_results, "sort": "asc"},
          headers={"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": cs},
      )
      # response.items → [{title, link, lprice, hprice, mallName, ...}]
  ```
- **장점**: 한국 쇼핑 최저가에 최적, 직접 가격 반환
- **공수**: 2~3h

### 3-B: Serper 쇼핑 탭

- **기존 Serper API에 `"type": "shopping"` 추가**
- Google Shopping 결과 직접 반환 (price, source, link)
- SERPER_API_KEY 이미 지원하므로 확장 쉬움
- **공수**: 1~2h

### 3-C: 다나와 직접 파싱

- `https://search.danawa.com/dsearch.php?query=...` 페이지 fetch
- BeautifulSoup으로 `.prod_pricelist` 등 가격 엘리먼트 추출
- API 키 불필요, 무료
- **리스크**: HTML 구조 변경 시 깨짐, IP 차단 가능
- **공수**: 3~4h

### 3-D: 쿠팡 파트너스 API

- CPC 기반, 수익화 가능
- 인증 복잡 (HMAC), 상품 검색 제한적
- **공수**: 4~6h
- **권장**: 우선순위 낮음

### 추천 순서

1. **3-A (네이버 쇼핑 API)** — 가장 실용적, 무료, 한국 쇼핑에 최적
2. **3-B (Serper 쇼핑)** — 기존 키 활용, 글로벌 가격 비교
3. **3-C (다나와)** — API 키 없이 가능하지만 취약

### 통합 설계

```yaml
# settings.yaml
tools:
  web_search:
    backend_order: [brave, serper, ddg_html, ddgs]
    shopping:
      enabled: true
      backends: [naver_shop, serper_shopping]
      auto_detect_keywords: [최저가, 가격, 얼마, 구매, 쇼핑, price, buy, cheap]
```

쇼핑 키워드 감지 시 일반 검색 대신 쇼핑 백엔드를 우선 호출.
결과에 가격/쇼핑몰/링크가 구조화되어 LLM이 바로 답변 가능.
