# Raphael 사용 가이드

Gemma4 기반 개인용 AI 에이전트 프레임워크 — v0.13.

8개 인터페이스 (CLI/Web/Telegram/Discord/Slack/Voice/Tray/Health API), 6개 에이전트, 24개 도구, 다중 Ollama 라우팅, 보안/감사 일체형.

---

## 요구사항

- **OS**: macOS 또는 Linux
- **Python**: 3.11+
- **셸**: zsh, bash, fish
- **Ollama**: `gemma4:e4b` (필수), `nomic-embed-text` (RAG)

## 설치

```bash
bash install.sh        # OS 자동 감지 + venv + alias 등록
```

## 초기 설정

```bash
raphael onboard
```

Ollama IP/포트, 옵시디언 볼트, 봇 토큰, 파일 접근 허용 경로, 임베딩 모델 자동 설치까지.

---

## 명령어 전체 (23개)

| 명령 | 설명 |
|---|---|
| `raphael` | (인자 없으면) 대화 모드 진입 |
| `raphael status` | Ollama/모델/에이전트 상태 |
| `raphael onboard` | 초기 설정 마법사 |
| `raphael cli ...` | CLI 서브그룹 (chat/ask/model/session/skill/profile/memory) |
| `raphael web` | Gradio 웹 UI (포트 7860) |
| `raphael telegram` | 텔레그램 봇 |
| `raphael discord` | 디스코드 봇 |
| `raphael slack` | Slack 봇 (Socket Mode) |
| `raphael voice` | 음성 대화 (마이크 → STT → 에이전트 → TTS) |
| `raphael tray` | macOS 메뉴바 / Linux 시스템 트레이 |
| `raphael health` | 모니터링 API (`/health` `/metrics` `/tokens`) |
| `raphael log [-f]` | 활동 로그 (모든 인터페이스 통합) |
| `raphael watch` | 파일 시스템 훅 (settings.hooks.watches) |
| `raphael parallel "task" --agents A,B` | 다중 에이전트 동시 실행 |
| `raphael plan "task"` | planner 에이전트 자동 분해/위임 |
| `raphael review "ctx"` | reviewer 에이전트 비판적 검토 |
| `raphael commit [-m "msg"]` | 스테이지 변경 → AI 커밋 메시지 자동 생성 |
| `raphael secret set/get/delete <key>` | OS Keychain 시크릿 |
| `raphael rollback list/restore <id>` | 파일 작업 체크포인트 복원 |
| `raphael audit show/verify` | 변조 방지 감사 로그 |
| `raphael feedback` | 사용자 피드백 통계 |
| `raphael update` | 자체 git pull + pip install |
| `raphael mcp` | MCP 서버/도구 목록 |
| `raphael pool` | 다중 Ollama 서버 풀 상태 |

---

## CLI 대화 모드

```bash
raphael                                   # 즉시 대화 진입 (claude 스타일)
raphael cli chat                          # 새 세션
raphael cli chat --continue               # 가장 최근 세션 이어가기
raphael cli chat --resume <id>            # 특정 세션 복원
raphael cli chat --agent note             # 특정 에이전트
raphael cli chat -q                       # 실시간 진행 표시 끄기

raphael cli ask "질문"                    # 단발성
raphael cli ask "..." --json              # JSON 출력 (응답+토큰+시간)
raphael cli ask "..." --skill code-review # 스킬 적용
raphael cli ask "..." --image ~/x.png     # 이미지 첨부 (vision 모델 필요)
raphael cli ask "..." --continue          # 최근 세션 컨텍스트
```

### 인라인 슬래시 명령 (대화 중)

```
/agent <이름>     에이전트 전환
/model <키>       모델 전환
/skill <이름>     스킬 임시 적용
/save             현재 세션 저장
/clear            대화 초기화
/verbose on|off   실시간 진행 토글
/quit             종료
/help             도움말
```

---

## 진행 상황 실시간 보기

CLI/웹은 **기본 ON**, 봇은 옵트인:

```bash
# CLI — 기본 활성, 끄려면 -q
raphael cli ask "..." -v        # 명시적 ON
raphael cli ask "..." -q        # OFF

# 별도 터미널에서 모든 활동 추적
raphael log --follow             # tail -f 스타일
raphael log --tail 50            # 최근 50줄
raphael log --session tg:12345   # 특정 세션만

# 봇은 토글
# Telegram: /verbose on
# Discord:  /verbose on
```

활동 로그는 `~/.raphael/activity.jsonl` (JSON 라인). `🧠 thinking`, `⏳ elapsed`, `🔧 tool_call`, `✓ result`, `⚡ done` 이벤트 포함.

---

## 웹 UI

```bash
raphael web   # http://localhost:7860
```

