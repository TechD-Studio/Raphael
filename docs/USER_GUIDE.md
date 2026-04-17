# Raphael 사용 가이드

---

## 1. 설치 및 시작

### 데스크톱 앱 (macOS/Windows)
1. [GitHub Releases](https://github.com/TechD-Studio/Raphael/releases)에서 최신 DMG/EXE 다운로드
2. 설치 후 실행
3. macOS 미서명 앱 경고 시: `sudo xattr -dr com.apple.quarantine /Applications/Raphael.app`

### CLI (개발자)
```bash
git clone https://github.com/TechD-Studio/Raphael.git
cd Raphael
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
raphael          # 대화 모드
raphael web      # 웹 UI
```

### 웹 원격 접속 (Tailscale 등)
```bash
raphael web --port 9000
# 브라우저: http://<tailscale-ip>:9000
```

---

## 2. 기본 사용

### 채팅
- 메시지 입력 후 **Enter** 전송 (Shift+Enter: 줄바꿈)
- **파일 첨부**: 채팅 영역에 드래그앤드롭 (이미지/텍스트/PDF)
- **Cmd+V**: 클립보드 이미지 붙여넣기
- **🎙 버튼**: 음성 입력 (녹음 → 전사)
- **🔊/🔇 버튼**: 응답 음성 읽기 ON/OFF
- **중지 버튼**: 스트리밍 중 응답 중단
- 스트리밍 중에도 다음 메시지 미리 입력 가능

### 메시지 기능
- **📋**: 응답 텍스트 복사
- **♻**: 마지막 응답 재생성
- **👍/👎**: 응답 품질 피드백
- **↗ 분기**: 해당 시점에서 새 세션으로 분기 (hover 시 표시)
- **Code 블록**: 우상단 "Copy" 버튼 (hover 시 표시)

### 세션 관리
- **＋ 버튼**: 새 세션
- **세션 클릭**: 이전 대화 불러오기
- **✕ 버튼**: 세션 삭제
- **☑ 버튼**: 선택 모드 → 다중 삭제 / 전체 삭제
- **태그 클릭**: 해당 태그로 세션 필터링
- **검색**: 시맨틱 기반 세션 검색

---

## 3. 이미지 생성

### 사용법
채팅에서 자연어로 요청:
```
고양이 그림 그려줘
우주를 여행하는 로봇 일러스트 만들어줘
```

### 설정 (설정 > 서버 > 이미지 생성)

#### 로컬 FLUX.1 (무료)
1. `pip install mflux`
2. [HuggingFace 토큰 생성](https://huggingface.co/settings/tokens) (Read 권한)
3. [FLUX.1-schnell 접근 승인](https://huggingface.co/black-forest-labs/FLUX.1-schnell)
4. 설정에서 HUGGINGFACE_TOKEN 입력
5. 터미널: `huggingface-cli login`
6. 첫 생성 시 ~4GB 모델 자동 다운로드

#### OpenAI DALL-E 3 (유료 ~$0.04/장)
1. [OpenAI API 키 생성](https://platform.openai.com/api-keys)
2. 설정에서 OPENAI_API_KEY 입력
3. 백엔드를 "OpenAI" 또는 "auto"로 설정

---

## 4. 모델 설정

### 모델 전환
- **사이드바 하단 드롭다운**: 즉시 전환
- **설정 > 모델**: 목록 + "사용" 버튼

### 사용 가능 모델
| 모델 | 종류 | 용도 |
|---|---|---|
| gemma4-e2b | 로컬 (5B) | 간단한 질문, 빠른 응답 |
| gemma4-e4b | 로컬 (9B) | 일반 대화, 코딩 (기본) |
| gemma4-26b | 원격 (26B) | 고난이도 작업 |
| claude-sonnet | 구독 (Claude) | 복잡한 추론, 코드 리뷰 |
| claude-opus | 구독 (Claude) | 최고 품질 |
| claude-haiku | 구독 (Claude) | 빠른 응답 |

### 에스컬레이션 사다리 (설정 > 모델)
gemma4가 빈 응답을 반환하면 자동으로 다음 모델로 전환:
```
gemma4-e2b → gemma4-e4b → gemma4-26b → claude-sonnet
```
- ▲▼로 순서 변경
- ON/OFF 토글로 활성화/비활성화
- Claude 추가 시 어려운 작업 자동 위임

### 상황별 모델 (라우팅)
auto 모드에서 입력 특성에 따라 모델 자동 선택:
- 짧은 입력 → 경량 모델
- 코딩 키워드 → 중간 모델
- 프로젝트 작업 → 대형 모델
- "추천 불러오기"로 기본 설정 적용

---

## 5. 에이전트 & 스킬

### 에이전트 (설정 > 에이전트)
| 에이전트 | 역할 |
|---|---|
| main | 모든 도구 사용 가능 (기본) |
| coder | 코드 작성/실행/디버깅 |
| researcher | 웹 검색 + RAG |
| writer | 글쓰기 |
| planner | 작업 분해 + 위임 |
| reviewer | 산출물 검토 |

- 채팅 툴바에서 에이전트 선택 가능
- "편집"으로 시스템 프롬프트 커스터마이징
- 새 에이전트 생성/삭제/활성화/비활성화

### 글로벌 커스텀 지시문 (설정 > 에이전트 탭 상단)
모든 에이전트에 공통 적용되는 규칙:
```
예시:
- 항상 한국어로 답하라
- 이미지 요청 시 generate_image를 반드시 호출하라
- 답변은 500자 이내로 간결하게
```

### 스킬 (설정 > 스킬)
재사용 가능한 프롬프트 템플릿. 채팅 시 스킬 셀렉터에서 선택하면 해당 프롬프트가 주입됨.

---

## 6. 서버 설정

### Ollama 서버 (설정 > 서버)
- 호스트/포트/타임아웃 설정
- 로컬: `localhost:11434`
- 원격: Tailscale IP (예: `100.72.161.37:11434`)

### 다중 서버 풀
여러 Ollama 서버를 등록해 모델별 라우팅. 설정 > 서버 > 풀 섹션.

### 보안
- **허용 경로**: 파일 도구가 접근 가능한 디렉토리 목록
- **Keychain 시크릿**: API 키를 OS Keychain에 안전 보관

---

## 7. RAG (옵시디언 연동)

### 설정 (설정 > RAG)
1. 볼트 경로 입력 (예: `/Users/dh/Documents/Obsidian Vault`)
2. "경로 저장" 클릭
3. "Sync (증분)" 또는 "전체 재인덱싱"
4. research 에이전트가 자동으로 참조

---

## 8. 파인튜닝

### 전제 조건
```bash
pip install mlx-lm           # 학습 엔진
# llama.cpp 빌드 (GGUF 변환용) — 선택
# ollama 실행 중 (모델 등록용)
```

### 사용법 (설정 > 모델 > 파인튜닝)
1. **데이터 변환**: 옵시디언 볼트 → Q&A 쌍 JSONL
2. **QLoRA 학습**: 베이스 모델 + 반복 횟수 설정 → 학습 시작
3. **모델 빌드**: 어댑터 → GGUF → Ollama 등록

### 참고
- gemma4-e2b (5B): M5 16GB에서 ~5분
- gemma4-e4b (9B): M5 16GB에서 ~50분 (빡빡)
- gemma4-26b: M4 32GB 필요

---

## 9. 텔레그램/디스코드 봇

### 시작
```bash
raphael telegram    # 텔레그램 봇
raphael discord     # 디스코드 봇
```

### 명령어
| 명령 | 설명 |
|---|---|
| `/start` | 상태 + 명령어 목록 |
| `/status` | 모델/서버 상태 |
| `/model list/use <key>` | 모델 전환 |
| `/agent` | 에이전트 목록 |
| `/reset` | 대화 초기화 |
| `/verbose on/off` | 도구 실행 과정 표시 |
| `/settings show` | 현재 설정 |
| `/settings model <key>` | 기본 모델 변경 |
| `/settings escalation on/off` | 에스컬레이션 토글 |
| `/settings server <host>` | 서버 변경 |

---

## 10. 대시보드

📊 버튼으로 접근:

| 탭 | 내용 |
|---|---|
| **실패 케이스** | MAX_ITERATIONS 도달 등 실패 기록 조회/삭제 |
| **체크포인트** | 파일 작업 백업 조회/복원/정리 |
| **로그** | Audit (해시 체인 검증) + 활동 로그 (이벤트별 필터) |
| **시스템** | Health, 피드백 통계, MCP 호출, 봇 관리, 플러그인 |

---

## 11. 다크 모드

macOS 시스템 설정에 자동 연동됩니다.
- 시스템 설정 > 모양새 > 다크/라이트 전환 시 즉시 반영
- 별도 토글 불필요

---

## 12. 단축키

### 데스크톱 앱
| 단축키 | 동작 |
|---|---|
| **Cmd+Shift+R** (macOS) | 창 토글 (보이기/숨기기) |
| **Ctrl+Alt+R** (Windows) | 창 토글 |
| **Enter** | 메시지 전송 |
| **Shift+Enter** | 줄바꿈 |
| **Cmd+V** | 이미지/텍스트 붙여넣기 |

---

## 13. CLI 명령어 요약

```bash
raphael                    # 대화 모드 (마지막 세션 이어가기)
raphael web [--port N]     # 웹 UI (원격 접속 가능)
raphael telegram           # 텔레그램 봇
raphael discord            # 디스코드 봇
raphael slack              # Slack 봇
raphael voice              # 음성 대화
raphael status             # 전체 상태
raphael agent list         # 에이전트 목록
raphael plan "작업"        # planner 자동 분해/실행
raphael review "컨텍스트"  # reviewer 검토
raphael commit             # AI 커밋 메시지 생성
raphael testbench <id>     # 통합 테스트
raphael ab-test <id>       # 모델 비교
raphael failures           # 실패 케이스 조회
raphael secret set/get     # Keychain 시크릿
raphael rollback list      # 체크포인트 관리
raphael audit verify       # Audit 체인 검증
raphael update             # 자체 업데이트
raphael onboard            # 초기 설정 마법사
```
