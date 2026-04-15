# 기능 목록 (v0.13)

Raphael의 모든 기능을 카테고리별로 정리.

---

## 1. 인터페이스 (8개)

### 1.1 CLI (`raphael cli`)
- `chat [--continue] [--resume <id>] [--agent X] [-q]` — 대화 모드
- `ask "..." [--json] [--skill X] [--continue] [--image FILE]` — 단발성
- `model list/use/status` — 모델 관리
- `session list/show/delete/export/search/reindex` — 세션 관리 + 의미 검색
- `skill list/show/create/delete` — 스킬 관리
- `profile show/add/forget/clear` — 사용자 장기 프로필
- `memory index/search` (스텁)

**인라인 슬래시 명령** (대화 중): `/agent /model /skill /save /clear /verbose /help`

### 1.2 Web UI (`raphael web`)
- **세션** 탭: 모든 저장된 세션 조회/내용 보기
- **채팅** 탭: 모델/에이전트 드롭다운, 실시간 도구 실행 표시, 토큰 스트리밍, 내보내기/통계
- **설정** 탭: Ollama IP, 볼트 폴더 선택(네이티브), 봇 토큰, 허용 경로, 연결 테스트
- 채팅 자동 지속 (`gr.BrowserState`)

### 1.3 Telegram (`raphael telegram`)
- `allowed_users` 검증, chat_id 세션 격리, 4000자 분할
- `/start /status /model /agent /reset /verbose on|off`
- 타이핑 인디케이터

### 1.4 Discord (`raphael discord`)
- `/status /model /agent /reset /verbose`, 1900자 분할

### 1.5 Slack (`raphael slack`) [v0.13]
- Socket Mode 기반, allowed_users 검증
- `app_mention` 이벤트 처리

### 1.6 Voice (`raphael voice`) [v0.13]
- Whisper STT + 시스템 TTS (`say` / `espeak`)
- 마이크 → 텍스트 → 에이전트 → 발화 루프

### 1.7 Tray (`raphael tray`) [v0.13]
- macOS: rumps 메뉴바
- Linux: pystray 시스템 트레이
- "빠른 질문" 팝업, 웹 UI 열기

### 1.8 Health API (`raphael health`)
- FastAPI 기반, `/health` `/agents` `/tokens` `/metrics` (Prometheus)
- Orchestrator.route 자동 계측

### 보조: File Watcher (`raphael watch`)
- watchdog 기반, settings.hooks.watches 규칙

### 보조: 활동 로그 (`raphael log [-f]`)
- 모든 인터페이스 통합 JSONL 로그
- session 필터, 색상, follow 모드

---

## 2. 에이전트 (6개)

| 에이전트 | 역할 | 도구 (개수) |
|---|---|---|
| **coding** (기본) | 코드/파일/실행/Git/멀티모달/위임 | 16 |
| **research** | RAG + 웹 검색 | 2 |
| **note** | 옵시디언 노트 | 2 |
| **task** | 할일/일정 (대화 전용) | 0 |
| **planner** [v0.12] | 작업 분해 + delegate 위임 | delegate |
| **reviewer** [v0.12] | 산출물 비판적 검토 | file_reader, delegate |

### 공통 자동 기능 (AgentBase)
- **ReAct 루프** (최대 6회)
- **대화 압축** (30턴 초과 시 LLM 요약, 최근 10턴 유지)
- **빈 응답 재시도** (temperature +0.3)
- **위험 도구 승인** (`execute`, `python`, `delete_file`)
- **on_tool_call/on_tool_result 훅** (UI 실시간 갱신)
- **스트리밍 응답** (`_stream_chat` + tag filter)
- **활동 로그 자동 주입** (model_call_start/progress/end + token_chunk)
- **사용자 프로필 자동 주입** (Profile.facts → system 메시지)
- **export_markdown / export_json**

---

## 3. 도구 (24종)

### 3.1 파일 (5) — 모두 path_guard + checkpoint
- `read_file` `write_file` `append_file` `delete_file` `mkdir`

### 3.2 실행 (2) — DANGEROUS
- `execute` (셸) `python`

### 3.3 Git (4)
- `git_status` `git_diff` `git_log` `git_commit`

### 3.4 웹/외부 (3)
- `web_search` (DuckDuckGo + ddgs fallback + sanitize)
- `open_in_browser` (file/URL)
- `mcp_call` (외부 MCP 서버 호출) [v0.12]

### 3.5 시스템 입출력 (5)
- `screenshot` `clipboard_read` `clipboard_write` [v0.12]
- `notify` (시스템 알림) `speak` (TTS) [v0.13]

