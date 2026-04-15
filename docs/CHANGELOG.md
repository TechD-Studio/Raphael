# 구현 히스토리

개발 과정에서 단계별로 추가된 기능의 연대기적 기록.

---

## Phase 1 — 코어 프레임워크
**목표**: 기본 인프라 구축

- `config/settings.py` — YAML 로더 + `settings.local.yaml` 병합 + `${VAR}` 치환
- `core/model_router.py` — Ollama 연결, 모델 선택/전환, 헬스체크, chat/stream/embed
- `core/agent_base.py` — 에이전트 베이스 클래스 (대화 관리, 툴 바인딩)
- `core/orchestrator.py` — 에이전트 등록/조회/라우팅
- `main.py` — Typer 엔트리포인트

---

## Phase 2 — 메모리 시스템

- `memory/obsidian_loader.py` — MD 파싱 + YAML 프론트매터 + 옵시디언 링크 텍스트화 + 헤딩/크기 청킹
- `memory/rag.py` — ChromaDB 인덱싱 + 유사도 검색 + 컨텍스트 조립

---

## Phase 3 — 툴 레이어

- `tools/file_reader.py` — txt/md/pdf(pymupdf)/csv/코드
- `tools/file_writer.py` — write/append/delete/mkdir
- `tools/executor.py` — subprocess asyncio + 타임아웃 + 로그 기록
- `tools/tool_registry.py` — 도구 등록/조회 레지스트리

---

## Phase 4 — 에이전트

- `agents/coding_agent.py`
- `agents/research_agent.py`
- `agents/note_agent.py`
- `agents/task_agent.py` — JSON 파일 기반 CRUD

---

## Phase 5 — 인터페이스

- `interfaces/cli.py` — Typer 서브그룹 (chat/ask/model/memory)
- `interfaces/web_ui.py` — Gradio ChatInterface
- `interfaces/telegram_bot.py`
- `interfaces/discord_bot.py`

---

## v0.2 — 설정 UX

- `raphael onboard` — 인터랙티브 설정 마법사
- 웹 UI "설정" 탭 — Ollama IP/포트/볼트/토큰
- 설정 변경 기능: `save_local_settings()`, `save_env()`
- 옵시디언 볼트 선택: OS 네이티브 다이얼로그 (`core/file_picker.py`)
  - Mac: osascript (Finder)
  - Linux: zenity → kdialog → tkinter fallback

---

## v0.3 — 배포/설치

- `install.sh` — macOS/Linux 자동 감지 + venv + alias 등록 (zsh/bash/fish)
- `uninstall.sh` — 마커 기반 안전한 제거
- `raphael` 바이너리 (`pyproject.toml` entry_point)

---

## v0.4 — 안정성

- **이벤트 루프별 httpx 클라이언트**: CLI(asyncio.run per call) ↔ 서버(지속 루프) 양쪽에서 안전
- **빈 응답 재시도**: temperature +0.3으로 1회
- **`DEFAULT_OPTIONS = {temperature: 0.3, top_p: 0.9}`**: 도구 호출 안정화
- **`ModelNotInstalledError`**: 404 응답을 `ollama pull` 안내 예외로 변환
- **동적 모델 조회**: `list_installed_models()`, `switch_model_checked()`
- 웹 UI 모델 드롭다운에 ✓(설치) / (미설치) 표시

---

## v0.5 — 도구 호출 (ReAct)

- `core/tool_runner.py` — XML 태그 기반 파싱
- `core/prompts.py` — 도구 사용법 공통 프롬프트
- `AgentBase._call_model()` — ReAct 루프 (최대 4회 반복)
- 에이전트별 허용 도구 필터링
- `tools/web_search.py` — DuckDuckGo + ddgs fallback

---

## v0.6 — 보안

- `core/input_guard.py` — 입력 소스 분류 + 인젝션/명령어 패턴 감지
- `tools/path_guard.py` — 파일 경로 샌드박스 (`allowed_paths`)
- `FileReader`/`FileWriter`에 `check_path()` 강제
- Orchestrator가 비신뢰 소스 경고 시 응답에 투명성 배너 첨부
- 웹 검색 결과, RAG 컨텍스트 자동 sanitize

