# Raphael 프로젝트 문서 (v0.13)

개인용 AI 에이전트 프레임워크 Raphael의 전체 기술 문서.

## 문서 목록

| 문서 | 용도 |
|---|---|
| [../HowToUse.md](../HowToUse.md) | 사용자 실전 가이드 (모든 명령/기능 한 번에) |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 시스템 구조, 모듈 트리, 데이터 흐름 6종 |
| [FEATURES.md](FEATURES.md) | 16개 카테고리별 모든 기능 |
| [API_REFERENCE.md](API_REFERENCE.md) | 내부 클래스/함수 시그니처 |
| [CHANGELOG.md](CHANGELOG.md) | Phase 1~5 + v0.2~v0.13 단계별 히스토리 |
| [SECURITY.md](SECURITY.md) | 위협 모델 + Keychain/Audit/Checkpoint |
| [TESTING.md](TESTING.md) | 38 unit + 20 E2E 테스트 가이드 |
| [ROADMAP.md](ROADMAP.md) | 24개 항목 모두 ✅ 완료 |

## 프로젝트 한눈에 보기 (v0.13)

| 항목 | 수치 |
|---|---|
| **언어** | Python 3.11+ |
| **모델** | Gemma 4 (Ollama, e2b/e4b/26b/31b) |
| **인터페이스** | 8종 (CLI · Web · Telegram · Discord · Slack · Voice · Tray · Health API) |
| **에이전트** | 6종 (coding · research · note · task · planner · reviewer) |
| **도구** | 24종 (파일 5 · 실행 2 · 웹 3 · Git 4 · 시스템 5 · 통신/일정 3 · 변환 4 · 메모리/위임 3) |
| **CLI 명령** | 23개 |
| **메모리** | ChromaDB (옵시디언 RAG + 대화 검색 + 사용자 프로필) |
| **다중 LLM** | OllamaPool + RouterStrategy (auto-routing) |
| **테스트** | 38 unit + 20 E2E |
| **보안** | 인젝션 방어 · path 샌드박스 · allowlist · Keychain · Checkpoint · Audit chain |
| **운영** | Health API · Prometheus · 활동 로그 · Docker · 자동 업데이트 · 플러그인 |

## 빠른 시작

```bash
bash install.sh              # 설치
raphael onboard              # 초기 설정
raphael                       # 바로 대화 모드 (claude 스타일)
```

자세한 사용법은 [HowToUse.md](../HowToUse.md) 참고.

## 주요 v0.13 추가

- **다중 Ollama 라우팅** (`OllamaPool`) + **Auto-routing** (`RouterStrategy`)
- **OS Keychain 시크릿** (`raphael secret`)
- **파일 체크포인트/롤백** (`raphael rollback`)
- **변조 방지 Audit log** (`raphael audit verify`)
- **사용자 피드백** (`raphael feedback`)
- **자동 업데이트** (`raphael update`)
- **Slack 봇 / 음성 / 메뉴바** (`raphael slack/voice/tray`)
- **알림/캘린더/이메일/변환 도구** + **플러그인 시스템**
- **대화 의미 검색** + **세션 자동 토픽 태깅**
- **CLI 인라인 슬래시 명령** + **Docker 컨테이너**
