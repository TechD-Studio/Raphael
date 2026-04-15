# Raphael 로드맵 — 24개 개선 제안

현재 v0.11+에서 추가/보완 가능한 항목 모음. 각 항목은 **동기 → 구현 스케치 → 영향 모듈 → 예상 공수 → 의존성** 순으로 정리.

## 📊 우선순위 매트릭스

```
                  Low Effort         Medium Effort       High Effort
                  ────────────────────────────────────────────────────
   High Impact │  #2 Profile Memory  #1 Multimodal       #3 MCP Client
               │  #5 Slash Commands  #22 Multi-Ollama    #4 Plan-Exec
               │                     #6 Web Sidebar
               │
   Med Impact  │  #16 Auto Tagging   #7 Voice I/O        #9 Tray App
               │  #10 Reminders      #8 Clipboard        #11 Calendar
               │                     #14 Converters      #12 Email
               │
   Low Impact  │  #20 Checkpoints    #18 Docker          #21 Plugins
               │  #23 Auto Update    #19 Keychain        #24 Audit Log
               │  #17 Feedback       #15 Convo Search    #13 Slack
```

## 🗺 권장 단계별 진행

```
Phase A (필수 인프라)      Phase B (지능)          Phase C (외부 통합)
─────────────────────     ──────────────────     ──────────────────
#2 사용자 프로필           #4 Plan-Execute        #3 MCP 클라이언트
#22 다중 Ollama            #15 대화 검색          #11 캘린더
#5 슬래시 명령             #16 자동 태깅          #12 이메일
#6 세션 사이드바           #17 피드백 루프        #10 알림

Phase D (멀티모달)        Phase E (운영)          Phase F (안전)
─────────────────────     ──────────────────     ──────────────────
#1 이미지/스크린샷         #18 Docker             #19 Keychain
#7 음성 입출력             #21 플러그인           #20 체크포인트
#8 클립보드/스크린샷       #23 자동 업데이트      #24 Audit Log
#14 파일 변환              #9 메뉴바 앱           #13 Slack
```

---

## 🔴 최우선 (TOP 4) — ✅ 모두 완료 (v0.12)

### #1 ✅ 멀티모달 — 이미지/스크린샷 처리
- **카테고리**: 입력 확장 / 지능
- **동기**: 텍스트만 처리 가능 → "이 화면에 뭐가 잘못됐어?" 같은 자연스러운 요청 불가
- **스케치**:
  - Ollama가 vision 모델(`gemma3-vision`, `llava`) 지원하는 경우 `/api/chat`의 `images: [base64]` 필드 사용
  - 웹 UI: `gr.Image` 업로드 컴포넌트 + 메시지에 첨부
  - CLI: `raphael cli ask "분석" --image /path/to/screenshot.png`
  - `tools/screenshot_tool.py` — `screencapture` (macOS) / `gnome-screenshot` (Linux)
- **영향**: `core/model_router.py`, `interfaces/web_ui.py`, `interfaces/cli.py`, 새 도구
- **공수**: 4~6h
- **의존**: vision 모델 사전 설치 (`ollama pull gemma3:vision` 등)

### #2 ✅ 장기 사용자 프로필 메모리 (Persistent Facts)
- **카테고리**: 메모리
- **동기**: 매 세션 "내가 누군지" 다시 알려야 함 — 비서로서 답답
- **스케치**:
  - `~/.raphael/facts.json` — 사용자 사실 영속 저장
  - 새 도구 `<tool name="remember"><arg name="fact">사용자 dh는 Python 개발자</arg></tool>`
  - 모든 에이전트의 system_prompt에 facts 자동 주입 (Orchestrator.route에서 prepend)
  - `raphael cli memory profile show / clear / forget <pattern>`
  - 자동 추출 옵션: 응답 후 LLM이 "기억할 만한 정보가 있나?" 자기검토
- **영향**: `core/profile.py` (신규), `core/orchestrator.py`, `core/tool_runner.py`, `core/agent_base.py`
- **공수**: 2~3h

### #3 ✅ MCP 클라이언트
- **카테고리**: 외부 통합
- **동기**: GitHub/Slack/Notion/Postgres 등 이미 만들어진 MCP 서버를 무료로 흡수
- **스케치**:
  - `core/mcp_client.py` — stdio/HTTP MCP 프로토콜 클라이언트
  - `settings.yaml`에 `mcp.servers: [{name, command, args, env}]`
  - 부팅 시 각 서버에 연결 → tools/list 받아 ToolRegistry에 동적 등록
  - 도구 호출 시 MCP 서버에 위임