---

## v0.7 — 봇 강화

- **사용자 allowlist**: `settings.yaml`의 `allowed_users` 검증 (빈 목록 = 모두 거부)
- **사용자별 세션 격리**: chat_id(TG) / channel_id(DC) 기반
- **긴 응답 분할**: TG 4000자 / DC 1900자, 개행 경계 선호
- **타이핑 인디케이터**: `ChatAction.TYPING` / `channel.typing()`
- `/reset` 명령 — 세션 초기화

---

## v0.8 — 운영/관측

- **지수 백오프 재시도**: ConnectError/Timeout/RemoteProtocolError 3회
- **토큰 추적**: `ModelRouter.get_token_stats()` — 모델별 prompt/completion/calls/latency
- **대화 압축**: 30턴 초과 시 LLM 요약 + 최근 10턴 유지
- **임베딩 병렬화**: `asyncio.gather` + 세마포어(8)
- **RAG 증분 동기화**: `sync_vault()` — mtime 기반 추가/수정/삭제/unchanged
- **nomic-embed-text 자동 설치**: `ensure_embedding_model(pull_if_missing=True)`
- **Health API** (`interfaces/health_api.py`) — FastAPI 기반
  - `/health`, `/agents`, `/tokens`, `/metrics` (Prometheus text)
  - `wrap_orchestrator_with_metrics()` 자동 계측

---

## v0.9 — 웹 UI 고도화

- **도구 실행 가시화**: `on_tool_call` / `on_tool_result` 훅으로 실시간 진행 표시
- **두 단계 채팅 렌더**: 사용자 메시지 즉시 표시 → 응답 스트리밍 (제너레이터)
- **대화 지속성**: `gr.BrowserState` — 브라우저 새로고침 후에도 유지
- **내보내기/통계**: 마크다운/JSON/토큰 통계 아코디언
- **위험 도구 승인**: `approval_callback` (execute/python/delete_file)

---

## v0.10 — 테스트 인프라

- `tests/sandbox.py` — 환경변수 기반 격리 (`RAPHAEL_CONFIG_DIR`, `RAPHAEL_PROJECT_ROOT`)
- `tests/test_unit.py` — 17 → 23 단위 테스트
- `tests/test_e2e.py` — 20개 E2E 시나리오 (`--fast` / `--slow`)
- `config.settings.rebind_paths()` — 런타임 경로 재바인딩

---

## v0.11 — Claude Code 교재 패턴 이식 (옵션 B)

[wikidocs.net/book/19202 참고]

### JSON 구조화 출력
- `raphael cli ask --json` → `{response, agent, model, duration_seconds, tokens, error, session_id}`

### CLI 세션 영속화
- `core/session_store.py` — `~/.raphael/sessions/<id>.json`
- `raphael cli chat --continue / --resume <id>`
- `raphael cli ask --continue / --resume <id>`
- `raphael cli session list / show / delete / export`

### 서브에이전트 (delegate)
- 새 도구 `<tool name="delegate" agent="research" task="..."/>`
- Orchestrator를 통한 독립 세션 위임

### 병렬 멀티에이전트
- `raphael parallel "task" --agents A,B` — asyncio.gather
- 각 에이전트 독립 세션 (`parallel-<name>`)으로 상태 격리

### Git 통합
- `tools/git_tool.py` — status/diff/log/commit
- `raphael commit` — AI가 staged diff 분석 후 커밋 메시지 제안

### 스킬 시스템
- `core/skills.py` — `~/.raphael/skills/<name>.md` (YAML frontmatter)
- `raphael cli skill list / show / create / delete`
- `raphael cli ask --skill X` — 시스템 프롬프트 임시 덧붙임

### 파일 시스템 훅
- `interfaces/file_watcher.py` — watchdog 기반
- `settings.yaml`의 `hooks.watches` 규칙
- `raphael watch` — 백그라운드 감시 + 자동 에이전트 호출

---

## 현재 상태 (v0.11+)

