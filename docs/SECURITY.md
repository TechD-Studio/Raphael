# 보안 모델

Raphael의 보안 설계 및 위협 대응 가이드.

---

## 위협 모델

Raphael는 **개인 사용자가 로컬에서 운영**하는 것을 전제로 하지만, 아래 위협을 고려한다:

| 위협 | 벡터 | 대응 |
|---|---|---|
| **프롬프트 인젝션** | RAG 문서, 웹 검색 결과, 파일 내용에 "ignore previous instructions" 류 삽입 | `input_guard.sanitize_external_text()` — 패턴 치환 + 접두사 무력화 + 투명성 배너 |
| **LLM 탈옥 후 파일 시스템 파괴** | `<tool name="write_file" path="/etc/passwd">` | `path_guard.check_path()` — `allowed_paths` 외부 거부 |
| **무단 봇 접근** | 봇 토큰 유출 시 임의 사용자 조작 | `allowed_users` allowlist 필수 검증 (빈 목록 = 모두 거부) |
| **다중 사용자 대화 누수** | 사용자 A의 발언을 사용자 B가 봄 | `Orchestrator` 세션별 conversation 격리 |
| **자동 실행 남용** | LLM이 `rm -rf`, `delete_file` 호출 | 위험 도구(`DANGEROUS_TOOLS`) `approval_callback` |
| **민감 정보 유출** | `.env`의 토큰이 로그/git에 노출 | `.gitignore`에 `.env`, `settings.local.yaml` 포함 |
| **검색 결과 SSRF/페이로드** | 악의적 페이지 스니펫 | `web_search.summarize()`가 자동 sanitize |

---

## 입력 소스 분류

`core.input_guard.InputSource`로 입력이 어디서 왔는지 태깅.

### 신뢰 소스 (명령어 허용)
- `CLI` — 로컬 터미널 직접 입력
- `WEB_UI` — 로컬 Gradio 창
- `TELEGRAM` — `allowed_users` 통과한 사용자
- `DISCORD` — `allowed_users` 통과한 사용자

### 비신뢰 소스 (명령어 차단 + 인젝션 패턴 치환)
- `WEB_SEARCH` — DuckDuckGo 결과
- `RAG_CONTEXT` — 옵시디언 문서
- `FILE_CONTENT` — `read_file`로 읽은 외부 파일
- `EXTERNAL` — 기타 외부 소스

### 동작
```python
sanitized, warnings = validate_input(text, InputSource.EXTERNAL)
# 비신뢰 소스 + 위협 감지 → sanitized는 안전한 버전, warnings는 사용자에게 표시할 배너
```

신뢰 소스는 그대로 통과 (명령어 `/command` 실행 정상).
비신뢰 소스는 `/` → `∕`(유니코드), 인젝션 패턴 → `[blocked]`로 치환.

---

## 인젝션 패턴

`input_guard._INJECTION_PATTERNS`에서 감지:

- `ignore\s+(previous|above|all)[\s\w]*(instructions?|prompts?)?`
- `disregard\s+(previous|above|all)...`
- `you\s+are\s+now\s+`
- `new\s+instructions?:`
- `system\s*:\s*`
- `<\s*system\s*>`
- `execute\s+(this|the\s+following)...`
- `run\s+(this|the\s+following)...`
- `eval\s*\(`, `exec\s*\(`, `subprocess`, `os\.system`
- 한국어: `이전\s*지시를?\s*무시`, `새로운\s*지시`, `명령어를?\s*실행`

대소문자 무관. 단독 `eval` 등 무해한 단어는 포함되지 않으므로 false positive 최소화.

---

## 파일 경로 샌드박스

`tools/path_guard.py` — 모든 파일 도구가 통과해야 하는 게이트.

### 허용 경로 계산
1. `settings.yaml` 의 `tools.file.allowed_paths` 우선
2. 비어있으면 기본값: `$HOME`, `/tmp`, `/var/folders` (macOS 임시 디렉토리)

### 검증 알고리즘
```python
def check_path(path: str) -> Path:
    resolved = Path(path).expanduser().resolve()  # 심볼릭 링크 우회 방지
    for base in allowed:
        try:
            resolved.relative_to(base)  # base 하위면 OK
            return resolved
        except ValueError:
            continue
    raise PathNotAllowedError(...)
```

