# 아키텍처 (v0.13)

## 시스템 개요

```
┌─────────────────────────────────────────────────────────────────────┐
│                          사용자 인터페이스                             │
│   CLI · Web UI · Telegram · Discord · Slack · Voice · Tray          │
│              Health API (FastAPI)  ·  File Watcher                  │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│              Orchestrator (세션 격리, 인젝션 방어, 메트릭)              │
└─────────────────────────────────────────────────────────────────────┘
                                   │
         ┌─────────────────────────┼─────────────────────────┐
         ▼                         ▼                         ▼
┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
│  Coding Agent    │   │ Research Agent   │   │  Note / Task     │
│ (file, exec,     │   │ (RAG, web search)│   │                  │
│  web, git,       │   │                  │   │                  │
│  delegate)       │   │                  │   │                  │
└──────────────────┘   └──────────────────┘   └──────────────────┘
         │                         │                         │
         └─────────┬───────────────┴────────────┬────────────┘
                   ▼                            ▼
      ┌─────────────────────────┐  ┌─────────────────────────┐
      │    Tool Registry        │  │   RAG Manager           │
      │  file_reader/writer     │  │   ChromaDB + Obsidian   │
      │  executor/python        │  │   증분 sync_vault       │
      │  web_search             │  │   병렬 임베딩            │
      │  git_tool               │  └─────────────────────────┘
      │  delegate               │              │
      └─────────────────────────┘              │
                   │                           │
                   └───────────┬───────────────┘
                               ▼
                 ┌─────────────────────────────┐
                 │      ModelRouter            │
                 │  - 이벤트 루프별 클라이언트   │
                 │  - 지수 백오프 재시도        │
                 │  - 빈 응답 재시도            │
                 │  - 토큰 통계                 │
                 │  - ModelNotInstalledError   │
                 └─────────────────────────────┘
                               │
                               ▼
                     ┌───────────────────┐
                     │  Ollama (gemma4)  │
                     └───────────────────┘
```

## 모듈 구조