### 규모
- **11개 모듈** (core), **7개 도구**, **4개 에이전트**, **5개 인터페이스**
- **43개 테스트** (23 unit + 20 E2E), 0 FAIL

### 외부 의존성
- ollama (로컬), chromadb, gradio, typer, fastapi, uvicorn, httpx, loguru, pyyaml, pymupdf, watchdog, python-telegram-bot, discord.py, python-dotenv

### CLI 명령 (15개)
```
status onboard parallel commit watch
web telegram discord health
cli chat / ask / model / session / skill / memory
```

### Health API 엔드포인트
- `/health` `/agents` `/tokens` `/metrics` `/docs`

---

## v0.12 — TOP 4 로드맵 완료

### #2 사용자 프로필 메모리
- `core/profile.py` — `~/.raphael/facts.json` 영속 저장 (`Fact`, `Profile`)
- `Orchestrator.route`가 매 라우팅 시 facts를 system 메시지로 자동 주입
- 신규 도구: `<tool name="remember">`, `<tool name="forget">`
- CLI: `raphael cli profile show / add / forget / clear`

### #4 Plan-Execute-Reflect
- `agents/planner_agent.py` — 작업 분해 + delegate 위임 메타 에이전트
- `agents/reviewer_agent.py` — 산출물 비판적 검토
- CLI: `raphael plan "task"`, `raphael review "context"`

### #1 멀티모달 (이미지/스크린샷)
- `ModelRouter.chat`에 `images=[]` 파라미터 추가 (vision 모델 호환)
- `tools/screenshot_tool.py` — macOS `screencapture` / Linux `grim/gnome-screenshot/scrot`
- `tools/clipboard_tool.py` — pbcopy/pbpaste, wl-copy/xclip
- 신규 도구: `<tool name="screenshot">`, `<tool name="clipboard_read/write">`
- CLI: `raphael cli ask "..." --image /path/to/img.png`

### #3 MCP 클라이언트
- `core/mcp_client.py` — stdio MCP 서버 연결 + 도구 동적 등록 (`MCPClientManager`)
- `pip install mcp` 의존성
- 도구 호출 형식: `<tool name="mcp_call"><arg name="server">github</arg><arg name="tool">create_issue</arg>...</tool>`
- CLI: `raphael mcp` (서버/도구 목록)
- settings.yaml: `mcp.servers: [...]`

### 추가된 신규 단위 테스트 (3개)
- 프로필 CRUD + addendum
- PlannerAgent / ReviewerAgent 초기화

### 지원 도구 (16종)
- 파일: `read_file`, `write_file`, `append_file`, `delete_file`, `mkdir`
- 실행: `execute`, `python`
- 웹: `web_search`
- Git: `git_status`, `git_diff`, `git_log`, `git_commit`
- 브라우저: `open_in_browser`
- 위임: `delegate`
- **프로필**: `remember`, `forget`
- **시스템**: `screenshot`, `clipboard_read`, `clipboard_write`
- **MCP**: `mcp_call`

### 에이전트 (6종)
- coding, research, note, task, **planner, reviewer**

---

## v0.13 — 로드맵 잔여 항목 + Auto-routing

### Phase 1 (사용성/운영)
- **#5** CLI 인라인 슬래시 명령 (`/agent /model /skill /save /clear /verbose /help`)
- **#16** 세션 자동 토픽 태깅 (chat 종료 시 LLM이 1~3개 영문 태그 추출)
- **#17** 사용자 피드백 (`core/feedback.py` + `raphael feedback` 통계)
- **#19** OS Keychain 시크릿 (`core/secrets.py` — keyring 우선, .env fallback / `raphael secret`)
- **#20** 파일 체크포인트 (`core/checkpoint.py` — write/delete 전 자동 백업 / `raphael rollback`)
- **#23** 자동 업데이트 (`raphael update` — git pull + pip install)
- **#24** Audit log + 변조 방지 (`core/audit.py` — SHA256 hash chain / `raphael audit verify/show`)

