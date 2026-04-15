# API Reference

Raphael 내부 클래스 및 함수 레퍼런스.

---

## `core.model_router`

### `class ModelRouter`

Ollama 서버 통신 핸들.

```python
router = ModelRouter()                              # 기본 모델로 초기화
router.switch_model("gemma4-e2b")                   # 동기 모델 전환
cfg, installed, lst = await router.switch_model_checked("gemma4-e2b")
health = await router.health_check()                # {"status": "ok", ...}
installed = await router.list_installed_models()    # ["gemma4:e4b", ...]
```

#### chat API
```python
result = await router.chat(
    messages=[{"role": "user", "content": "..."}],
    model_key=None,             # None이면 current_key
    retry_on_empty=True,        # 빈 응답 시 1회 재시도
    options={"temperature": 0.5},  # DEFAULT_OPTIONS와 병합
)
# returns: Ollama /api/chat 원본 응답 dict
```

#### 스트리밍
```python
async for chunk in router.chat_stream(messages):
    print(chunk["message"]["content"], end="")
```

#### 임베딩
```python
vec = await router.embed("텍스트")  # list[float]
```

#### 토큰 통계
```python
stats = router.get_token_stats()
# {"gemma4:e4b": {"prompt": 1234, "completion": 567, "calls": 10, "total_ms": 8900}}
router.reset_token_stats()
```

#### 임베딩 모델 자동 설치
```python
ok, msg = await router.ensure_embedding_model(pull_if_missing=True)
```

### `exception ModelNotInstalledError`

404 응답을 변환한 사용자 친화적 예외. `str(e)`에 `ollama pull ...` 안내 포함.

---

## `core.agent_base`

### `class AgentBase(ABC)`

```python
@dataclass
class AgentBase(ABC):
    name: str
    description: str
    router: ModelRouter
    tools: list[str] = []                  # 허용된 도구 카테고리
    system_prompt: str = ""
    tool_registry: ToolRegistry | None = None
    approval_callback: callable | None = None   # (tool_name, args) -> bool
    on_tool_call: callable | None = None        # (ToolCall) -> None
    on_tool_result: callable | None = None      # (ToolResult) -> None
```

#### 주요 메서드

```python
agent.add_message(role, content)
agent.get_conversation() -> list[dict]
agent.clear_conversation()                  # system만 유지

# 반드시 구현
async def handle(self, user_input: str, **kw) -> str: ...

# 도구 바인딩
agent.bind_tools(["file_reader", "executor"])
agent.has_tool("file_reader")

# 내보내기
md = agent.export_markdown()
js = agent.export_json()

agent.info()  # {"name", "description", "tools", "model", "conversation_length"}
```

#### 내부
- `_call_model(user_input)` — ReAct 루프 수행 (최대 4회)
- `_maybe_compact()` — 30턴 초과 시 LLM으로 요약
- `_is_tool_allowed(tool_name)` — 매핑 테이블 기반 허용 판별

### 상수
```python
MAX_TOOL_ITERATIONS = 4
COMPACT_THRESHOLD = 30
KEEP_RECENT = 10
DANGEROUS_TOOLS = {"execute", "python", "delete_file"}
```

---

## `core.orchestrator`

### `class Orchestrator`

```python
orch = Orchestrator(router=router)
orch.register(agent)                        # 첫 번째 등록이 기본 에이전트
orch.set_default("research")
orch.get_agent("coding")
orch.list_agents()                          # [{"name", "description", ...}]
orch.default_agent

# 세션
orch.list_sessions()
orch.reset_session("session-id", agent_name=None)  # agent_name=None이면 모든 에이전트 제거

# 라우팅
response = await orch.route(
    user_input="...",
    agent_name=None,                        # None이면 기본
    source=InputSource.CLI,
    session_id="optional-id",
)

orch.status()  # {"agents": [...], "default_agent": ..., "model": ...}
```

---

## `core.input_guard`

```python
from core.input_guard import InputSource, is_trusted, validate_input

# 입력 소스
InputSource.CLI / WEB_UI / TELEGRAM / DISCORD   # 신뢰
InputSource.WEB_SEARCH / RAG_CONTEXT / FILE_CONTENT / EXTERNAL  # 비신뢰

is_trusted(InputSource.CLI)  # True

# 검증
sanitized, warnings = validate_input(text, InputSource.EXTERNAL)
# 비신뢰면 warnings에 감지 내역, sanitized는 정제된 텍스트

# 헬퍼
contains_command(text)       # True/False
contains_injection(text)     # True/False
sanitize_external_text(text) # 정제된 문자열
```