### 3.6 통신/일정 (3)
- `calendar_add` `email_inbox` `email_send` [v0.13]

### 3.7 변환 (4) [v0.13]
- `convert_md_to_html` `convert_md_to_pdf`
- `convert_csv_to_chart` `image_resize`

### 3.8 메모리/위임 (3)
- `remember` `forget` (사용자 프로필) [v0.12]
- `delegate` (서브에이전트 위임)

---

## 4. 메모리 / RAG

### 4.1 옵시디언 RAG (`memory/rag.py`)
- ChromaDB PersistentClient, cosine
- `index_vault()` / **`sync_vault()`** (mtime 기반 증분)
- `build_context()` 자동 sanitize
- 임베딩 병렬화 (asyncio.gather, semaphore 8)

### 4.2 옵시디언 로더 (`memory/obsidian_loader.py`)
- YAML 프론트매터 파싱
- `[[링크]]` 텍스트화
- 헤딩 1차 + 크기 2차 청킹

### 4.3 대화 검색 (`memory/conversation_index.py`) [v0.13]
- 별도 ChromaDB 컬렉션 `conversations`
- `raphael cli session search "키워드" / reindex`

### 4.4 사용자 프로필 (`core/profile.py`) [v0.12]
- `~/.raphael/facts.json`
- Orchestrator가 매 라우팅 시 system 메시지로 자동 주입

---

## 5. LLM 라우터 (`ModelRouter` + `OllamaPool` + `RouterStrategy`)

### 5.1 단일 서버 모드
- 이벤트 루프별 httpx 클라이언트 자동 재생성
- 지수 백오프 재시도 (3회)
- 빈 응답 재시도 (temperature +0.3)
- 토큰 통계 (모델별 prompt/completion/calls/latency)
- `ModelNotInstalledError` (404 → "ollama pull" 안내)
- `ensure_embedding_model(pull_if_missing=True)`
- chat / chat_stream / embed
- 이미지 첨부 지원 (`images=[...]`)

### 5.2 다중 서버 모드 [v0.13]
- `OllamaPool` — 여러 서버 등록, 각 서버 active 카운터/declared models/weight
- `select_for_model(model_name)` — least-busy + 가중치
- ModelRouter가 자동 사용 (서버 ≥ 2일 때)
- 단일 서버 fallback 보장

### 5.3 Auto-routing (`RouterStrategy`) [v0.13]
- `settings.models.routing.strategy: auto`
- 규칙 매칭 → (모델, 에이전트) 자동 전환
- 매치 조건: `agent`, `min_messages`, `token_estimate_gt/lt`, `contains_any`, `default`
- Orchestrator가 매 라우팅 시 평가

### 기본 옵션
```python
DEFAULT_OPTIONS = {"temperature": 0.3, "top_p": 0.9}
```

---

## 6. 보안

### 6.1 입력 인젝션 방어 (`input_guard.py`)
- 신뢰: CLI / WEB_UI / TELEGRAM / DISCORD
- 비신뢰: WEB_SEARCH / RAG_CONTEXT / FILE_CONTENT / EXTERNAL
- 명령어 접두사 무력화 + 인젝션 패턴 `[blocked]` 치환
- 경고 배너 응답 상단 첨부

### 6.2 파일 경로 샌드박스 (`path_guard.py`)
- `allowed_paths` 외부 거부
- 빈 값이면 `$HOME` + `/tmp` + `/var/folders` + cwd 자동 허용
- 심볼릭 링크 resolve

### 6.3 봇 allowlist
- Telegram/Discord/Slack — `allowed_users` 빈 목록 = 모두 거부
- 사용자별 세션 격리

### 6.4 위험 도구 승인
- `DANGEROUS_TOOLS = {"execute", "python", "delete_file"}`
- `approval_callback` 콜백으로 사용자 확인

### 6.5 OS Keychain 시크릿 (`secrets.py`) [v0.13]
- macOS Keychain / Linux Secret Service / Windows Credential Manager
- keyring 미설치/실패 시 `.env` fallback

### 6.6 파일 작업 체크포인트 (`checkpoint.py`) [v0.13]
- write/delete 전 자동 백업
- `~/.raphael/backups/<timestamp>__<hash>/`
- 7일 자동 정리, 수동 복원

### 6.7 Audit log (`audit.py`) [v0.13]
- 모든 도구 실행을 SHA256 hash chain으로 기록
- `~/.raphael/audit.log` (JSONL)
- `verify()` — 변조 감지 (체인 무결성)

---

## 7. 대화 / 세션

### 7.1 세션 영속화 (`session_store.py`)
- `~/.raphael/sessions/<id>.json`
- 자동 토픽 태깅 [v0.13]
- `latest()`, `list_sessions()`, `delete_session()`

