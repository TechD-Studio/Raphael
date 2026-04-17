# Raphael AI Agent

> 제한된 로컬 하드웨어에서 gemma4가 어디까지 가능한지 탐구하는 개인 AI 에이전트 프레임워크.

---

## 사용 경고

**Raphael은 실제 컴퓨터에서 파일 생성, 코드 실행, 셸 명령 실행, 웹 접속 등을 수행할 수 있는 강력한 AI 에이전트입니다.**

사용 전 반드시 인지하세요:

- **파일이 의도치 않게 생성, 수정 또는 삭제될 수 있습니다**
- **셸 명령이 시스템에 영향을 줄 수 있습니다**
- **외부 네트워크에 요청을 보낼 수 있습니다**
- **AI의 판단이 부정확하거나 잘못될 수 있습니다**
- **중요한 데이터는 반드시 백업하세요**

위험 도구(execute, python, delete_file) 실행 시 승인 팝업이 표시됩니다. 신중하게 검토하세요. **사용으로 인한 모든 결과는 사용자의 책임입니다.**

---

## 설치

### 방법 1: 데스크톱 앱 (macOS / Windows)

1. [GitHub Releases](https://github.com/TechD-Studio/Raphael/releases)에서 최신 버전 다운로드
   - macOS: `Raphael_x.x.x_aarch64.dmg`
   - Windows: `Raphael_x.x.x_x64-setup.exe`
2. 설치 후 실행
3. 첫 실행 시 **사용 경고 동의** 화면이 표시됩니다

#### macOS 미서명 앱 경고 해결
```bash
sudo xattr -dr com.apple.quarantine /Applications/Raphael.app
```

#### Windows SmartScreen 경고
"추가 정보" → "실행" 클릭

### 방법 2: CLI (개발자)

```bash
git clone https://github.com/TechD-Studio/Raphael.git
cd Raphael
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
raphael onboard    # 초기 설정 마법사
raphael            # 대화 모드
```

### 방법 3: 웹 UI (원격 접속)

```bash
raphael web --port 9000
# 브라우저: http://localhost:9000
# Tailscale: http://<tailscale-ip>:9000
```

---

## 사전 요구사항

### Ollama (필수)
Raphael은 로컬 LLM 실행에 [Ollama](https://ollama.com)를 사용합니다.

```bash
# macOS
brew install ollama
ollama serve

# 모델 설치
ollama pull gemma4:e4b    # 권장 (9B, ~5GB)
ollama pull gemma4:e2b    # 경량 (5B, ~3GB)
```

### Claude 구독 (선택)
Claude Code CLI가 설치되어 있으면 에스컬레이션 폴백으로 사용 가능.
```bash
# claude CLI 설치 + 로그인 후
# 설정 > 모델 > 에스컬레이션 사다리에 claude-sonnet 추가
```

---

## 주요 기능

| 기능 | 설명 |
|---|---|
| **다중 인터페이스** | 데스크톱 앱, 웹 UI, CLI, Telegram, Discord, Slack, 음성 |
| **6종 에이전트** | coding, research, writer, planner, reviewer + 커스텀 |
| **24종 도구** | 파일, 코드 실행, Git, 웹 검색, 스크린샷, 클립보드, 이메일, 캘린더 등 |
| **이미지 생성** | FLUX.1 (로컬, 무료) / DALL-E 3 (API) |
| **모델 에스컬레이션** | gemma4-e2b → e4b → 26b → Claude (자동 전환) |
| **RAG** | 옵시디언 볼트 연동 (ChromaDB) |
| **파인튜닝** | QLoRA 학습 → Ollama 등록 (설정 UI) |
| **기억 시스템** | Daily Log + Project Context + 성공 패턴 |
| **보안** | 인젝션 방어, 파일 샌드박스, 위험 도구 승인, Keychain, Audit chain |
| **다크 모드** | macOS 시스템 설정 자동 연동 |

---

## 문서

| 문서 | 설명 |
|---|---|
| [docs/USER_GUIDE.md](docs/USER_GUIDE.md) | 전체 사용 가이드 |
| [docs/RELEASE_NOTES.md](docs/RELEASE_NOTES.md) | 릴리스 노트 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 시스템 아키텍처 |
| [docs/FEATURES.md](docs/FEATURES.md) | 전체 기능 목록 |
| [docs/SECURITY.md](docs/SECURITY.md) | 보안 모델 |
| [docs/UPGRADE_BACKLOG.md](docs/UPGRADE_BACKLOG.md) | 향후 업그레이드 목록 |

---

## 라이선스

이 프로젝트는 개인 사용 목적으로 개발되었습니다.

---

**TechD Studio** — [GitHub](https://github.com/TechD-Studio/Raphael)