탭 구성:
- **세션** — 저장된 모든 세션 목록 + 클릭으로 내용 보기
- **채팅** — 모델/에이전트 드롭다운 + 실시간 도구 실행 + 응답 스트리밍 + 내보내기 + 토큰 통계
- **설정** — Ollama IP/볼트/토큰/허용 경로 (네이티브 폴더 선택 다이얼로그)

대화는 브라우저 localStorage(`gr.BrowserState`)에 자동 저장.

---

## 봇 (Telegram / Discord / Slack)

### 사용자 등록 필수

`settings.local.yaml` 또는 `settings.yaml`:
```yaml
interfaces:
  telegram:
    allowed_users: [123456789]
  discord:
    allowed_users: [987654321098765432]
  slack:
    bot_token: "${SLACK_BOT_TOKEN}"
    app_token: "${SLACK_APP_TOKEN}"
    allowed_users: ["U12345"]
```

### 공통 명령어

```
/start /status /model list/use/status /agent /reset
/verbose on|off|status      # 진행 표시 토글
```

세션은 chat_id/channel별로 격리. 긴 응답은 자동 분할.

---

## 에이전트 (6개)

| 에이전트 | 역할 | 주요 도구 |
|---|---|---|
| `coding` (기본) | 코드/파일/실행/Git/브라우저/위임 | executor, file_*, git_*, browser, screenshot, clipboard, voice 등 16개 |
| `research` | RAG + 웹 검색 | file_reader, web_search |
| `note` | 옵시디언 노트 | file_reader, file_writer |
| `task` | 할일/일정 | (없음) |
| **planner** | 큰 작업 자동 분해 + delegate | delegate |
| **reviewer** | 산출물 비판적 검토 | file_reader, delegate |

### 자동 기능
- ReAct 루프 (최대 6회) — 도구 호출 자동 반복
- 대화 압축 (30턴 초과 시 LLM 요약, 최근 10턴 유지)
- 빈 응답/짧은 content 자동 경고 → 재시도 유도
- 위험 도구 (`execute`, `python`, `delete_file`) — `approval_callback` 설정 시 사용자 확인

---

## 도구 (24종)

### 파일/실행 (7)
`read_file` `write_file` `append_file` `delete_file` `mkdir` `execute` `python`
- 모두 `path_guard` 통과 필수 (`allowed_paths` 외부 거부)
- write/delete는 자동 체크포인트 → `raphael rollback`

### Git (4)
`git_status` `git_diff` `git_log` `git_commit`

### 웹/외부 (3)
`web_search` (DuckDuckGo + ddgs fallback) · `open_in_browser` · `mcp_call`

### 시스템 (5)
`screenshot` `clipboard_read` `clipboard_write` · `notify` · `speak` (TTS)

### 통신/캘린더/변환 (7)
`calendar_add` · `email_inbox` `email_send` · `convert_md_to_html` `convert_md_to_pdf` `convert_csv_to_chart` `image_resize`

### 메모리 (3)
`remember` `forget` (사용자 프로필) · `delegate` (서브에이전트 위임)

---

## 사용자 프로필 (장기 기억)

```bash
raphael cli profile show
raphael cli profile add "사용자는 Python 백엔드 개발자, 옵시디언 사용"
raphael cli profile forget "옵시디언"
raphael cli profile clear
```

또는 대화 중 LLM이 직접 `<tool name="remember">` 호출. 모든 에이전트 응답에 자동 주입.

저장: `~/.raphael/facts.json`

---

## 스킬 (사용자 정의 프롬프트 모드)

```bash
raphael cli skill create code-review -d "코드 리뷰 전문가 모드"
# (입력 모드에서 본문 작성, 빈 줄 두 번이면 종료)

raphael cli skill list
raphael cli ask "이 코드 리뷰해줘" --skill code-review
```

저장: `~/.raphael/skills/<name>.md`

---

## 세션 관리

```bash
raphael cli session list                     # 전체 목록 (자동 태그 포함)
raphael cli session show <id>
raphael cli session export <id> --format markdown
raphael cli session delete <id>
raphael cli session search "파이썬 데코레이터"  # 의미 검색 (RAG)
raphael cli session reindex                   # 검색 인덱스 재생성
```

세션은 `~/.raphael/sessions/<id>.json`에 자동 저장. 종료 시 LLM이 토픽 태그 자동 추출.

---

## RAG (옵시디언 볼트)

```python
from memory.rag import RAGManager
rag = RAGManager(router)
await rag.sync_vault()    # 증분 동기화 (mtime 기반 추가/수정/삭제)
hits = await rag.search("질문")
```

또는 research 에이전트가 자동 활용.

---

## 멀티모달 (이미지/스크린샷)