### 7.2 CLI 세션 명령
- `raphael cli chat --continue / --resume`
- `raphael cli ask --continue / --resume`
- `raphael cli session list/show/delete/export/search/reindex`

### 7.3 봇 세션
- `tg:<chat_id>`, `dc:<channel_id>`, `sk:<channel_id>`
- `/reset` 명령

### 7.4 Orchestrator 격리
- `route(session_id=...)` — 세션별 conversation 주입/저장

---

## 8. 스킬 시스템 (`skills.py`)

- `~/.raphael/skills/<name>.md` (YAML frontmatter + 본문)
- `raphael cli skill list/show/create/delete`
- `raphael cli ask --skill X` (system_prompt 임시 주입)

---

## 9. 파일 시스템 훅 (`file_watcher.py`)

- watchdog 기반, settings.hooks.watches
- `path / patterns / events / agent / prompt / debounce_seconds`
- `{path}` `{event}` 플레이스홀더
- `raphael watch`

---

## 10. Plan-Execute-Reflect (메타 에이전트) [v0.12]

- `planner` — 작업 분해 + delegate 위임
- `reviewer` — 산출물 비판적 검토
- `raphael plan "task"`, `raphael review "ctx"`
- 한 응답에 여러 delegate 블록 가능 (병렬 위임)

---

## 11. MCP 클라이언트 [v0.12]

- `mcp` 라이브러리 기반 stdio MCP 서버 연결
- settings.mcp.servers
- 부팅 시 tools/list 자동 등록 → ToolRegistry에 노출
- LLM은 `<tool name="mcp_call">`로 호출

---

## 12. 플러그인 시스템 (`plugin_loader.py`) [v0.13]

- entry_points: `raphael.tools`, `raphael.agents`
- 외부 패키지 설치 → 자동 등록
- 부팅 시 importlib.metadata.entry_points 스캔

---

## 13. 운영 / 관측

### 13.1 토큰 추적
- `router.get_token_stats()` — 모델별 prompt/completion/calls/latency
- `/tokens` 엔드포인트
- 웹 UI "토큰 사용량" 버튼

### 13.2 메트릭 (`health_api.py`)
- 자동 계측 (orchestrator.route 래핑)
- Prometheus text format `/metrics`

### 13.3 로깅
- loguru 기반, 파일 rotation (10MB / 7일)

### 13.4 활동 로그 (`activity_log.py`)
- JSONL `~/.raphael/activity.jsonl`
- 7가지 이벤트: user_message, model_call_start/progress/end, token_chunk, tool_call, tool_result
- 콘솔 모드 (CLI verbose) + 콜백 (웹/봇)

### 13.5 사용자 피드백 (`feedback.py`) [v0.13]
- `~/.raphael/feedback.jsonl`
- `raphael feedback` 통계

### 13.6 자동 업데이트 (`raphael update`) [v0.13]
- git pull + pip install -e .

### 13.7 Docker 배포 [v0.13]
- `Dockerfile` + `docker-compose.yml`
- Raphael + Ollama + 볼륨

---

## 14. 멀티모달 [v0.12]

- ModelRouter.chat에 `images=[]` 파라미터
- 파일 경로 또는 base64 자동 처리
- vision 모델 필요 (gemma3-vision, llava 등)
- CLI: `raphael cli ask "..." --image FILE`
- 도구: `screenshot`, `clipboard_read` (이미지 컨텍스트 즉시 활용)

---

## 15. 개발/테스트

### 15.1 샌드박스 (`tests/sandbox.py`)
- 환경변수 기반 격리 (RAPHAEL_CONFIG_DIR, RAPHAEL_PROJECT_ROOT)
- 컨텍스트 매니저
- 자동 cleanup

### 15.2 단위 테스트 (38개) [v0.13]
- tool_runner, path_guard, input_guard, orchestrator, 봇 분할, 메트릭
- 세션 store, 스킬, profile, planner/reviewer
- audit chain + 변조 감지, checkpoint, RouterStrategy, OllamaPool, feedback, secrets

### 15.3 E2E (20개)
- `--fast` (~1s) / `--slow` (~14s)

---

## 16. 설치 / 배포

### 16.1 install.sh
- macOS / Linux 자동 감지
- venv + pip install -e .
- zsh / bash / fish alias 자동 등록 (마커 기반 멱등)

### 16.2 Docker [v0.13]
- `docker compose up` — Raphael + Ollama 한 번에

### 16.3 entry point
- `raphael` 명령어 (pyproject.toml `[project.scripts]`)
- `raphael` 단독 실행 시 `cli chat` 자동 진입 (claude 스타일)
