# 테스트 가이드

## 실행 요약

```bash
source .venv/bin/activate

# 단위 테스트 (빠름, ~1.5초, LLM 불필요)
python tests/test_unit.py

# E2E (전체, Ollama 필요, ~16초)
python tests/test_e2e.py

# E2E 모드 선택
python tests/test_e2e.py --fast       # LLM 제외 (~1초)
python tests/test_e2e.py --slow       # LLM만 (~14초)
python tests/test_e2e.py --no-color   # 색상 끄기
```

---

## 테스트 커버리지

### 단위 테스트 (`test_unit.py`) — **38개 (v0.13)**

| 섹션 | 테스트 | 검증 대상 |
|---|---|---|
| tool_runner 엣지 | 8 | 파싱 기본/다중/빈 입력/미닫힘/name 누락/XML 문자/strip/display 포맷 |
| path_guard | 3 | 홈 허용, /etc 차단, /tmp 허용 |
| input_guard | 1 | 인젝션 대소문자/공백 변주 |
| orchestrator | 1 | 세션 격리 |
| 봇 분할 | 3 | 텔레그램/디스코드 청크, 개행 경계 |
| 메트릭 | 1 | MetricsCollector + Prometheus 포맷 |
| 세션 저장소 | 2 | save/load/delete + latest() |
| 스킬 | 1 | save/load/delete + addendum |
| 신규 도구 | 5 | delegate, git non-repo, browser URL/없는파일, watcher, 빈 content 경고 |
| TOP 4 (v0.12) | 3 | profile CRUD + addendum, planner/reviewer 초기화 |
| 로드맵 잔여 (v0.13) | 6 | audit 체인+변조감지, checkpoint create-restore, RouterStrategy 매칭, OllamaPool 초기화, feedback 기록, secrets fallback |

### E2E 테스트 (`test_e2e.py`) — 20개

| 섹션 | 테스트 | 검증 대상 |
|---|---|---|
| 샌드박스/설정 | 3 | 생성, .env 격리, local yaml 병합 |
| 도구 레이어 | 3 | 파일 R/W/D, 셸 실행, sleep |
| 입력 보안 | 3 | 신뢰 통과, 비신뢰 명령어 차단, 인젝션 차단 |
| 메모리 | 3 | 옵시디언 로더, RAG 인덱싱+검색, 증분 동기화 |
| 에이전트 | 3 | 등록, TaskAgent CRUD, 보안 배너 |
| LLM 연동 | 5 | 헬스체크, 간단한 질의, 미설치 모델 에러, 빈 응답 재시도, 도구 호출 |

### 태그 분류
- `tag="fast"` (기본) — LLM/외부 서비스 불필요
- `tag="slow"` — Ollama + gemma4:e4b + nomic-embed-text 필요

---

## 샌드박스 환경 (`tests/sandbox.py`)

### 핵심 원리
프로덕션 `~/.env`, `config/settings.local.yaml`을 건드리지 않기 위해 **임시 디렉토리 + 환경변수 재바인딩**.

### 환경변수 오버라이드
```
RAPHAEL_CONFIG_DIR    → settings.local.yaml 위치
RAPHAEL_PROJECT_ROOT  → .env 위치
RAPHAEL_SESSIONS_DIR  → 세션 저장소 (test_session_*)
RAPHAEL_SKILLS_DIR    → 스킬 저장소 (test_skill_*)
```

### 사용 패턴
```python
from tests.sandbox import Sandbox

with Sandbox.create() as sb:
    sb.write_note("note.md", "# content")

    # 이 블록 안에서 모든 설정 조작은 sb에만 영향
    from config.settings import save_local_settings
    save_local_settings({"models": {"default": "gemma4-e2b"}})

    # 프로덕션 .env는 변경되지 않음
# cleanup 자동 수행 (경로 원복 + 임시 디렉토리 삭제)
```

### 기본 allowed_paths
샌드박스는 `allowed_paths`에 다음을 자동 포함:
- `sb.root` — 샌드박스 루트
- `$HOME` — 홈 디렉토리
- `/tmp`, `/var/folders`, `/private` — macOS 임시 디렉토리

---

## 테스트 러너 출력 예