```
raphael/
├── core/                       # 코어 프레임워크
│   ├── model_router.py         # Ollama 연결, 재시도, 토큰, 스트리밍, pool 통합
│   ├── ollama_pool.py          # 다중 Ollama 서버 풀 + least-busy 선택  [v0.13]
│   ├── router_strategy.py      # auto-routing 규칙 평가 (모델 + 에이전트)  [v0.13]
│   ├── agent_base.py           # ReAct 루프 + 대화 압축 + 위험 도구 승인 + 활동 훅
│   ├── orchestrator.py         # 에이전트 관리, 세션 격리, 경고 배너, profile 주입, auto-route
│   ├── tool_runner.py          # 도구 태그 파싱/디스패치/실행 + audit + 스트리밍 필터
│   ├── input_guard.py          # 프롬프트 인젝션 방어
│   ├── session_store.py        # CLI 세션 영속화 + 자동 태깅 [v0.13]
│   ├── skills.py               # 스킬 시스템 (~/.raphael/skills/)
│   ├── profile.py              # 사용자 장기 프로필 (facts.json)  [v0.12]
│   ├── activity_log.py         # 통합 활동 로거 (JSONL + 콘솔 + 콜백)
│   ├── audit.py                # 변조 방지 감사 로그 (SHA256 chain)  [v0.13]
│   ├── checkpoint.py           # 파일 작업 체크포인트 + 롤백  [v0.13]
│   ├── feedback.py             # 사용자 피드백 기록  [v0.13]
│   ├── secrets.py              # OS Keychain 시크릿 (fallback .env)  [v0.13]
│   ├── plugin_loader.py        # entry_points 기반 외부 플러그인  [v0.13]
│   ├── mcp_client.py           # MCP 서버 stdio 클라이언트  [v0.12]
│   ├── prompts.py              # 공통 시스템 프롬프트 조각
│   └── file_picker.py          # OS 네이티브 폴더 선택
│
├── memory/                     # 장기 기억
│   ├── obsidian_loader.py      # MD 파싱, 헤딩 기반 청킹
│   ├── rag.py                  # ChromaDB + 증분 sync + 병렬 임베딩
│   └── conversation_index.py   # 세션 대화 의미 검색 인덱스  [v0.13]
│
├── tools/                      # 에이전트 도구
│   ├── file_reader.py          # + path_guard
│   ├── file_writer.py          # + path_guard + checkpoint
│   ├── executor.py             # subprocess, 타임아웃, 로그
│   ├── web_search.py           # DuckDuckGo + ddgs fallback + sanitize
│   ├── git_tool.py             # status/diff/log/commit
│   ├── browser_tool.py         # 파일/URL 기본 브라우저 열기
│   ├── screenshot_tool.py      # 화면 캡처  [v0.12]
│   ├── clipboard_tool.py       # 시스템 클립보드  [v0.12]
│   ├── notification_tool.py    # 시스템 알림  [v0.13]
│   ├── calendar_tool.py        # 캘린더 (osascript / ICS)  [v0.13]
│   ├── email_tool.py           # IMAP/SMTP  [v0.13]
│   ├── converter_tool.py       # md→html/pdf, csv→차트, 이미지  [v0.13]
│   ├── path_guard.py           # allowed_paths 검증
│   └── tool_registry.py        # 도구 등록/조회
│
├── agents/                     # 에이전트 (6개)
│   ├── coding_agent.py
│   ├── research_agent.py
│   ├── note_agent.py
│   ├── task_agent.py
│   ├── planner_agent.py        # 작업 분해 + delegate  [v0.12]
│   └── reviewer_agent.py       # 산출물 비판적 검토  [v0.12]
│
├── interfaces/                 # 사용자 인터페이스 (8개)
│   ├── cli.py                  # Typer (chat/ask/session/skill/profile/...)
│   ├── web_ui.py               # Gradio (세션 탭 + 채팅 + 설정)
│   ├── telegram_bot.py         # allowlist + 세션 + 분할 + verbose 토글
│   ├── discord_bot.py          # 동일 패턴
│   ├── slack_bot.py            # Socket Mode  [v0.13]
│   ├── voice.py                # STT(Whisper) + TTS(say/espeak)  [v0.13]
│   ├── tray_app.py             # macOS rumps / Linux pystray  [v0.13]
│   ├── health_api.py           # FastAPI /health /metrics /tokens
│   └── file_watcher.py         # watchdog 파일 훅
│
├── config/
│   ├── settings.yaml           # 기본 (git 추적)
│   ├── settings.local.yaml     # 로컬 오버라이드 (git 제외)
│   └── settings.py             # 로더 + rebind_paths
│
├── tests/
│   ├── sandbox.py              # 환경변수 기반 격리
│   ├── test_unit.py            # 38개 단위 테스트  [v0.13]
│   └── test_e2e.py             # 20개 E2E (--fast / --slow)
│
├── docs/                       # 기술 문서 (8개)
│   ├── README.md               # 인덱스
│   ├── ARCHITECTURE.md
│   ├── FEATURES.md
│   ├── API_REFERENCE.md
│   ├── CHANGELOG.md
│   ├── SECURITY.md
│   ├── TESTING.md
│   └── ROADMAP.md              # 24개 항목 모두 ✅
│
├── main.py                     # Typer 엔트리 (raphael / 23개 명령)
├── HowToUse.md                 # 사용자 가이드
├── install.sh / uninstall.sh
├── Dockerfile                  # 컨테이너 이미지  [v0.13]
├── docker-compose.yml          # Raphael + Ollama  [v0.13]
└── pyproject.toml              # entry_points: raphael, raphael.tools, raphael.agents
```

## 핵심 데이터 흐름

### 1. 사용자 요청 → 응답 (전체 경로)

