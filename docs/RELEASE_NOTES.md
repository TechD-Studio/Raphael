# Raphael v0.1.17+ 릴리스 노트

> 기준: v0.1.10 → 현재 (57 commits)

---

## 신규 기능

### 이미지 생성
- **로컬 FLUX.1** (무료): `mflux-generate` CLI 기반, Apple Silicon 네이티브
- **OpenAI DALL-E 3** (유료): API 키 기반, ~$0.04/장
- 설정 > 서버 > 이미지 생성에서 백엔드 선택 (auto/local/openai)
- HuggingFace/OpenAI 토큰 입력 + 저장 상태 확인 (마스킹 표시)
- 채팅에서 "그림 그려줘" → `generate_image` 도구 자동 호출
- 생성된 이미지 채팅 인라인 표시

### 파인튜닝 (QLoRA)
- 설정 > 모델 > 파인튜닝 — 3단계 위저드
  1. 옵시디언 볼트 → JSONL Q&A 쌍 변환
  2. mlx_lm QLoRA 학습 (gemma4-e2b/e4b)
  3. fuse → GGUF → Ollama 등록
- 의존성 상태 표시 (✓/✗ mlx_lm, llama.cpp, ollama)
- 등록된 파인튜닝 모델 관리 (삭제)

### 에스컬레이션 사다리 에디터
- 설정 > 모델에서 GUI로 에스컬레이션 순서 편집
- ▲▼ 순서 변경, + 추가, ✕ 제거
- ON/OFF 토글 (비활성화 시 현재 모델만 사용)
- Claude 모델에 "구독" 배지 표시

### 글로벌 커스텀 지시문
- 설정 > 에이전트 탭 상단
- 모든 에이전트에 "최우선 준수" 태그로 주입
- 사용자가 행동 규칙을 직접 정의 가능

### 검색 강화
- `web_search` 상위 2개 URL 본문 자동 수집 (`auto_fetch`)
- 검색 → fetch 체인 강제 프롬프트 (snippet 부족 시 반드시 본문 읽기)
- 쇼핑 질문에 `site:danawa.com` 힌트

### 스마트 에이전트
- `MAX_TOOL_ITERATIONS` 4→6
- 도구 실패 시 3단계 재시도 전략 프롬프트
- 최종 답변 전 자기 검증 (`_self_reflect`)
- 실패 패턴 학습 (`_load_failure_patterns`) — 같은 실수 반복 방지
- 복잡한 요청 → planner 자동 라우팅
- 코딩 후 reviewer 자동 검토

### 웹 원격 접속
- `raphael web` → React UI + API 동일 포트 서빙
- Tailscale IP로 외부 브라우저 접속 가능
- `http://<ip>:8765/app` (루트 `/` → `/app` 자동 리다이렉트)
- Gradio Web UI 제거 (React로 대체)

### 텔레그램/디스코드 `/settings` 명령
- `/settings show` — 현재 설정 표시
- `/settings model <key>` — 모델 변경
- `/settings escalation on|off` — 에스컬레이션 토글
- `/settings server <host>` — Ollama 서버 변경
- `/settings default_agent <name>` — 기본 에이전트 변경

### 음성 I/O
- 컴포저 🎙 마이크 버튼 → MediaRecorder → `/stt` (whisper) → 텍스트 입력
- 🔊/🔇 응답 음성 토글 (OS TTS)

---

## UI/UX 개선

### 채팅
- 사용자 메시지 우측 정렬 (인디고 말풍선)
- 📋 메시지 복사 버튼 + 코드 블록 hover Copy
- ♻ 마지막 응답 재생성 버튼
- ↗ 대화 분기 (특정 턴에서 새 세션)
- 👍/👎 피드백 버튼 + `/feedback` 기록
- 🔧 도구 행동 과정 접이식 패널 (실시간)
- 🔄 모델 변경 알림
- 📊 토큰 사용량 모달 차트 (막대그래프)
- 드래그앤드롭 파일 첨부 (이미지/텍스트/PDF)
- 스트리밍 중지 버튼 (빨간색 "중지")
- 스트리밍 중 타이핑 가능
- Planner 실행 시각화 (단계별 진행 상태)

### 사이드바
- 세션 태그 칩 + 클릭 필터링
- 호출수/토큰 실시간 카운터 (30초 폴링)
- ☑ 선택 모드 → 다중 삭제 / 전체 삭제
- 빈 세션 자동 정리 (daemon 시작 시)

### 다크 모드
- macOS 시스템 설정 자동 연동 (수동 토글 제거)
- CSS 변수 40개+ (라이트/다크)
- 사이드바도 라이트/다크 전환
- 모든 팝업/설정/대시보드 다크 대응

### 설정 탭 정리
- 10개 → 5개: 에이전트(+프로필) | 스킬 | 모델(+라우팅+에스컬레이션+파인튜닝) | 서버(+풀+보안+이미지생성) | RAG
- 버튼 스타일 전체 통일 (글로벌 룰)
- 라우팅 추천 불러오기 (동적 모델 감지)

### 대시보드 탭 정리
- 6개 → 4개: 실패 | 체크포인트 | 로그(Audit+활동 서브토글) | 시스템
- A/B 테스트 UI/API 제거, 훅/업데이트/도구 탭 제거

---

## 버그 수정

| 수정 | 원인 |
|---|---|
| Ollama 서버 설정 영속화 | PyInstaller 프로즌 모드에서 `_MEIPASS` 임시 폴더에 저장됨 → `~/.raphael/config` |
| window.confirm() 차단 | Tauri v2 WKWebView에서 조용히 false 반환 → `confirmDialog()` React 모달 |
| 세션 삭제 실패 | 파일명 `{sid}__agent.json` 형식 미지원 → glob 패턴 |
| 세션 목록 0개 | list형 세션 파일 미지원 → dict/list 모두 처리 |
| RAG/서버 탭 버튼 안 보임 | macOS WebKit 기본 color 투명 → `color: #1c1d20` 명시 |
| 이미지 스트리밍 미전달 | `chat_stream()`에 images 파라미터 누락 → 추가 |
| Claude 모델 미사용 | auto-routing이 매번 gemma4로 덮어씀 → provider 체크 후 스킵 |
| stale daemon 포트 점유 | 구버전 sidecar 잔존 → 앱 시작 시 `lsof + kill` 자동 |
| 에이전트 "가상 환경" 거짓 | 프롬프트 3중 강화 ("실제 컴퓨터에서 실행 중") |
| 이미지 생성 planner 라우팅 | 긴 프롬프트 복잡도 오감지 → 단순 작업 키워드 제외 |