```
Raphael E2E QA — 샌드박스 모드
  sandbox: /var/folders/.../raphael_sandbox_xxxx

── 1. 샌드박스 & 설정 ──
  [PASS] config :: 샌드박스 생성
  [PASS] config :: .env 저장 (격리 확인)
  [PASS] config :: local yaml 저장

── 2. 도구 레이어 ──
  [PASS] tools :: 파일 R/W/D
  ...

=============================================================
결과: 18/20 PASS / 0 FAIL / 2 SKIP
```

SKIP은 `nomic-embed-text` 미설치 등 환경 이슈 시 자동 처리.

---

## 새 테스트 추가

### 단위 테스트
`tests/test_unit.py`에 함수 추가 후 `main()`에서 `check(name, fn)` 또는 `await acheck(name, coro_fn)` 호출.

```python
def test_my_feature():
    from myappe.module import do_thing
    result = do_thing()
    _assert(result == expected, "불일치")

# main()에 등록
check("내 기능 테스트", test_my_feature)
```

### E2E 테스트
`tests/test_e2e.py`에 async 함수 추가:

```python
async def t_my_flow(sb, router):
    # ...
    assert condition, "메시지"

# main()에서 등록
await run("my_section", "내 흐름", t_my_flow, sb, router, tag="fast")
# LLM이 필요하면 tag="slow"
```

### 스킵 처리
```python
async def t_needs_model(router):
    installed = await router.list_installed_models()
    if "my-model:tag" not in installed:
        raise SkipTest("my-model 미설치")
    # 실제 테스트 ...
```

---

## 수동 검증 체크리스트

LLM 행동 변화 검증 시 자동화만으로 부족할 때:

### CLI
- [ ] `raphael status`가 에이전트 4개 + 모델 목록 출력
- [ ] `raphael cli ask "hi" --json`이 유효한 JSON 반환
- [ ] `raphael cli chat` → 메시지 하나 보낸 후 `/exit` → `raphael cli chat --continue`로 이어짐
- [ ] `raphael cli session list` 출력
- [ ] `raphael cli skill create test -d "desc"` 후 `raphael cli ask "hi" --skill test` 동작

### 웹 UI
- [ ] `raphael web` 기동 후 브라우저 http://localhost:7860 접속
- [ ] 모델 드롭다운에 ✓ / (미설치) 표시
- [ ] 메시지 전송 시 🔧 도구 실행 진행이 실시간 표시됨
- [ ] 설정 탭 "폴더 선택" 버튼이 네이티브 다이얼로그 열림 (macOS Finder)
- [ ] 📤 내보내기 아코디언 → 마크다운 출력 확인
- [ ] 브라우저 새로고침 후에도 대화 이어짐

### 봇 (토큰 + user_id 등록 후)
- [ ] `/start` 응답
- [ ] 일반 메시지 → 타이핑 표시 + 응답
- [ ] 미등록 계정이 메시지 → 거부 + user_id 안내
- [ ] 긴 응답 (~5000자) → 자동 분할 전송
- [ ] `/reset` → 대화 초기화

### Health API
- [ ] `raphael health --port 7862 &`
- [ ] `curl /health` → JSON 응답 (status/agents/sessions)
- [ ] `curl /metrics` → Prometheus text
- [ ] 채팅 몇 번 후 `curl /tokens` → 토큰 누적

---

## CI 통합 예

### GitHub Actions
```yaml
name: tests
on: [push, pull_request]
jobs:
  unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: '3.11'}
      - run: |
          python -m venv .venv
          source .venv/bin/activate
          pip install -e .
          python tests/test_unit.py
          python tests/test_e2e.py --fast --no-color
```

E2E `--slow`는 Ollama 서버가 필요하므로 self-hosted runner 또는 docker-compose로 Ollama 기동 후 실행.

---

## 회귀 테스트 기대치

주요 PR 후 반드시 확인:
- `test_unit.py`: **38/38 PASS, 0 FAIL** (v0.13 기준)
- `test_e2e.py --fast`: **13/13 PASS, 0 FAIL** (약 1초)
- `test_e2e.py` (전체): **18/20 PASS, 0 FAIL, 2 SKIP** (nomic-embed-text 없을 때) 또는 **20/20 PASS**