```
User Input
    │
    ▼
Interface (CLI/Web/Bot)
    │ source=InputSource.X, session_id=Y
    ▼
Orchestrator.route()
    │ ┌─ input_guard.validate_input() ────┐
    │ │   - 비신뢰 소스면 명령어/인젝션 차단 │
    │ │   - 경고 배너 첨부 대상 수집         │
    │ └───────────────────────────────────┘
    │ ┌─ 세션 복원 (session_id 있으면) ─────┐
    │ │   agent._conversation ← sessions[id]│
    │ └───────────────────────────────────┘
    ▼
Agent.handle()
    │ ┌─ _call_model() ReAct 루프 ────────┐
    │ │  ① add_message(user, sanitized)   │
    │ │  ② _maybe_compact() (>30턴 시 요약)│
    │ │  ③ router.chat() [재시도 + 빈응답] │
    │ │  ④ parse_tool_calls(response)     │
    │ │  ⑤ 위험 도구면 approval_callback  │
    │ │  ⑥ execute_tool_call() × N        │
    │ │  ⑦ add_message(user, tool_results)│
    │ │  ⑧ 도구 없으면 return             │
    │ │  (최대 4회 반복)                  │
    │ └───────────────────────────────────┘
    ▼
Orchestrator.route() 후처리
    │  세션 저장 + 경고 배너 첨부
    ▼
Interface로 응답 반환
```

### 2. ModelRouter 이벤트 루프 관리

```
router.chat(messages)
    │
    ├─ _get_client() ─────────────────────────┐
    │                                         │
    │   현재 이벤트 루프 확인                   │
    │   │                                     │
    │   ├─ 이전과 동일? → 기존 클라이언트 재사용 │
    │   └─ 다르거나 없음? → 새 httpx.AsyncClient│
    │       (루프 바뀌면 이전 클라이언트 폐기)   │
    └─────────────────────────────────────────┘
    │
    ▼
_request_with_retry()
    │   최대 3회 지수 백오프 (0.5s → 1s → 2s)
    │   재시도 대상: ConnectError, ReadTimeout, RemoteProtocolError
    ▼
/api/chat 응답
    │
    ├─ 404 → ModelNotInstalledError 변환
    ├─ 빈 응답 → temperature +0.3 재시도 (1회)
    └─ 정상 → 토큰 통계 누적 후 반환
```

### 3. RAG 증분 동기화

```
rag.sync_vault()
    │
    ▼
disk_files = scan_vault()    # {source: mtime}
db_sources = collection.get() # {source: latest_mtime}
    │
    ├─ DB에만 있는 것 → _delete_source() (삭제된 파일)
    ├─ Disk에만 있는 것 → load_file() → 인덱싱 (신규)
    ├─ mtime > db_mtime  → _delete_source() → 재인덱싱 (수정)
    └─ 같은 mtime        → skip (변경 없음)
    │
    ▼
_embed_batch() with asyncio.gather + semaphore(8)
    │
    ▼
collection.add()
```

## 주요 설계 결정

### 이벤트 루프별 httpx 클라이언트 재생성
**문제**: `asyncio.run()`으로 매 CLI 호출마다 새 루프가 만들어지는데, `httpx.AsyncClient`는 생성된 루프에 바인딩되어 재사용 불가.

**해결**: `_get_client()`가 매번 현재 루프를 확인하고, 다르면 재생성. 서버(지속 루프)와 CLI(단발 루프) 양쪽 환경에서 자동 동작.

### 도구 호출 — XML 태그 기반 파싱
Ollama의 gemma4가 native function calling을 지원하지 않아, 프롬프트에 도구 사용법을 지시하고 `<tool name="X"><arg name="Y">값</arg></tool>` 태그를 정규식으로 파싱하는 방식 채택.

**장점**: 로컬 모델과 호환, 모델 무관
**단점**: 작은 모델(8B)은 태그 형식을 완벽히 따르지 않을 때가 있음 → 빈 응답 재시도 + temperature 0.3 기본값으로 안정화

### 세션 격리 — Orchestrator 레벨
에이전트가 `_conversation` 상태를 가지고 있으므로, 다중 사용자 환경에서 상태가 섞이지 않도록 `Orchestrator`가 `session_id`별로 conversation을 보관하고 라우팅 전후로 복원/저장.

**결과**: Telegram/Discord에서 여러 사용자가 동시에 같은 봇을 써도 각자의 대화만 보임.