- **영향**: 새 모듈, `tools/tool_registry.py` 확장
- **공수**: 6~8h
- **의존**: MCP Python SDK (`pip install mcp`)

### #4 ✅ Plan → Execute → Reflect 메타 에이전트
- **카테고리**: 에이전트 협업
- **동기**: 큰 작업("내 소개 사이트 만들어줘")이 한 ReAct 루프로 해결 안됨
- **스케치**:
  - 새 에이전트 `planner` — 작업을 단계 리스트로 분해
  - 각 단계를 `delegate` 도구로 적합한 에이전트에 위임
  - 새 에이전트 `reviewer` — 결과 검토 후 보완 지시
  - `raphael plan "task"` 명령 — 자동 분해/실행/검토 한 번에
- **영향**: `agents/planner_agent.py` `agents/reviewer_agent.py`, `core/orchestrator.py`
- **공수**: 4~6h
- **의존**: `delegate` 도구 (이미 있음)

---

## 🟡 사용성

### #5 ✅ CLI 인라인 슬래시 명령
- **동기**: 대화 도중 모드 전환에 chat 종료 → 재실행 → 옵션 부여 단계 필요
- **스케치**:
  - chat 루프에서 입력이 `/`로 시작하면 명령 파싱:
    - `/agent X` → 에이전트 전환
    - `/model X` → 모델 전환
    - `/skill X` → 스킬 적용
    - `/save` → 현재 세션 export
    - `/clear` → 대화 초기화
    - `/help` → 명령 목록
- **영향**: `interfaces/cli.py:chat`
- **공수**: 1~2h

### #6 ✅ 웹 UI 세션 사이드바
- **동기**: 과거 대화로 클릭 한번에 전환 불가
- **스케치**:
  - `gr.Column(scale=1)` 좌측에 세션 목록 (Listbox)
  - 클릭 → 해당 세션 conversation 로드 → chatbot 갱신
  - "새 대화" 버튼
  - 자동 새로고침
- **영향**: `interfaces/web_ui.py`
- **공수**: 2~3h

### #7 ✅ 음성 입출력
- **동기**: 손 떼고 사용 가능 (운전 중, 요리 중)
- **스케치**:
  - STT: Whisper.cpp (로컬), `tools/voice_in.py`
  - TTS: macOS `say`, Linux `espeak`, 또는 `pyttsx3`
  - `raphael voice` — 마이크 듣기 → STT → 에이전트 → TTS 응답
  - 핫키: AppleScript / xdotool로 시스템 단축키 등록
- **영향**: 새 모듈 `interfaces/voice.py`
- **공수**: 4~6h

### #8 ✅ 클립보드 / 스크린샷 도구
- **동기**: "방금 복사한 거 정리해줘" 즉시 컨텍스트
- **스케치**:
  - `<tool name="clipboard_read"/>` `<tool name="clipboard_write">...</tool>`
  - `<tool name="screenshot"/>` → 임시 PNG 저장 후 vision 모델로 분석
  - macOS: `pbcopy`/`pbpaste`/`screencapture`
  - Linux: `xclip`/`wl-copy`/`grim`
- **영향**: 새 `tools/clipboard_tool.py`, `tools/screenshot_tool.py`
- **공수**: 2~3h
- **의존**: #1 (vision)

### #9 ✅ 시스템 트레이 / 메뉴바 앱
- **동기**: 항상 켜져 있는 비서, 빠른 접근
- **스케치**:
  - macOS: `rumps` 라이브러리 (메뉴바)
  - Linux: `pystray` (시스템 트레이)
  - 클릭 → `tkinter`/`webview` 작은 채팅 팝업
  - 백그라운드에서 `raphael health` 자동 시작
- **영향**: 새 `interfaces/tray_app.py`
- **공수**: 6~8h
- **의존**: rumps/pystray 의존성

---

## 🟢 외부 통합

### #10 ✅ 알림 / 리마인더
- **동기**: task agent가 일정 잡아도 그 시간에 알림 못 보냄
- **스케치**:
  - `task_agent`에 `due_at` 타임스탬프 필드 강화
  - 백그라운드 데몬 `raphael remind` — 1분 주기 체크
  - 알림 발송: macOS `osascript -e 'display notification'`, Linux `notify-send`
  - 텔레그램/디스코드로도 푸시 옵션
- **영향**: `agents/task_agent.py`, 새 `interfaces/reminder_daemon.py`
- **공수**: 3~4h

### #11 ✅ 캘린더 통합
- **동기**: "다음주 화요일 3시 미팅 잡아줘" 자연어 일정 관리
- **스케치**:
  - macOS: AppleScript로 캘린더 앱 조작
  - 크로스플랫폼: ICS 파일 R/W (`icalendar` 라이브러리)
  - Google Calendar: OAuth 후 API
  - 도구: `calendar_create`, `calendar_list`, `calendar_delete`