---

## `core.tool_runner`

```python
from core.tool_runner import parse_tool_calls, execute_tool_call, ToolCall, ToolResult

# 파싱
calls = parse_tool_calls(llm_response_text)
# [ToolCall(name="write_file", args={"path": "...", "content": "..."}, raw="...")]

# 실행
result = await execute_tool_call(call, registry)
# ToolResult(name, args, output, error)

# 포매팅
text = format_tool_call_display(call)      # "🔧 write_file(path='/tmp/x', content='...')"
text = format_tool_result_display(result)  # "✓ 파일 저장 완료: ..."

# 응답에서 태그 제거
clean = strip_tool_calls(llm_response)
```

### 지원 도구 이름 (24종)

**파일**: `read_file` `write_file` `append_file` `delete_file` `mkdir`
**실행**: `execute` `python`
**웹/외부**: `web_search` `open_in_browser` `mcp_call`
**Git**: `git_status` `git_diff` `git_log` `git_commit`
**시스템**: `screenshot` `clipboard_read` `clipboard_write` `notify` `speak`
**통신/일정**: `calendar_add` `email_inbox` `email_send`
**변환**: `convert_md_to_html` `convert_md_to_pdf` `convert_csv_to_chart` `image_resize`
**메모리/위임**: `remember` `forget` `delegate`

---

## `core.session_store`

```python
from core.session_store import Session, list_sessions, delete_session

s = Session.new("coding")
s.conversation = [{"role": "user", "content": "hi"}]
path = s.save()                    # ~/.raphael/sessions/<id>.json
loaded = Session.load(s.id)
latest = Session.latest()          # 가장 최근 업데이트 세션

summary_list = list_sessions()
# [{"id", "agent", "updated", "turns", "preview"}, ...]

delete_session(s.id)               # True/False
```

환경변수 `RAPHAEL_SESSIONS_DIR`로 위치 변경 가능.

---

## `core.skills`

```python
from core.skills import save_skill, get_skill, list_skills, delete_skill

save_skill(
    name="code-review",
    description="코드 리뷰 전문가",
    prompt="당신은 시니어 리뷰어입니다...",
    agent="coding",
    tags=["review"],
)

skill = get_skill("code-review")
# Skill(name, description, agent, prompt, tags, path)
addendum = skill.to_system_addendum()  # 시스템 프롬프트 덧붙임 텍스트

all_skills = list_skills()
delete_skill("code-review")
```

환경변수 `RAPHAEL_SKILLS_DIR`로 위치 변경 가능.

---

## `memory.rag`

### `class RAGManager`

```python
rag = RAGManager(router)

# 인덱싱
n = await rag.index_vault(force=False)  # 기존 유지, 신규만 추가
n = await rag.index_vault(force=True)   # 전체 재인덱싱

# 증분 동기화 (권장)
stats = await rag.sync_vault()
# {"added": N, "updated": M, "deleted": K, "unchanged": L}

# 검색
hits = await rag.search("쿼리", n_results=5)
# [SearchResult(content, metadata, distance), ...]

context = await rag.build_context("쿼리", n_results=3)
# "<context>[1] source > section\n...\n</context>"

rag.stats()  # {"collection", "document_count", "vault_path"}
```

---

## `memory.obsidian_loader`

```python
from memory.obsidian_loader import ObsidianLoader, Document

loader = ObsidianLoader(vault_path="/path", chunk_size=500, chunk_overlap=50)
files = loader.scan_files()
parsed = loader.parse_file(path)  # {"path", "title", "frontmatter", "body"}
chunks = loader.chunk_text(body, source, title)  # list[Document]
all_docs = loader.load_all()
one_file = loader.load_file(path)  # 단일 파일만
```

`Document`:
```python
@dataclass
class Document:
    id: str          # md5 해시
    content: str
    metadata: dict   # {source, title, section, mtime, ...}
```

---

## `tools.tool_registry`

```python
from tools.tool_registry import ToolRegistry, create_default_registry

registry = create_default_registry()
# file_reader, file_writer, executor, web_search, git_tool 등록됨

registry.register("custom", instance, "description")
tool = registry.get("file_reader")
registry.has("executor")
registry.list_tools()  # [{"name", "description"}]
```