### 설정 예시
```yaml
tools:
  file:
    allowed_paths:
      - "~/workspace"
      - "~/Documents"
      - "~/Obsidian"
    max_file_size_mb: 50
    supported_formats: ["txt", "md", "pdf", "csv", "py", "js", "json", "yaml"]
```

### 차단되는 경로 예
- `/etc/passwd` — 시스템 경로
- `../../etc/shadow` — 상대 경로 탈출 (resolve 시 절대 경로화되어 차단됨)
- 심볼릭 링크로 외부를 가리키는 경우 — resolve 결과가 실제 경로라 차단됨

---

## 봇 보안

### allowlist 구성

**텔레그램 user_id 확인**: `@userinfobot`에게 `/start` 전송
**디스코드 user_id 확인**: 설정 → 고급 → 개발자 모드 켜고 프로필 우클릭 → ID 복사

```yaml
interfaces:
  telegram:
    allowed_users: [123456789, 234567890]  # 정수 user_id 리스트
  discord:
    allowed_users: [987654321098765432]
```

### 빈 목록 = 거부
```python
self.allowed_users: set[int] = set(cfg.get("allowed_users") or [])

def _is_authorized(self, user):
    if not self.allowed_users:
        return False  # safe default
    return user.id in self.allowed_users
```

### 미허가 응답
사용자 user_id를 알려주면서 거부 메시지 반환 → 소유자에게 허용 요청 쉬움.

### 사용자별 세션 격리
- Telegram: `session_id = f"tg:{chat.id}"`
- Discord: `session_id = f"dc:{channel.id}"`

각 `session_id`마다 conversation이 분리되어 **다른 사용자의 대화가 컨텍스트에 섞이지 않음**.

---

## 위험 도구 승인

`AgentBase.DANGEROUS_TOOLS = {"execute", "python", "delete_file"}`

`approval_callback`이 설정되면 실행 전 호출:

```python
def my_approval(tool_name: str, args: dict) -> bool:
    if tool_name == "delete_file":
        return input(f"정말로 {args['path']}를 삭제할까요? (y/N) ").lower() == "y"
    return True

agent.approval_callback = my_approval
```

- 콜백이 `False` 반환 시 해당 도구는 "사용자가 실행을 거부했습니다" 메시지와 함께 skip
- 동기/비동기 콜백 모두 지원
- 에이전트는 거부 결과를 받고 다른 접근을 시도하거나 포기

---

## 시크릿 관리

### `.env` 파일
- 프로젝트 루트에 위치 (`~/.zshrc` alias 환경에서는 raphael 실행 시 cwd 기준이 아니라 설치 시 고정된 경로)
- git 추적 제외 (`.gitignore`)
- `save_env()`가 기존 값 보존하며 key만 업데이트

### `${VAR}` 치환
`settings.yaml`에서 `${TELEGRAM_BOT_TOKEN}`처럼 쓰면 `.env`에서 자동 치환.

### 로그 마스킹
- 현재 토큰 값이 로그에 직접 찍히는 경우는 없음 (설정 조회는 파일 경로만 로그)
- 웹 UI 토큰 입력창은 `type="password"`로 마스킹

---

## 인젝션 방어 배너

비신뢰 소스 감지 시 `Orchestrator.route`가 응답 상단에 투명성 배너 첨부:

```
⚠ 외부 콘텐츠 보안 경고 (아래 패턴이 감지되어 무력화되었습니다):
  - 프롬프트 인젝션 패턴 감지 (source=rag_context)
  - 명령어 패턴 감지 — 비신뢰 소스이므로 실행하지 않음 (source=web_search)

---

(정상 응답)
```

사용자가 **무엇이 차단되었는지 명시적으로 인지**할 수 있도록 설계.

---

## 알려진 한계

### LLM 지시 추종 불안정성
gemma4:e4b (8B) 같은 작은 모델은 시스템 프롬프트 지시를 100% 따르지 않음.
- 대응: 시스템 프롬프트에 `"불가능하다고 답하지 말고 도구를 호출하라"` 명시
- 대응: temperature 0.3 기본값
- 대응: 빈 응답 1회 재시도