### Phase 2 (외부 통합)
- **#10** 알림 도구 (`tools/notification_tool.py` — osascript / notify-send)
- **#11** 캘린더 도구 (`tools/calendar_tool.py` — macOS Calendar.app + cross-platform ICS)
- **#12** 이메일 도구 (`tools/email_tool.py` — IMAP/SMTP, 비밀번호 keychain)
- **#13** Slack 봇 (`interfaces/slack_bot.py` — Socket Mode, allowlist)
- **#14** 변환 도구 (`tools/converter_tool.py` — md→html/pdf, csv→차트, 이미지 리사이즈)
- **#21** 플러그인 시스템 (`core/plugin_loader.py` — entry_points 기반 외부 도구/에이전트 자동 등록)

### Phase 3 (인프라)
- **#15** 대화 검색 (`memory/conversation_index.py` — ChromaDB 별도 컬렉션 / `raphael cli session search/reindex`)
- **#6** 웹 UI 세션 사이드바 (Tab "세션" — 목록/내용/새로고침)
- **#18** Docker (`Dockerfile` + `docker-compose.yml` + Ollama 묶음)

### Phase 4 (음성/메뉴바)
- **#7** 음성 인터페이스 (`interfaces/voice.py` — `say`/`espeak` TTS + whisper STT, `speak` 도구, `raphael voice`)
- **#9** 트레이/메뉴바 앱 (`interfaces/tray_app.py` — macOS rumps / Linux pystray, `raphael tray`)

### Phase 5 (다중 Ollama)
- **#22** OllamaPool + RouterStrategy (`core/ollama_pool.py`, `core/router_strategy.py`)
- ModelRouter가 풀 자동 활용 (서버 ≥2면 least-busy 선택, fallback 내장)
- `raphael pool` 명령 (서버 헬스/활성요청/모델 표시)

### Phase 6 (Auto-plan)
- Orchestrator가 매 라우팅 시 RouterStrategy 호출 → 모델/에이전트 자동 전환
- settings.yaml `models.routing.strategy: auto` + rules로 활성
- 큰 작업/특정 키워드 → planner 에이전트 자동 라우팅 가능

### 단위 테스트
29 → 32 (TOP 4) → **38 (Phase 1~6)** PASS
신규: audit chain + 변조 감지 / checkpoint create-restore / RouterStrategy 매칭 / OllamaPool 초기화 / Feedback 기록 / Secrets fallback

### 새 CLI 명령 (총 23개)
```
status onboard parallel commit watch web telegram discord slack health
log voice tray secret rollback audit feedback update mcp pool plan review cli
```

### 도구 (24종)
파일 5 + 실행 2 + 웹 1 + Git 4 + 브라우저 1 + 위임 1 + 프로필 2 + 시스템 3 + MCP 1
+ **알림 1 + 캘린더 1 + 이메일 2 + 변환 4 + 음성 1**

### 에이전트 (6종) — 변동 없음

---

## v0.14 — Claude Code 구독 백엔드

### 추가
- `core/claude_provider.py` — `claude` CLI subprocess wrapper
  - `--output-format json` (비스트리밍) / `stream-json` (스트리밍)
  - messages → `[ROLE]\ncontent` 형식 직렬화
  - usage 토큰 + cost_usd + session_id 메타 노출
- ModelRouter: `provider: claude_cli` 분기 (chat / chat_stream / switch_model_checked)
- settings.yaml: 새 모델 3종 (`claude-sonnet`, `claude-opus`, `claude-haiku`)
- 단위 테스트 3개 추가 (38 → 41 PASS)

### 사용
```bash
raphael cli model use claude-sonnet
raphael cli ask "..."             # 본인 Claude 구독으로 호출
```

### 의미
Anthropic API key 없이도 Pro/Max 구독으로 Sonnet/Opus/Haiku 사용 가능.
Auto-routing과 결합하면 쉬운 작업은 로컬 gemma4, 어려운 작업은 claude로 자동 분배.

---

## (구) 지원 도구 (11종)
- `read_file` `write_file` `append_file` `delete_file` `mkdir`
- `execute` `python`
- `web_search`
- `git_status` `git_diff` `git_log` `git_commit`
- `delegate`