---

## `tools.path_guard`

```python
from tools.path_guard import check_path, PathNotAllowedError, get_allowed_paths

# 경로 검증 — 실패 시 PathNotAllowedError
safe = check_path("~/Documents/note.md")  # 확장된 Path 반환

allowed = get_allowed_paths()  # list[Path]
```

---

## `tools.web_search`

```python
from tools.web_search import WebSearch

ws = WebSearch(timeout=15.0)
hits = await ws.search("쿼리", max_results=5)
# [SearchHit(title, url, snippet), ...]

text = await ws.summarize("쿼리")  # LLM용 자동 sanitize 포함
```

---

## `tools.git_tool`

```python
from tools.git_tool import GitTool

git = GitTool()
await git.status(cwd="/path")
await git.diff(path=None, cwd="/path", staged=False)
await git.log(n=10, cwd="/path")
await git.commit("메시지", cwd="/path")
```

모두 git 명령 실패 시 에러 메시지 문자열을 반환(예외 던지지 않음).

---

## `config.settings`

```python
from config.settings import (
    get_settings, load_settings, reload_settings,
    save_local_settings, save_env, get_current_onboard_values,
    get_ollama_base_url, get_model_config,
    rebind_paths,
)

s = get_settings()                           # 캐시된 설정
save_local_settings({"models": {"default": "gemma4-e2b"}})
save_env("TELEGRAM_BOT_TOKEN", "xxx")
vals = get_current_onboard_values()          # onboard 필드 현재값

# 테스트 샌드박스
rebind_paths(config_dir="/tmp/sb", project_root="/tmp/sb")
```

환경변수:
- `RAPHAEL_CONFIG_DIR` — settings.local.yaml 위치
- `RAPHAEL_PROJECT_ROOT` — .env 위치
- `RAPHAEL_SESSIONS_DIR` — 세션 저장소
- `RAPHAEL_SKILLS_DIR` — 스킬 저장소

---

## `interfaces.health_api`

```python
from interfaces.health_api import (
    MetricsCollector, METRICS,
    wrap_orchestrator_with_metrics,
    build_app, run_health_server,
)

wrap_orchestrator_with_metrics(orch)  # orch.route를 계측 버전으로 교체
run_health_server(router, orch, host="127.0.0.1", port=7861)

# 수동 기록
METRICS.record(agent="coding", duration_ms=123.4, error=False)
print(METRICS.prometheus_format())
```

---

---

## `core.profile` (v0.12)

```python
from core.profile import Profile, Fact, profile_path

p = Profile.load()
fact = p.add("사용자는 Python 개발자", source="tool")
p.forget("Python")        # 패턴 매칭 fact 모두 삭제
p.clear()
p.to_system_addendum()    # system 메시지에 덧붙일 텍스트
```

환경변수 `RAPHAEL_PROFILE_PATH` 오버라이드.

---

## `core.audit` (v0.13)

```python
from core import audit

audit.append("tool_call", {"name": "write_file", "args": {...}}, agent="coding", session="cli")
ok, count, msg = audit.verify()  # SHA256 chain 무결성 검증
recent = audit.show(50)
```

각 엔트리: `{ts, type, agent, session, data, prev_hash, hash}`

---

## `core.checkpoint` (v0.13)

```python
from core import checkpoint

cp = checkpoint.create_checkpoint("write", "/path/to/file", note="before-edit")
checkpoint.list_checkpoints(limit=50)
checkpoint.restore(cp.id)
checkpoint.cleanup_old(days=7)
```

저장: `~/.raphael/backups/<timestamp>__<hash>/`

---

## `core.feedback` (v0.13)

```python
from core import feedback

feedback.record(session="s1", agent="coding", question="...", response="...", score=1)
stats = feedback.stats()  # {"total", "positive", "negative", "neutral"}
```

---

## `core.secrets` (v0.13)

```python
from core.secrets import get_secret, set_secret, delete_secret

backend = set_secret("EMAIL_PASSWORD", "...")  # "keychain" 또는 ".env"
v = get_secret("EMAIL_PASSWORD")
delete_secret("EMAIL_PASSWORD")
```

---

## `core.ollama_pool` (v0.13)