- **영향**: 새 `tools/calendar_tool.py`
- **공수**: 4~8h (구현 깊이에 따라)

### #12 ✅ 이메일 도구
- **동기**: "오늘 메일 중요한 것만 요약해줘"
- **스케치**:
  - IMAP 읽기 (`imaplib`), SMTP 보내기 (`smtplib`)
  - 도구: `email_inbox`, `email_send`, `email_search`
  - settings에 메일 계정 설정 (앱 비밀번호 권장)
- **영향**: 새 `tools/email_tool.py`
- **공수**: 4~5h
- **주의**: 비밀번호는 #19 (Keychain)와 함께 권장

### #13 ✅ Slack 봇 인터페이스
- **동기**: Telegram/Discord 외 회사용 채널
- **스케치**:
  - Slack Bolt SDK
  - `interfaces/slack_bot.py` — telegram_bot 패턴 그대로
  - allowed_users → Slack user_id
- **영향**: 새 모듈
- **공수**: 3~4h

### #14 ✅ 파일 변환 도구
- **동기**: 마크다운 → PDF, CSV → 차트, 이미지 변환
- **스케치**:
  - 마크다운→PDF: `weasyprint` 또는 `pandoc` 호출
  - CSV→차트: `pandas` + `matplotlib`
  - 이미지: `Pillow` (리사이즈/포맷)
  - 도구: `convert_md_to_pdf`, `csv_to_chart`, `image_resize`
- **영향**: 새 `tools/converters.py`
- **공수**: 3~4h

---

## 🔵 메모리 / 지능

### #15 ✅ 대화 검색
- **동기**: "지난주에 얘기한 그 함수 뭐였지?" 검색 불가
- **스케치**:
  - 별도 ChromaDB 컬렉션 `conversations`
  - 세션 종료 시 자동 인덱싱 (또는 백그라운드 데몬)
  - 도구: `<tool name="search_conversations"><arg name="query">...</arg></tool>`
  - `raphael cli session search "키워드"`
- **영향**: 새 `memory/conversation_index.py`, `tools/`
- **공수**: 3~4h

### #16 ✅ 자동 토픽 태깅
- **동기**: 세션 목록에서 주제 한눈에 파악
- **스케치**:
  - 세션 종료 시 LLM에 "이 대화의 핵심 태그 3개" 요청
  - `Session` 메타에 `tags: list[str]` 추가
  - `raphael cli session list --tag python`
- **영향**: `core/session_store.py`, `interfaces/cli.py`
- **공수**: 1~2h

### #17 ✅ 사용자 피드백 학습
- **동기**: 좋은/나쁜 응답 추적 → 향후 응답 품질 개선
- **스케치**:
  - 응답 후 `/feedback +1` `/feedback -1` 명령
  - `~/.raphael/feedback.jsonl`에 기록 (질문/응답/평가)
  - +1 응답을 RAG로 인덱싱 → 유사 질문 시 few-shot 예시로 주입
- **영향**: `interfaces/cli.py`, 새 `core/feedback.py`
- **공수**: 2~3h

---

## ⚙️ 운영 / 배포

### #18 ✅ Docker 컨테이너
- **동기**: `docker compose up`으로 한 번에 배포
- **스케치**:
  - `Dockerfile` (python:3.11-slim 베이스)
  - `docker-compose.yml`: Raphael + Ollama (volume) + Chroma (volume)
  - `.dockerignore`
- **영향**: 새 파일들
- **공수**: 2~3h

### #19 ✅ macOS Keychain / Linux Secret Service
- **동기**: `.env` 평문 토큰 → OS 키체인으로 안전 보관
- **스케치**:
  - `keyring` 라이브러리 (cross-platform)
  - `save_env`/`load_env`가 keyring을 우선 시도, fallback `.env`
  - `raphael secret set/get/delete`
- **영향**: `config/settings.py`
- **공수**: 2h

### #20 ✅ 체크포인트 / 롤백
- **동기**: 파일 도구가 잘못 작성한 경우 되돌리기
- **스케치**:
  - `write_file`/`delete_file` 호출 전 자동으로 `.raphael-backups/<timestamp>/`에 원본 복사
  - `raphael rollback list / restore <timestamp>`
  - 7일 자동 정리
- **영향**: `tools/file_writer.py`, 새 `core/checkpoint.py`
- **공수**: 3~4h

