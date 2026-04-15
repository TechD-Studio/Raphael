# 라파엘 (Raphael) — AI 에이전트 프레임워크

## 프로젝트 개요

개인용 AI 에이전트 프레임워크. Gemma4를 주력 모델로 사용하며 옵시디언 노트를 장기 기억으로 활용한다. CLI, 웹 UI, 텔레그램, 디스코드 4가지 인터페이스를 통해 어디서든 에이전트에 접근 가능하다. 테스트 성격이 강하며 완성도가 높아지면 오픈소스 배포를 고려한다.

---

## 확정 스택

| 항목 | 선택 | 비고 |
|---|---|---|
| 언어 | Python 3.11+ | |
| 주력 모델 | Gemma 4 (다중 선택) | Ollama 서빙 |
| 보조 모델 | Claude Code (구독형) | NanoClaw 방식 시도, 안되면 드롭 |
| 벡터 DB | ChromaDB | RAG용 |
| 임베딩 | nomic-embed-text | Ollama로 처리 |
| 인터페이스 | CLI + Web UI + Telegram + Discord | Typer, Gradio, python-telegram-bot, discord.py |
| 네트워크 | 로컬 LAN / Tailscale | 동일 설정으로 처리 |

---

## 하드웨어 구성

```
[라파엘 실행 머신]              [Ollama 서버 머신]
  raphael/ 코드               Linux / Ryzen 7
  ChromaDB                   GTX 1070 8GB VRAM
  텔레그램/디스코드 봇           48GB RAM
        │                    (추후: 맥미니 or 맥스튜디오)
        └──── 로컬 LAN / Tailscale ────┘
```

---

## 지원 모델 목록

Ollama 기반. `settings.yaml`에서 관리하며 런타임에 전환 가능.

| 모델 키 | Ollama 이름 | VRAM | 용도 |
|---|---|---|---|
| `gemma4-e2b` | gemma4:e2b | ~3GB | 경량, 빠른 응답 |
| `gemma4-e4b` | gemma4:e4b | ~5GB | **기본값**, 균형 성능 |
| `gemma4-26b` | gemma4:26b | ~16GB | 고성능 |
| `gemma4-31b` | gemma4:31b | ~18GB | 최대 성능 (맥스튜디오 전용) |

---

## 폴더 구조

```
raphael/
├── core/
│   ├── model_router.py       # Ollama 연결, 모델 선택/전환 로직
│   ├── agent_base.py         # 에이전트 베이스 클래스
│   └── orchestrator.py       # 에이전트 조율, 태스크 분배
│
├── memory/
│   ├── rag.py                # ChromaDB RAG 검색/저장
│   ├── obsidian_loader.py    # 옵시디언 MD 파일 읽기 + 인덱싱
│   └── finetune/
│       ├── dataset_builder.py  # 옵시디언 → 학습 데이터셋 변환
│       └── lora_trainer.py     # LoRA 파인튜닝 파이프라인
│
├── tools/
│   ├── file_reader.py        # txt, md, pdf(pymupdf), csv, 코드 파일
│   ├── file_writer.py        # 파일 생성, 수정, 삭제
│   ├── executor.py           # 코드/스크립트 실행 (제한 없음, 로그 기록)
│   └── tool_registry.py      # 에이전트가 툴을 가져다 쓰는 레지스트리
│
├── agents/
│   ├── research_agent.py     # 웹 검색 + 문서 분석 + 요약
│   ├── coding_agent.py       # 코드 작성, 실행, 디버깅
│   ├── note_agent.py         # 옵시디언 노트 작성/정리/검색
│   └── task_agent.py         # 일정, 태스크, 할일 관리
│
├── interfaces/
│   ├── cli.py                # CLI 인터페이스 (Typer 기반)
│   ├── web_ui.py             # 웹 UI (Gradio 기반)
│   ├── telegram_bot.py       # 텔레그램 봇 인터페이스
│   └── discord_bot.py        # 디스코드 봇 인터페이스
│
├── config/
│   ├── settings.yaml         # 메인 설정 (아래 상세 참고)
│   └── settings.local.yaml   # 로컬 오버라이드 (.gitignore)
│
├── data/
│   └── chroma/               # ChromaDB 저장소
│
├── logs/                     # 실행 로그, executor 로그
├── .env                      # 토큰, 시크릿 (절대 커밋 금지)
├── requirements.txt
└── main.py
```

---