```bash
# 이미지 첨부
raphael cli ask "이 화면 분석해줘" --image ~/screen.png

# 에이전트가 직접 스크린샷 (vision 모델 필요)
# LLM이 <tool name="screenshot"/> 호출
```

vision 모델: `ollama pull gemma3:vision` 또는 `llava` 등.

---

## 다중 Ollama 풀 + Auto-routing

`config/settings.local.yaml`:

```yaml
models:
  routing:
    strategy: auto
    rules:
      - match: { token_estimate_lt: 80 }
        prefer_model: gemma4-e2b
      - match: { agent: coding, min_messages: 8 }
        prefer_model: gemma4-26b
      - match:
          contains_any: ["여러", "전체", "사이트", "프로젝트"]
          token_estimate_gt: 200
        prefer_model: gemma4-26b
        prefer_agent: planner
      - match: { default: true }
        prefer_model: gemma4-e4b

  ollama_pool:
    - name: local
      host: localhost
      models: ["gemma4:e4b"]
    - name: server
      host: 100.64.0.10
      weight: 3
      models: ["gemma4:26b", "gemma4:31b", "nomic-embed-text"]
```

```bash
raphael pool   # 서버별 헬스/활성 요청/모델 표시
```

규칙은 위에서 아래로 평가, 첫 매칭 적용. `default: true`로 fallback.

---

## Plan-Execute-Reflect

큰 작업은 planner가 자동으로 단계 분해 + 적합한 에이전트에 위임:

```bash
raphael plan "내 소개 사이트 만들어 ~/site에. HTML+CSS, 만든 후 브라우저 열기"
raphael review "방금 만든 사이트 구조 점검해줘"
```

내부적으로 `delegate` 도구로 coding/research 에이전트에 위임.

---

## Git 통합

```bash
git add -p
raphael commit              # AI가 staged diff 분석 후 커밋 메시지 제안
raphael commit -m "fix bug" # 수동 메시지
```

또는 LLM 도구로: `git_status`, `git_diff`, `git_log`, `git_commit`.

---

## 알림 / 캘린더 / 이메일

도구 형식으로 LLM이 사용:
```
"오늘 5시 회의 캘린더에 추가해줘"
→ <tool name="calendar_add"><arg name="title">...</arg><arg name="start">2026-04-15T17:00</arg></tool>

"이메일 받은편지함 5개 요약해줘"
→ <tool name="email_inbox"><arg name="n">5</arg></tool>

"작업 끝나면 알림 띄워줘"
→ <tool name="notify"><arg name="title">완료</arg><arg name="message">...</arg></tool>
```

이메일 비밀번호는 keychain에:
```bash
raphael secret set EMAIL_PASSWORD
```

---

## 보안

### 입력 인젝션 방어
- 신뢰 소스: CLI / WEB_UI / TELEGRAM / DISCORD
- 비신뢰 소스: WEB_SEARCH / RAG_CONTEXT / FILE_CONTENT — 명령어 무력화 + 경고 배너

### 파일 경로 샌드박스
- `tools.file.allowed_paths` 외부 거부
- 빈 값이면 홈 + /tmp + cwd 자동 허용

### 위험 도구 승인
`execute`, `python`, `delete_file`은 `approval_callback`으로 사용자 확인 가능.

### 시크릿 (Keychain)
```bash
raphael secret set GH_TOKEN
raphael secret get GH_TOKEN
raphael secret delete GH_TOKEN
```
keyring 가능하면 OS Keychain, 아니면 `.env` fallback.

### Audit log
모든 도구 실행은 `~/.raphael/audit.log`에 SHA256 hash chain으로 기록.
```bash
raphael audit show         # 최근 50건
raphael audit verify       # 체인 무결성 검증 (변조 감지)
```

### 체크포인트
파일 write/delete 전 자동 백업. 7일 보관.
```bash
raphael rollback list
raphael rollback restore <id>
raphael rollback cleanup [days]
```

---

## MCP (외부 도구 무한 확장)

`settings.local.yaml`:
```yaml
mcp:
  servers:
    - name: filesystem
      command: npx
      args: ["-y", "@modelcontextprotocol/server-filesystem", "~/Documents"]
    - name: github
      command: npx
      args: ["-y", "@modelcontextprotocol/server-github"]
      env:
        GITHUB_PERSONAL_ACCESS_TOKEN: "${GH_TOKEN}"
```

```bash
raphael mcp   # 서버/도구 목록
```

LLM이 `<tool name="mcp_call"><arg name="server">github</arg><arg name="tool">...</arg></tool>`로 호출.

---

## 플러그인 시스템

외부 패키지로 도구/에이전트 추가:

```toml
# raphael-plugin-jira/pyproject.toml
[project.entry-points."raphael.tools"]
jira_tool = "raphael_jira:JiraTool"
```

```bash
pip install raphael-plugin-jira
# 다음 raphael 실행 시 자동 등록됨
```

---

## 음성 대화

```bash
raphael voice
```

마이크로 말 → Whisper STT → 에이전트 → 응답을 `say`/`espeak`로 발화.

의존: `sox` (녹음), `openai-whisper` (STT), 시스템 TTS.

---

## 시스템 트레이 / 메뉴바

```bash
raphael tray
```

- macOS: `rumps` (메뉴바 R 아이콘) — "빠른 질문" 팝업
- Linux: `pystray` (시스템 트레이)

설치: `pip install rumps`(macOS) 또는 `pip install pystray Pillow`(Linux).

---

## Health API

```bash
raphael health [--port 7861]
```

| 엔드포인트 | 응답 |
|---|---|
| `GET /health` | Ollama 상태, 활성 세션 수 |
| `GET /agents` | 에이전트 목록 |
| `GET /tokens` | 누적 토큰 (모델별) |
| `GET /metrics` | Prometheus text |

---

## Docker 배포

```bash
docker compose up -d
```

`docker-compose.yml`이 Raphael + Ollama 한 묶음으로 띄움.

---

## 자동 업데이트 / 피드백

```bash
raphael update             # git pull + pip install -e .
raphael feedback           # 누적 👍/👎 통계
```

피드백은 향후 RAG few-shot 예시로 활용 (선택적).

---

## 설정 파일

```
config/settings.yaml         # 기본 (git 추적)
config/settings.local.yaml   # 로컬 오버라이드
.env                         # 시크릿 (keychain 우선)
```

테스트 샌드박스:
```bash
export RAPHAEL_CONFIG_DIR=/tmp/sb
export RAPHAEL_PROJECT_ROOT=/tmp/sb
```

---

## 모델 목록

### 로컬 (Ollama)
| 키 | Ollama | VRAM |
|---|---|---|
| `gemma4-e2b` | gemma4:e2b | ~3GB |
| `gemma4-e4b` ★기본 | gemma4:e4b | ~5GB |
| `gemma4-26b` | gemma4:26b | ~16GB |
| `gemma4-31b` | gemma4:31b | ~18GB |

```bash
ollama pull gemma4:e4b
ollama pull nomic-embed-text
```

### Claude 구독 (CLI 백엔드)

API 키 없이 본인 Claude Pro/Max 구독을 그대로 활용. `claude` CLI가 설치되고 로그인되어 있어야 함.

| 키 | 모델 | 용도 |
|---|---|---|
| `claude-haiku` | Haiku | 빠른 응답 |
| `claude-sonnet` | Sonnet | 복잡한 추론, 코드 리뷰 |
| `claude-opus` | Opus | 최고 품질 분석 |

```bash
# claude CLI 설치/로그인 후
which claude && claude --version

raphael cli model use claude-sonnet
raphael cli ask "복잡한 알고리즘 짜줘"

# Auto-routing과 결합:
# settings.local.yaml에 규칙 추가
# match: { contains_any: ["복잡", "어려운", "최적화"] }
# prefer_model: claude-sonnet
```

각 모델 호출 시 본인 Claude 구독 토큰이 소모됩니다. `usage` 정보는 `raphael cli ask --json`으로 확인.

---

## 테스트

```bash
python tests/test_unit.py             # 38개 단위 테스트
python tests/test_e2e.py [--fast|--slow]
```

---

## 트러블슈팅

| 증상 | 해결 |
|---|---|
| 봇이 응답 안 함 | `allowed_users`에 user_id 등록 |
| "경로 허용 범위 밖" | `allowed_paths`에 추가 또는 onboard 재실행 |
| 모델 404 | `ollama pull <name>` |
| RAG 빈 결과 | `ollama pull nomic-embed-text` |
| 토큰 빠뜨림(빈 응답) | 자동 재시도 / 큰 모델 전환 |
| 도구 태그 응답 본문에 노출 | 자동 필터링됨 — 발생 시 이슈로 보고 |

---

## 더 자세한 문서

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — 시스템 구조
- [docs/FEATURES.md](docs/FEATURES.md) — 모든 기능 카테고리
- [docs/API_REFERENCE.md](docs/API_REFERENCE.md) — 내부 API
- [docs/SECURITY.md](docs/SECURITY.md) — 보안 모델
- [docs/TESTING.md](docs/TESTING.md) — 테스트 전략
- [docs/CHANGELOG.md](docs/CHANGELOG.md) — 버전별 변경 이력
- [docs/ROADMAP.md](docs/ROADMAP.md) — 24개 항목 모두 완료