### 코드 실행 샌드박싱 없음
`execute`, `python` 도구는 현재 **호스트 프로세스 권한**으로 실행.
- `settings.yaml`의 `tools.executor.sandbox: false`는 플래그만 있고 실제 샌드박싱은 미구현
- 완화: `DANGEROUS_TOOLS`에 포함 → `approval_callback`으로 수동 확인 가능
- 향후: Docker/nsjail/bwrap 통합 검토

### 사이드채널
- 웹 UI는 localhost에 바인딩되지만, 0.0.0.0으로 열면 네트워크 전체 노출
- Health API는 인증 없음 → 로컬 전용으로만 사용 권장
- 대응: 외부 노출 시 리버스 프록시 + 인증 계층 별도 구성

### DoS
- 단일 Ollama 서버 → 무거운 요청이 누적되면 전체 느려짐
- `raphael health`에 요청 수/지연 메트릭 있음 → Grafana 등으로 모니터링 권장

---

## v0.13 신규 보안 기능

### OS Keychain 시크릿 (`core/secrets.py`)

`.env` 평문 대신 OS 키체인에 저장:

```bash
raphael secret set EMAIL_PASSWORD       # 입력 프롬프트 (마스킹)
raphael secret get GH_TOKEN
raphael secret delete OLD_TOKEN
```

```python
from core.secrets import get_secret, set_secret
backend = set_secret("KEY", "VALUE")  # "keychain" 또는 ".env"
v = get_secret("KEY")
```

- macOS Keychain / Linux Secret Service / Windows Credential Manager 자동
- keyring 미설치/실패 시 `.env` fallback (안전 기본)
- `${VAR}` 치환은 둘 다 지원 (먼저 keychain → 환경변수)

### 파일 작업 체크포인트 (`core/checkpoint.py`)

`write_file` / `delete_file` 호출 시 자동 백업:

```bash
raphael rollback list                   # 최근 체크포인트
raphael rollback restore <id>           # 원본 복원
raphael rollback cleanup [days]         # 오래된 것 정리 (기본 7일)
```

저장: `~/.raphael/backups/<timestamp>__<hash>/<filename>` + `meta.json`
LLM이 잘못 작성/삭제했을 때 복구 가능.

### Audit log + 변조 방지 (`core/audit.py`)

모든 도구 실행이 SHA256 hash chain으로 기록:

```bash
raphael audit show                      # 최근 50건
raphael audit verify                    # 체인 무결성 검증
```

각 엔트리:
```json
{
  "ts": "2026-04-15T10:00:00",
  "type": "tool_call",
  "agent": "coding",
  "session": "cli:main",
  "data": {"name": "write_file", "args": {...}, "error": false},
  "prev_hash": "abc...",
  "hash": "def..."
}
```

- 한 줄 변조 시 그 이후 모든 hash 불일치 → `verify()`가 즉시 감지
- append-only 보장 (수정 X, 삭제 X)
- `~/.raphael/audit.log` 권한을 `chmod 600` 권장

### 사용자 피드백 학습 (`core/feedback.py`)

응답 평가를 누적해 향후 RAG few-shot 예시로 활용 가능:

```bash
raphael feedback                       # 통계 (👍/👎/중립)
```

---

## 권장 보안 체크리스트

- [ ] `.env`와 `settings.local.yaml`이 `.gitignore`에 있는지 확인
- [ ] 봇을 띄우기 전 `allowed_users`에 자신의 user_id 등록
- [ ] `allowed_paths`를 실제 작업 디렉토리로 좁혀 설정
- [ ] 외부 IP로 웹 UI/Health API 노출 시 추가 인증 계층 구성
- [ ] 위험 작업(`delete_file`, `execute`) 이 빈번하면 `approval_callback` 설정
- [ ] Ollama 서버도 `allow list` 방화벽으로 접근 제한 (`ufw allow from 192.168.0.0/16 to any port 11434`)
- [ ] 로그 파일(`logs/raphael.log`, `logs/exec.log`)에 민감 정보가 없는지 주기적 검토
- [ ] **시크릿은 `raphael secret set`으로 OS Keychain에 저장 (`.env` 평문 회피)**
- [ ] **`raphael audit verify` 정기 실행** (예: cron으로 매일)
- [ ] **`raphael rollback cleanup` 주기 실행** (오래된 백업 삭제)
- [ ] Docker 이미지 사용 시 `~/.raphael` 볼륨이 호스트에 노출되는지 확인
