"""LLM 출력을 파싱해 도구를 실행하고 결과를 반환한다.

에이전트가 다음 태그 형식으로 도구를 호출할 수 있다:

  <tool name="read_file">
  <arg name="path">/Users/dh/note.md</arg>
  </tool>

  <tool name="execute">
  <arg name="command">ls -la</arg>
  </tool>

  <tool name="write_file">
  <arg name="path">/tmp/out.txt</arg>
  <arg name="content">hello</arg>
  </tool>

  <tool name="delete_file">
  <arg name="path">/tmp/out.txt</arg>
  </tool>

  <tool name="web_search">
  <arg name="query">gemma4 모델 스펙</arg>
  </tool>

동일 응답에 여러 tool 태그를 포함할 수 있으며, 순서대로 실행된다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from loguru import logger

from tools.tool_registry import ToolRegistry

# 전체 tool 블록
_TOOL_RE = re.compile(
    r'<tool\s+name="(?P<name>[\w_]+)"\s*>(?P<body>.*?)</tool>',
    re.DOTALL,
)

# arg 파싱 — gemma4가 종종 </arg>를 빼먹고 바로 </tool>로 닫는 패턴을 허용.
# value는 다음 중 가장 먼저 만나는 경계까지: </arg>, 다음 <arg 시작, </tool>, 문자열 끝.
_ARG_RE = re.compile(
    r'<arg\s+name="(?P<name>[\w_]+)"\s*>(?P<value>.*?)(?:</arg>|(?=<arg\s+name=)|(?=</tool>)|\Z)',
    re.DOTALL,
)


@dataclass
class ToolCall:
    name: str
    args: dict
    raw: str  # 원본 매칭 텍스트


@dataclass
class ToolResult:
    name: str
    args: dict
    output: str
    error: bool = False


def parse_tool_calls(text: str) -> list[ToolCall]:
    """LLM 응답에서 tool 호출을 파싱한다. 공백/개행 정규화 후 중복 제거.

    arg value에 포함된 HTML 엔티티(&lt; &gt; &amp; 등)는 자동 디코드해서
    실제 문자로 복원 — LLM이 코드 블록을 이스케이프한 채 넘기는 케이스 대응.
    """
    import re as _re
    import html as _html
    calls: list[ToolCall] = []
    seen: set[tuple] = set()
    for m in _TOOL_RE.finditer(text):
        name = m.group("name")
        body = m.group("body")
        args: dict[str, str] = {}
        for am in _ARG_RE.finditer(body):
            raw_val = am.group("value").strip()
            # HTML 엔티티 디코드 (실제 <script> 태그가 본문에 있으면 복원)
            args[am.group("name")] = _html.unescape(raw_val)
        # 중복 키 계산 시 연속 공백/개행 정규화 (의미 동일한 중복 잡기)
        norm = tuple(sorted((k, _re.sub(r"\s+", " ", v)) for k, v in args.items()))
        key = (name, norm)
        if key in seen:
            continue
        seen.add(key)
        calls.append(ToolCall(name=name, args=args, raw=m.group(0)))
    return calls


def strip_tool_calls(text: str) -> str:
    """응답에서 tool 블록을 제거한 사람-친화적 텍스트를 반환."""
    return _TOOL_RE.sub("", text).strip()


async def execute_tool_call(call: ToolCall, registry: ToolRegistry) -> ToolResult:
    """파싱된 tool 호출을 실제로 실행한다. audit log에 기록."""
    from core import audit
    logger.info(f"도구 실행: {call.name} {list(call.args.keys())}")
    try:
        output = await _dispatch(call, registry)
        result = ToolResult(name=call.name, args=call.args, output=output, error=False)
    except Exception as e:
        logger.error(f"도구 실행 실패: {call.name} — {e}")
        result = ToolResult(name=call.name, args=call.args, output=str(e), error=True)

    try:
        audit.append("tool_call", {
            "name": call.name,
            "args": {k: v[:200] if isinstance(v, str) else v for k, v in call.args.items()},
            "error": result.error,
            "output_preview": result.output[:200] if isinstance(result.output, str) else "",
        })
    except Exception as e:
        logger.debug(f"audit append 실패: {e}")
    return result


class StreamingTagFilter:
    """LLM 토큰 스트림에서 <tool>...</tool> 블록을 사용자 표시에서 제외한다.

    토큰 경계가 임의이므로(예: '<to' / 'ol name' / ...) 안전하게 버퍼링하며
    완전한 태그 매칭을 기다린 뒤 flush 한다.

    parse_tool_calls는 전체 원본 텍스트로 동작하므로 도구 실행에는 영향 없음.
    """

    TOOL_OPEN_PREFIX = "<tool"
    TOOL_CLOSE = "</tool>"
    HOLD_TAIL = 6  # 태그 시작 끊겨 들어올 가능성 대비 마지막 N자 보류

    def __init__(self) -> None:
        self.buffer: str = ""
        self.in_tool: bool = False

    def feed(self, chunk: str) -> str:
        """청크 추가 후 사용자에게 즉시 보여줄 수 있는 안전 부분만 반환."""
        if not chunk:
            return ""
        self.buffer += chunk
        out_parts: list[str] = []

        while self.buffer:
            if self.in_tool:
                idx = self.buffer.find(self.TOOL_CLOSE)
                if idx == -1:
                    return "".join(out_parts)  # 종료 태그 대기
                # </tool> 발견 → 태그 블록 통째로 버림
                self.buffer = self.buffer[idx + len(self.TOOL_CLOSE):]
                self.in_tool = False
            else:
                idx = self.buffer.find(self.TOOL_OPEN_PREFIX)
                if idx == -1:
                    # 태그 시작 신호 없음 → 마지막 일부는 hold (끊긴 '<too' 같은 경우 대비)
                    safe_end = max(0, len(self.buffer) - self.HOLD_TAIL)
                    if safe_end > 0:
                        out_parts.append(self.buffer[:safe_end])
                        self.buffer = self.buffer[safe_end:]
                    return "".join(out_parts)
                # 태그 시작 이전까지 출력
                if idx > 0:
                    out_parts.append(self.buffer[:idx])
                self.buffer = self.buffer[idx:]
                self.in_tool = True

        return "".join(out_parts)

    def flush(self) -> str:
        """스트림 종료 시 남은 안전 부분을 모두 반환."""
        if self.in_tool:
            # 태그 안에서 종료 → 모두 버림
            self.buffer = ""
            return ""
        out, self.buffer = self.buffer, ""
        return out


def format_tool_call_display(call: "ToolCall") -> str:
    """LLM이 호출한 도구를 사람이 읽기 좋게 포맷한다 (UI 표시용)."""
    summary = []
    for k, v in call.args.items():
        val = v if len(v) < 80 else v[:80] + "…"
        val = val.replace("\n", " ")
        summary.append(f"{k}={val!r}")
    return f"🔧 {call.name}({', '.join(summary)})"


def format_tool_result_display(result: "ToolResult") -> str:
    """실행 결과를 UI 표시용으로 포맷."""
    icon = "✗" if result.error else "✓"
    output = result.output
    if len(output) > 200:
        output = output[:200] + "…"
    return f"{icon} {output}"


async def _dispatch(call: ToolCall, registry: ToolRegistry) -> str:
    """도구 이름별 디스패치. 결과는 문자열로 통일."""
    name = call.name
    args = call.args

    if name == "delegate":
        # 서브에이전트 위임: agent + task 인자 필수
        if not registry.has("_orchestrator"):
            return "delegate 도구는 orchestrator가 등록된 환경에서만 사용 가능합니다."
        target = _require(args, "agent")
        task = _require(args, "task")
        orch = registry.get("_orchestrator")

        # 위임 깊이 제한 (재귀 폭주 방지)
        from core.delegate_state import current_depth, push_depth, pop_depth, MAX_DEPTH
        depth = current_depth()
        if depth >= MAX_DEPTH:
            return f"delegate 깊이 한도({MAX_DEPTH}) 초과 — 더 이상 위임하지 않음"

        # 활성 에이전트만 허용 (main이 카탈로그 외 호출 차단)
        try:
            from core.agent_definitions import load_active_agents, record_usage
            active = load_active_agents()
            if active and target not in active:
                return f"'{target}' 은 비활성 에이전트입니다. 활성 목록: {sorted(active)}"
        except Exception:
            record_usage = None  # type: ignore

        import uuid as _uuid
        sub_session = f"delegated-{_uuid.uuid4().hex[:8]}"
        push_depth()
        try:
            from core.input_guard import InputSource
            result = await orch.route(
                task,
                agent_name=target,
                source=InputSource.CLI,
                session_id=sub_session,
            )
            if record_usage:
                try:
                    record_usage(target, was_helpful=True)
                except Exception:
                    pass
            return f"[{target} 위임 결과]\n{result}"
        except Exception as e:
            return f"delegate 실패: {e}"
        finally:
            pop_depth()

    if name == "git_status":
        if not registry.has("git_tool"):
            return "git 도구가 등록되지 않았습니다."
        return await registry.get("git_tool").status(args.get("cwd"))

    if name == "git_diff":
        if not registry.has("git_tool"):
            return "git 도구가 등록되지 않았습니다."
        return await registry.get("git_tool").diff(args.get("path"), args.get("cwd"), bool(args.get("staged", "")))

    if name == "git_log":
        if not registry.has("git_tool"):
            return "git 도구가 등록되지 않았습니다."
        return await registry.get("git_tool").log(int(args.get("n", "10")), args.get("cwd"))

    if name == "git_commit":
        if not registry.has("git_tool"):
            return "git 도구가 등록되지 않았습니다."
        return await registry.get("git_tool").commit(_require(args, "message"), args.get("cwd"))

    if name == "fetch_url":
        if not registry.has("fetch_tool"):
            return "fetch 도구 미등록"
        return await registry.get("fetch_tool").fetch(
            _require(args, "url"),
            max_chars=int(args.get("max_chars", "8000") or 8000),
            prompt=args.get("prompt"),
        )

    if name == "open_in_browser":
        # alias: url/path/file → target (LLM이 자주 혼동)
        for alt in ("url", "path", "file"):
            if alt in args and "target" not in args:
                args["target"] = args[alt]
                break
        if not registry.has("browser_tool"):
            return "browser 도구가 등록되지 않았습니다."
        return registry.get("browser_tool").open(_require(args, "target"))

    if name == "screenshot":
        if not registry.has("screenshot_tool"):
            return "screenshot 도구가 등록되지 않았습니다."
        return await registry.get("screenshot_tool").capture(args.get("path"))

    if name == "clipboard_read":
        if not registry.has("clipboard_tool"):
            return "clipboard 도구가 등록되지 않았습니다."
        return await registry.get("clipboard_tool").read()

    if name == "clipboard_write":
        if not registry.has("clipboard_tool"):
            return "clipboard 도구가 등록되지 않았습니다."
        return await registry.get("clipboard_tool").write(_require(args, "text"))

    if name == "mcp_call":
        # MCP 서버의 도구 호출 — server/tool 인자 필수
        server = _require(args, "server")
        tool = _require(args, "tool")
        full = f"mcp:{server}:{tool}"
        if not registry.has(full):
            return f"MCP 도구를 찾을 수 없음: {full}"
        # tool 인자 외 나머지를 MCP 도구 인자로 전달
        tool_args = {k: v for k, v in args.items() if k not in {"server", "tool"}}
        # tool_args가 단일 'args' JSON 문자열로 들어올 수 있음 (LLM이 그렇게 만들기 쉬움)
        if "args" in tool_args and len(tool_args) == 1:
            try:
                import json as _json
                tool_args = _json.loads(tool_args["args"])
            except Exception:
                pass
        proxy = registry.get(full)
        return await proxy.call(tool_args)

    if name == "notify":
        if not registry.has("notification_tool"):
            return "notification 도구 미등록"
        return await registry.get("notification_tool").notify(_require(args, "title"), args.get("message", ""))

    if name == "calendar_add":
        if not registry.has("calendar_tool"):
            return "calendar 도구 미등록"
        return await registry.get("calendar_tool").add_event(
            _require(args, "title"),
            _require(args, "start"),
            int(args.get("duration_minutes", "60")),
            args.get("notes", ""),
            args.get("calendar_name", ""),
        )

    if name == "email_inbox":
        if not registry.has("email_tool"):
            return "email 도구 미등록"
        return registry.get("email_tool").list_inbox(int(args.get("n", "10")), args.get("unread_only", "") == "true")

    if name == "email_send":
        if not registry.has("email_tool"):
            return "email 도구 미등록"
        return registry.get("email_tool").send(_require(args, "to"), _require(args, "subject"), _require(args, "body"))

    if name == "convert_md_to_html":
        return registry.get("converter_tool").md_to_html(_require(args, "src"), args.get("dst", ""))
    if name == "convert_md_to_pdf":
        return registry.get("converter_tool").md_to_pdf(_require(args, "src"), args.get("dst", ""))
    if name == "convert_csv_to_chart":
        return registry.get("converter_tool").csv_to_chart(_require(args, "src"), args.get("dst", ""), args.get("x", ""), args.get("y", ""))
    if name == "image_resize":
        return registry.get("converter_tool").image_resize(_require(args, "src"), int(_require(args, "width")), args.get("dst", ""))

    if name == "speak":
        from interfaces.voice import tts_speak
        return await tts_speak(_require(args, "text"))

    if name == "remember":
        from core.profile import Profile
        text = _require(args, "fact")
        p = Profile.load()
        f = p.add(text, source="tool")
        return f"기억됨: [{f.id}] {f.text}"

    if name == "forget":
        from core.profile import Profile
        pattern = _require(args, "pattern")
        p = Profile.load()
        n = p.forget(pattern)
        return f"{n}개 fact 삭제됨"

    if name == "read_file":
        path = _require(args, "path")
        if not registry.has("file_reader"):
            return "file_reader 도구가 등록되어 있지 않음"
        content = registry.get("file_reader").read(path)
        return content[:8000]  # 과도한 컨텍스트 방지

    if name == "write_file":
        path = _require(args, "path")
        content = args.get("content", "")
        # 빈 content는 파일에 쓰지 않고 오류로 반환 — 기존 파일 덮어쓰기 방지
        if len(content.strip()) == 0:
            return (
                "⚠ ESCALATE_EMPTY_CONTENT: content 인자가 비어 있어 파일을 쓰지 않았습니다. "
                "같은 응답 내에 content를 실제 값으로 채워 다시 호출하세요."
            )
        result = registry.get("file_writer").write(path, content)
        if len(content.strip()) < 20 and path.endswith((".html", ".css", ".js", ".py", ".md")):
            return f"⚠ 경고: 매우 짧은 내용({len(content)}자)입니다. 의도한 것이 맞나요? 부족하면 다시 호출하세요.\n{result}"
        return result

    if name == "append_file":
        path = _require(args, "path")
        content = args.get("content", "")
        return registry.get("file_writer").append(path, content)

    if name == "delete_file":
        path = _require(args, "path")
        return registry.get("file_writer").delete(path)

    if name == "mkdir":
        path = _require(args, "path")
        return registry.get("file_writer").mkdir(path)

    if name == "execute":
        command = _require(args, "command")
        result = await registry.get("executor").run(command)
        if result.return_code == 0:
            return f"[exit 0]\n{result.stdout}".strip() or "[exit 0]"
        return f"[exit {result.return_code}]\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}".strip()

    if name == "python":
        code = _require(args, "code")
        result = await registry.get("executor").run_python(code)
        if result.return_code == 0:
            return f"[exit 0]\n{result.stdout}".strip() or "[exit 0]"
        return f"[exit {result.return_code}]\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}".strip()

    if name == "web_search":
        query = _require(args, "query")
        max_results = int(args.get("max_results", "5"))
        auto_fetch = int(args.get("auto_fetch", "2"))
        return await registry.get("web_search").summarize(
            query, max_results=max_results, auto_fetch=auto_fetch,
        )

    if name == "generate_image":
        prompt = _require(args, "prompt")
        neg = args.get("negative_prompt", "")
        size = args.get("size", "")
        backend = args.get("backend", "")
        result = await registry.get("image_gen").generate(prompt, neg, size, backend or None)
        if result.get("ok"):
            parts = [f"이미지 생성 완료 ({result.get('backend')}/{result.get('model')})"]
            parts.append(f"저장 경로: {result.get('path')}")
            if result.get("revised_prompt"):
                parts.append(f"수정된 프롬프트: {result['revised_prompt']}")
            return "\n".join(parts)
        return f"이미지 생성 실패: {result.get('error')}"

    raise ValueError(f"알 수 없는 도구: {name}")


def _require(args: dict, key: str) -> str:
    if key not in args:
        raise ValueError(f"필수 인자 누락: {key}")
    return args[key]


def format_results(results: list[ToolResult]) -> str:
    """도구 결과를 LLM에 돌려줄 텍스트로 포맷한다."""
    blocks: list[str] = []
    for r in results:
        marker = "ERROR" if r.error else "OK"
        blocks.append(
            f"<tool_result name=\"{r.name}\" status=\"{marker}\">\n{r.output}\n</tool_result>"
        )
    return "\n\n".join(blocks)
