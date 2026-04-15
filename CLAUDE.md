# Raphael — 프로젝트 맥락 (Claude Code용)

## 프로젝트 목적
**제한된 로컬 하드웨어(MacBook Pro M5 16GB)에서 gemma4가 어디까지 가능한지 탐구**.
claude API/구독은 fallback으로만 존재하며, 기본값에서 자동 사용하지 않음.
잘 되는 claude로 도망치는 것은 프로젝트 의미 무효화.

## 아키텍처 핵심 결정

### 에이전트 = 페르소나, 도구 = 공용 인프라
- `AgentDefinition.tools=[]` → 모든 도구 자동 허용 (페르소나 모드)
- 기본 5개: `main`, `coder`, `researcher`, `writer`, `planner`/`reviewer`(opt-in)
- 사용자는 `~/.raphael/agents/<name>.md` 에 system_prompt만 정의하면 페르소나 추가
- main은 직접 도구 호출 우선, 위임은 역할 전문성이 진짜 필요할 때만

### 모델 전략
- 기본: `gemma4-e4b` (5GB, 균형)
- 에스컬레이션 사다리 `settings.yaml:models.escalation_ladder`: `gemma4-e2b → e4b → 26b`
- 26B는 원격 Ollama 서버(다른 PC)에서 실행
- 31B는 현실적 하드웨어 범위 밖 — 지원 제거됨
- claude 추가는 사용자가 명시적으로 설정에 추가해야 작동
- auto-route 휴리스틱: 짧은 질문(<30자) → e2b, 코딩/파일 키워드 or 80자+ → e4b

### 실패 케이스 수집
- `MAX_TOOL_ITERATIONS` 도달 시 `~/.raphael/failures/<ts>_<agent>_<reason>.json` 자동 저장
- `raphael failures` 로 조회, `raphael failures --clear`
- A/B 러너: `raphael ab-test <scenario> --models gemma4-e2b,gemma4-e4b`

### 세션 영속화
- CLI: `~/.raphael/sessions/<id>.json` (매 턴 저장)
- Orchestrator 레벨(web/testbench): `~/.raphael/sessions/<sid>__<agent>.json`
- `raphael` 무인자 실행 시 마지막 세션 자동 이어가기

## 자주 발생한 문제 + 해결

| 증상 | 원인 | 해결 |
|---|---|---|
| `write_file` content 빈 채로 저장 | gemma4가 tool 본문 누락 | 빈 content면 파일 쓰지 않고 `ESCALATE_EMPTY_CONTENT` 반환, 같은 응답 재시도 지시 주입 |
| HTML이 `&lt;` 엔티티로 저장됨 | LLM이 content를 HTML 이스케이프 | `parse_tool_calls`에서 `html.unescape()` 자동 적용 |
| 유튜브에서 푸터만 추출 | JS 렌더링 기반 | `fetch_tool`에 유튜브 전용 파서 (og:meta + `ytInitialData`) |
| main이 URL도 web-researcher에 위임 | 위임 루프 낭비 | main 프롬프트 "URL 있으면 fetch_url 직접 호출" 명시 |
| 동일 tool 블록 중복 실행 | LLM 반복 출력 | `parse_tool_calls`에서 `(name, args)` 중복 제거 |
| `open_in_browser(url=...)` 실패 | 도구는 `target=` 기대 | `url`/`path`/`file` alias 자동 매핑 |
| `python` 명령 없음 | macOS는 `python3` | 프롬프트에 명시 + venv 가이드 |
| gemma4-e2b 도구 형식 실패 | 훈련 부족 | testbench 권장 모델, main 프롬프트 경고, 휴리스틱 자동 e4b |

## 안티패턴 (피할 것)
- ❌ gemma 실패 시 claude로 자동 폴백 (기본값에서)
- ❌ 에이전트마다 도구 제한 부여 (페르소나 모델 채택)
- ❌ 사용자 메시지의 경로/URL을 각색해서 delegate task에 넣기
- ❌ 브라우저/파일 도구를 "불가능"이라 답하기 (전부 구현되어 있음)

## 자주 쓰는 커맨드
```bash
raphael                              # 자동 세션 이어가기
raphael testbench <id>               # L1~L4 시나리오 실행
raphael ab-test <id> --models ...    # 모델 비교
raphael failures --n 10              # 실패 케이스
raphael agent list                   # 등록된 페르소나
raphael web                          # Gradio UI
```