### #21 ✅ 플러그인 시스템
- **동기**: 외부 패키지로 기능 확장
- **스케치**:
  - `pyproject.toml` entry points: `raphael.tools`, `raphael.agents`
  - 부팅 시 `importlib.metadata.entry_points()` 스캔 → 자동 등록
  - 예: `pip install raphael-plugin-jira`
- **영향**: `tools/tool_registry.py`, `main.py`
- **공수**: 3~4h

### #22 ✅ 다중 Ollama 서버 라우팅 + 모델 자동 선택
- **동기**: 여러 머신/모델 활용, 부하 분산, 자동 fallback
- **스케치**: (별도 섹션 — 너무 큼)
  - `core/ollama_pool.py` — 서버 풀 + 헬스체크 + 활성 카운터
  - `core/router_strategy.py` — 작업 분류 + 모델/서버 선택
  - `ModelRouter` 풀 기반 리팩토링
  - settings:
    ```yaml
    models:
      routing:
        strategy: auto
        rules:
          - match: { agent: coding, min_messages: 5 }
            prefer: gemma4-26b
      ollama_pool:
        - name: local
          host: localhost
          models: [gemma4:e4b]
        - name: server
          host: 100.64.0.10
          weight: 3
          models: [gemma4:26b, gemma4:31b]
    ```
- **영향**: `core/model_router.py` 대형 리팩토링, 신규 2개 모듈
- **공수**: 4~6h

### #23 ✅ 자동 업데이트
- **동기**: `git pull && pip install -e .` 매번 수동
- **스케치**:
  - `raphael update` — 백그라운드에서 GitHub release 체크
  - 사용 가능 시 자동 또는 사용자 확인 후 업데이트
- **영향**: 새 `interfaces/updater.py`
- **공수**: 2h

### #24 ✅ Audit Log + 변조 방지
- **동기**: 모든 도구 실행 추적, 사후 감사 가능
- **스케치**:
  - `~/.raphael/audit.log` — append-only
  - 각 엔트리에 이전 엔트리 hash 포함 (Merkle chain)
  - `raphael audit verify` — chain 무결성 검증
  - `raphael audit show --since 1d`
- **영향**: 새 `core/audit.py`, `core/tool_runner.py` 후크
- **공수**: 2~3h

---

## 의존성 그래프

```
#1 (멀티모달) ──┬──► #8 (스크린샷)
                └──► (vision 모델 prerequisite)

#2 (Profile) ───► (모든 에이전트 응답 품질 향상)

#22 (멀티 Ollama) ──► (#1, #15, embedding 워크로드 분리에 유리)

#19 (Keychain) ──► #12 (이메일 비밀번호 보호)

#3 (MCP) ───► (외부 도구 무한 확장)

#4 (Plan-Execute) ──► (#10 캘린더, #12 이메일 자동 처리에 활용)

#20 (체크포인트) ──► #16 (피드백)

#21 (플러그인) ──► (외부 기여 가능)
```

## 추정 총 공수

| 카테고리 | 항목 수 | 합계 |
|---|---|---|
| TOP 4 (#1~#4) | 4 | 16~23h |
| 사용성 (#5~#9) | 5 | 15~22h |
| 외부 통합 (#10~#14) | 5 | 17~25h |
| 메모리/지능 (#15~#17) | 3 | 6~9h |
| 운영/배포 (#18~#24) | 7 | 18~25h |
| **합계** | **24** | **72~104h** |

## 참고 — 미진행해도 되는 이유

이 모든 게 **반드시 필요한 것은 아닙니다**. AI 에이전트는 **실제 사용 → 마찰점 발견 → 그 부분만 보강**의 사이클이 가장 효율적입니다.

지금 Raphael은 이미 다음을 갖춘 production-ready 수준입니다:
- 4 인터페이스 (CLI/Web/Telegram/Discord)
- 12 도구 (파일/실행/Git/웹검색/브라우저/delegate)
- 5 에이전트 (coding/research/note/task)
- 보안 격리 (인젝션 방어, path_guard, allowlist, 위험 도구 승인)
- 운영 (Health API, 메트릭, 활동 로그)
- 테스트 (29 unit + 20 E2E)

추가 항목은 **본인이 가장 필요한 것부터** 우선순위를 다시 매기는 게 좋습니다.

## 개선 항목 추가 시 워크플로우

1. 이 문서에 새 항목 추가 (위 형식 따라)
2. `docs/CHANGELOG.md`에 작업 계획 단계 추가
3. 구현 후 단위/E2E 테스트 작성
4. `HowToUse.md`/`docs/FEATURES.md` 업데이트
5. 이 ROADMAP에서 해당 항목 → "✅ 완료"로 표시 후 CHANGELOG로 이전