## 설정 파일 (`config/settings.yaml`)

```yaml
raphael:
  name: "Raphael"
  version: "0.1.0"

models:
  default: "gemma4-e4b-q4"

  ollama:
    host: "100.x.x.x"          # Tailscale IP 또는 로컬 192.168.x.x
    port: 11434
    timeout: 120

    available:
      gemma4-e2b-q4:
        name: "gemma4:e2b-q4_0"
        vram: "3.2GB"
        description: "경량, 빠른 응답"
        best_for: ["간단한 질문", "빠른 태스크"]

      gemma4-e4b-q4:
        name: "gemma4:e4b-q4_0"
        vram: "5GB"
        description: "균형잡힌 성능 (권장)"
        best_for: ["일반 대화", "코딩", "분석"]

      gemma4-e4b-sfp8:
        name: "gemma4:e4b-sfp8"
        vram: "7.5GB"
        description: "고품질 추론"
        best_for: ["복잡한 추론", "긴 문서 처리"]

      gemma4-26b-q4:
        name: "gemma4:26b-a4b-q4_0"
        vram: "15.6GB"
        description: "고성능 (맥스튜디오 권장)"
        best_for: ["고난이도 태스크"]

      gemma4-31b-q4:
        name: "gemma4:31b-q4_0"
        vram: "17.4GB"
        description: "최대 성능 (맥스튜디오 전용)"
        best_for: ["최고 품질 작업"]

  claude:
    enabled: false              # NanoClaw 방식 시도 후 결정
    mode: "subscription"

  auto_routing:
    enabled: false              # true면 태스크 복잡도별 자동 모델 선택

memory:
  obsidian_vault: "/path/to/vault"
  chroma_db_path: "./data/chroma"
  embedding_model: "nomic-embed-text"

tools:
  file:
    allowed_paths:
      - "~/workspace"
      - "/path/to/obsidian"
    max_file_size_mb: 50
    supported_formats: ["txt", "md", "pdf", "csv", "py", "js", "ts", "json", "yaml"]

  executor:
    sandbox: false              # 제한 없이 실행
    log_executions: true
    log_path: "./logs/exec.log"
    timeout_seconds: 60

interfaces:
  cli:
    enabled: true               # 터미널에서 직접 대화
    history_file: "./data/cli_history.json"

  web_ui:
    enabled: true
    host: "0.0.0.0"            # 로컬만 쓰려면 "127.0.0.1"
    port: 7860                  # Gradio 기본 포트
    share: false                # true면 Gradio 퍼블릭 링크 생성
    auth: false                 # true면 사용자명/비번 설정 가능

  telegram:
    enabled: true
    token: "${TELEGRAM_BOT_TOKEN}"

  discord:
    enabled: true
    token: "${DISCORD_BOT_TOKEN}"

logging:
  level: "INFO"
  file: "./logs/raphael.log"
```

---

## 구현 순서 (로드맵)

### Phase 1 — 코어 + 모델 연결
1. `requirements.txt` 작성
2. `config/settings.yaml` + 설정 로더
3. `core/model_router.py` — Ollama 연결, 모델 선택/전환, 헬스체크
4. `core/agent_base.py` — 에이전트 베이스 클래스 (툴 바인딩, 메모리 접근)
5. `core/orchestrator.py` — 에이전트 조율 로직

### Phase 2 — 메모리 시스템
6. `memory/obsidian_loader.py` — MD 파일 파싱, 청킹, ChromaDB 인덱싱
7. `memory/rag.py` — 유사도 검색, 컨텍스트 주입

### Phase 3 — 툴 레이어
8. `tools/file_reader.py` — txt/md/pdf/csv/코드 파일 읽기
9. `tools/file_writer.py` — 파일 생성/수정/삭제
10. `tools/executor.py` — subprocess 실행, 로그 기록
11. `tools/tool_registry.py` — 툴 등록/조회

### Phase 4 — 에이전트
12. `agents/coding_agent.py`
13. `agents/research_agent.py`
14. `agents/note_agent.py`
15. `agents/task_agent.py`

### Phase 5 — 인터페이스
16. `interfaces/cli.py` — Typer 기반 CLI, 대화/명령어 모드
17. `interfaces/web_ui.py` — Gradio 채팅 UI, 파일 업로드/다운로드 지원
18. `interfaces/telegram_bot.py`
19. `interfaces/discord_bot.py`