## 테스트
`python tests/test_unit.py` — 46개 유닛 테스트 (수정 전후 통과 필수).

## 데스크톱 앱 (Tauri + React) 진행 상태

### 현재 버전: v0.1.10 (Tauri)

### 인프라 완료
- `interfaces/daemon.py` — FastAPI 데몬 (lifespan handler), SSE 메시지, 구버전 list형 세션 파일 skip
- `desktop/build_sidecar.sh` — PyInstaller 단일 바이너리 (macOS 74MB / Windows 68MB)
- `desktop/src-tauri/` — Tauri 셸, sidecar spawn/kill, tray, 플랫폼별 단축키, updater (자동 업데이트 프롬프트 배선 완료), **panic hook → crash.log**, 비밀번호 없는 서명 키페어
- `.github/workflows/release.yml` — macOS arm64 + Windows x64 빌드 매트릭스 + latest.json (서명 + Windows 아티팩트 포함)
- GitHub repo `TechD-Studio/Raphael` (private), DMG/EXE/MSI 배포

### 기능 완료 (UI)
- **채팅**: 사이드바 세션, 모델 셀렉터, SSE 스트리밍, markdown + highlight.js, 클립보드 붙여넣기, 멀티모달 이미지 첨부 + 스크린샷 캡처, 에이전트 타겟 셀렉터
- **스킬/에이전트**: 스킬 CRUD, 스킬 셀렉터, 프로파일, 풀, 훅, slot 기반 라우팅 에디터, 봇 매니저
- **보안**: 허용 경로 + Keychain 비밀, 위험 도구 인터랙티브 승인 다이얼로그
- **관찰성**: 활동 로그, 감사 로그 + 체인 검증, 체크포인트 뷰어/복원, 세션 시맨틱 검색 + 태그
- **시스템 패널**: health, feedback, MCP 호출 UI, plugins, update, /metrics, 모델 pull
- **RAG**: Obsidian 관리
- **기타**: 파일 변환, 레이아웃 스크롤 격리

### 글로벌 단축키
- macOS: `Cmd+Shift+R` 창 토글
- Windows/Linux: `Ctrl+Alt+R` 창 토글 (Win+Shift+R는 OS 예약어로 회피)

### 남은 작업
- A/B 대시보드 (`raphael ab-test` 결과 시각화)
- 아이콘 디자인 (현재 Tauri 기본 아이콘)
- 코드 서명 (Apple Developer $99/년 + Windows EV — 추후)

### 알려진 이슈
- `tauri.conf.json`의 pubkey 문자열이 Claude Code 컨텐츠 필터에 오탐. **직접 Read 금지**, JSON 유효성은 `python3 -c "import json; json.load(open(...))"` 또는 sed로만 수정.
- **Windows 배포**: 미서명이라 첫 실행 시 SmartScreen 경고. `Unblock-File` 또는 "추가 정보 → 실행" 필요.
- **macOS 배포**: Sequoia+는 미서명 앱에 "손상됨" 다이얼로그 (그래도 열기 버튼 없음). 우회: `sudo xattr -dr com.apple.quarantine /Applications/Raphael.app`.
- PyInstaller onefile sidecar는 Windows Defender가 드물게 오탐할 수 있음 (실측은 아직 없음).
- v0.1.0은 Windows에서 무음 크래시 (tray icon unwrap + reserved shortcut) — v0.1.1에서 방어 코드로 해결, v0.1.0은 삭제됨.

## 파일 구조 요점
- `core/agent_base.py` — ReAct 루프, 에스컬레이션, 실패 저장
- `core/agent_definitions.py` — 페르소나 md 로더, 기본 5개
- `core/orchestrator.py` — 라우팅, 세션 영속화
- `core/tool_runner.py` — XML 파싱, HTML unescape, 중복 제거
- `core/router_strategy.py` — 규칙 + 휴리스틱
- `core/prompts.py` — TOOL_USAGE_PROMPT (모든 에이전트 공용)
- `tools/fetch_tool.py` — WebFetch 구현 (유튜브 파서 포함)
- `tools/web_search.py` — Brave/Tavily/Serper/SearXNG/DDG 자동 폴백