```python
from core.ollama_pool import OllamaPool, OllamaServer

pool = OllamaPool()  # settings.models.ollama_pool 자동 로드
target = await pool.select_for_model("gemma4:26b")  # least-busy
resp = await target.request("POST", "/api/chat", json=payload)
healths = await pool.health_all()
await pool.close_all()
```

---

## `core.router_strategy` (v0.13)

```python
from core.router_strategy import RouterStrategy, TaskContext, RouteDecision

strat = RouterStrategy()
ctx = TaskContext(user_input="...", agent="coding", messages_count=10)
decision = strat.decide(ctx)
# decision.model_key, decision.agent_name, decision.rule_name
```

---

## `core.activity_log` (v0.12+)

```python
from core.activity_log import ActivityLogger

al = ActivityLogger(session_id="cli:main", console=True, on_event=callback)
al.attach(agent)         # on_tool_call/on_tool_result 훅 설치
al.user_message("...")
al.model_call_start(model, messages_count, iteration)
al.model_call_progress(elapsed_seconds)
al.model_call_end(model, duration_seconds, tokens={"prompt": N, "completion": M})
al.token_chunk(text)     # 스트리밍 토큰
al.tool_call(call)       # ToolCall 객체
al.tool_result(result)   # ToolResult 객체
```

---

## `core.mcp_client` (v0.12)

```python
from core.mcp_client import MCPClientManager

mgr = MCPClientManager()
await mgr.start(registry)   # settings.mcp.servers 모두 기동, ToolRegistry에 등록
items = mgr.list_tools()    # [{"server": "...", "tool": "..."}]
await mgr.stop()
```

---

## `core.plugin_loader` (v0.13)

```python
from core.plugin_loader import load_tool_plugins, load_agent_plugins

n_tools = load_tool_plugins(registry)
n_agents = load_agent_plugins(orchestrator, router, registry)
```

외부 패키지 pyproject.toml entry_points:
```toml
[project.entry-points."raphael.tools"]
my_tool = "my_pkg:MyTool"

[project.entry-points."raphael.agents"]
my_agent = "my_pkg:MyAgent"
```

---

## `memory.conversation_index` (v0.13)

```python
from memory.conversation_index import ConversationIndex

ci = ConversationIndex(router)
n = await ci.index_session(session_id)
n_total = await ci.index_all()
hits = await ci.search("쿼리", n_results=10)
# [ConvHit(session_id, role, content, distance), ...]
```

---

## `tools.git_tool` / `browser_tool` / `screenshot_tool` / `clipboard_tool` / `notification_tool` / `calendar_tool` / `email_tool` / `converter_tool`

비동기 메서드들. 자세한 시그니처는 각 모듈 docstring 참고.

```python
from tools.git_tool import GitTool
git = GitTool()
await git.status(cwd="/path")
await git.diff(staged=True, cwd="/path")
await git.commit("msg", cwd="/path")

from tools.notification_tool import NotificationTool
await NotificationTool().notify("제목", "본문")

from tools.calendar_tool import CalendarTool
await CalendarTool().add_event("회의", "2026-04-15T15:00", duration_minutes=60)

from tools.converter_tool import ConverterTool
ConverterTool().md_to_html("/path/in.md", "/path/out.html")
ConverterTool().csv_to_chart("/data.csv", "/chart.png", x="date", y="sales")
```

---

## `interfaces.voice` / `tray_app` / `slack_bot` (v0.13)

```python
from interfaces.voice import tts_speak, stt_transcribe, voice_session
await tts_speak("안녕하세요")
text = stt_transcribe("/path/to/audio.wav")
await voice_session(orchestrator)

from interfaces.tray_app import run_tray
run_tray(orchestrator, router)

from interfaces.slack_bot import SlackBot
SlackBot(router, orchestrator).run()
```

---

## 도구 태그 문법 (LLM ↔ 시스템)

```xml
<tool name="write_file">
<arg name="path">/tmp/out.txt</arg>
<arg name="content">내용</arg>
</tool>
```

- `<tool name="X">` — 도구 이름
- `<arg name="Y">값</arg>` — 인자
- 한 응답에 여러 `<tool>` 블록 가능 (순서대로 실행)
- 미닫힘 / name 누락 태그는 무시됨
- content에 `<`/`>` 포함 가능

### 결과 피드백 형식
시스템이 다음 턴 user 메시지로 주입:
```
<tool_results>
<tool_result name="write_file" status="OK">
파일 저장 완료: /tmp/out.txt
</tool_result>
</tool_results>
```