### Phase 6 — 파인튜닝 파이프라인
18. `memory/finetune/dataset_builder.py`
19. `memory/finetune/lora_trainer.py`

---

## 인터페이스별 특징

| 인터페이스 | 접근 방법 | 특징 |
|---|---|---|
| CLI | `python main.py cli` | 개발/테스트 최적, 스크립트 연동 가능 |
| Web UI | `http://localhost:7860` | 파일 업로드/다운로드, 대화 히스토리 시각화 |
| 텔레그램 | 모바일/데스크탑 앱 | 외부 어디서든 접근, 알림 수신 |
| 디스코드 | 디스코드 서버 | 채널별 에이전트 분리, 팀 활용 가능 |

---

## CLI 사용 예시

```bash
# 대화 모드
python main.py cli chat

# 단발성 명령
python main.py cli ask "오늘 옵시디언 노트 요약해줘"

# 모델 관리
python main.py cli model list
python main.py cli model use gemma4-e4b-sfp8

# 메모리 관리
python main.py cli memory index
python main.py cli memory search "프로젝트 계획"

# 상태 확인
python main.py cli status
```

---

## 봇 명령어 (텔레그램/디스코드 공통)

```
/model list              사용 가능한 모델 목록 출력
/model use <key>         모델 전환 (예: /model use gemma4-e4b-sfp8)
/model status            현재 모델 + Ollama 서버 상태

/memory index            옵시디언 볼트 전체 재인덱싱
/memory search <query>   RAG 검색 테스트

/tool run <code>         코드 직접 실행
/tool read <path>        파일 읽기

/agent list              사용 가능한 에이전트 목록
/agent use <name>        에이전트 전환

/status                  라파엘 전체 상태 요약
```

---

## Ollama 서버 초기 설정 (서버 머신에서)

```bash
# 외부 접속 허용
OLLAMA_HOST=0.0.0.0:11434 ollama serve

# systemd 서비스 환경변수로 등록
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/override.conf <<EOF
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
EOF
sudo systemctl daemon-reload
sudo systemctl restart ollama

# 방화벽 (ufw 기준)
sudo ufw allow from 100.0.0.0/8 to any port 11434  # Tailscale 대역
# 또는 로컬 네트워크
sudo ufw allow from 192.168.0.0/16 to any port 11434

# 모델 다운로드
ollama pull gemma4:e4b-q4_0
ollama pull nomic-embed-text
```

---

## 주요 의존성 (`requirements.txt` 초안)

```
# 모델
ollama>=0.2.0

# 벡터 DB
chromadb>=0.5.0

# 파일 처리
pymupdf>=1.24.0       # PDF
python-docx>=1.1.0    # docx (추후)

# 인터페이스
typer>=0.12.0         # CLI
gradio>=4.0.0         # Web UI
python-telegram-bot>=21.0
discord.py>=2.3.0

# 설정
pyyaml>=6.0
python-dotenv>=1.0.0

# 유틸
loguru>=0.7.0
httpx>=0.27.0
```

---

## 개발 원칙

- 모든 설정은 `settings.yaml`에서 관리, 하드코딩 금지
- 시크릿(토큰, 키)은 `.env`에서만 관리
- 모든 파일 실행은 `executor.py`를 통해서만, 로그 필수
- 에이전트는 `agent_base.py`를 반드시 상속
- 모델 교체 시 코드 변경 없이 설정만으로 가능해야 함
- 맥스튜디오 전환을 고려해 하드웨어 종속 코드 최소화

---

## 현재 상태 (v0.13)

- [x] 아키텍처 설계 완료
- [x] 스택 확정
- [x] 설정 구조 설계
- [x] Phase 1~5 (코어 ~ 인터페이스) 완료
- [x] v0.2~v0.11 — 설정 UX, 보안, 봇 강화, 운영, 웹 UI 고도화, 테스트, MCP/스킬/세션
- [x] v0.12 — TOP 4 (멀티모달, 사용자 프로필, MCP 클라이언트, Plan-Execute-Reflect)
- [x] v0.13 — ROADMAP 24개 + Auto-routing 모두 완료

### 통계
- **인터페이스 8종, 에이전트 6종, 도구 24종, CLI 명령 23개**
- **단위 테스트 38 / E2E 20 — 모두 PASS**
- **다중 Ollama + Auto-routing + Plugin + Docker — production ready**

자세한 내용은 [docs/](docs/) 참고.