### 대화 압축 임계값
- 30턴 초과 시 과거를 LLM으로 요약
- 최근 10턴은 원문 유지 → 단기 문맥 손실 방지
- system prompt는 항상 유지

### 경로 샌드박스 — allowed_paths
파일 도구에 `path_guard.check_path()` 강제.
- 설정값 있으면 해당 경로 하위만 허용
- 빈 값이면 기본: `$HOME` + `/tmp` + `/var/folders`
- 심볼릭 링크는 resolve해서 실제 경로로 비교

### 인젝션 방어 — 소스별 신뢰도
`InputSource` enum으로 입력 출처를 분류하고, 비신뢰 소스(RAG, 웹검색, 파일 내용, 외부)에서는 명령어 접두사와 인젝션 패턴을 자동 무력화.

### 4. 다중 Ollama 라우팅 (v0.13)

```
ModelRouter.chat(messages, model_key)
    │
    ├─ pool.servers ≥ 2 → OllamaPool 라우팅
    │   │
    │   ├─ select_for_model(model_name)
    │   │   ├─ declared_models 또는 installed_models 매칭
    │   │   └─ least-busy (active / weight 최소)
    │   │
    │   ├─ target.request("/api/chat") — 활성 카운터 ++
    │   ├─ 404 → ModelNotInstalledError
    │   └─ 실패 → fallback (단일 클라이언트)
    │
    └─ pool 비활성/단일 서버 → 기존 _request_with_retry
```

### 5. Auto-routing (v0.13)

```
Orchestrator.route(user_input, agent="coding")
    │
    ├─ RouterStrategy.decide(TaskContext)
    │   │   user_input, agent, messages_count
    │   │
    │   └─ rules 순회 → 첫 매칭 적용
    │       ├─ prefer_model="gemma4-26b" → router.switch_model
    │       └─ prefer_agent="planner"     → agent 교체
    │
    ▼
선택된 (모델, 에이전트)로 진행
```

### 6. 활동 로그 + 콜백 + audit (v0.12~v0.13)

```
Orchestrator.route() — verbose, stream_tokens, activity_callback
    │
    ▼
ActivityLogger 생성
    ├─ JSONL 영속 (~/.raphael/activity.jsonl)
    ├─ console (verbose=True 시 stderr)
    └─ on_event 콜백 (웹 UI 큐, 봇 중간 메시지)

agent._call_model
    ├─ activity.model_call_start
    ├─ 5초 주기 ticker → activity.model_call_progress
    ├─ stream_chat → token_chunk × N (StreamingTagFilter 통과)
    ├─ activity.model_call_end (토큰 통계)
    └─ tool_runner.execute_tool_call
        ├─ on_tool_call(call) 훅
        ├─ DANGEROUS_TOOLS → approval_callback
        ├─ _dispatch
        ├─ on_tool_result(result) 훅
        └─ audit.append("tool_call", ...) — SHA256 chain
```

## 외부 의존성

| 의존성 | 용도 |
|---|---|
| `ollama` (외부 프로세스) | 로컬 LLM 서빙 |
| `chromadb` | 벡터 스토어 (RAG, 대화 검색) |
| `httpx` | Ollama HTTP 클라이언트 |
| `gradio` | 웹 UI |
| `typer` | CLI |
| `python-telegram-bot` | 텔레그램 |
| `discord.py` | 디스코드 |
| `slack-bolt` (선택) | Slack |
| `fastapi` + `uvicorn` | 헬스 API |
| `watchdog` | 파일 시스템 훅 |
| `pymupdf` | PDF 파싱 |
| `loguru` | 로깅 |
| `pyyaml` + `python-dotenv` | 설정 |
| `keyring` | OS Keychain 시크릿 |
| `mcp` | MCP 클라이언트 |
| `markdown` / `weasyprint` (선택) | 변환 |
| `pandas` + `matplotlib` (선택) | CSV → 차트 |
| `Pillow` (선택) | 이미지 리사이즈 |
| `openai-whisper` (선택) | STT |
| `rumps` / `pystray` (선택) | 메뉴바/트레이 |
