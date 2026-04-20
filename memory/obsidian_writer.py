"""옵시디언 볼트 자동 저장 — 세션 대화를 마크다운 노트로 영속화.

사용자의 `memory.obsidian_vault` 설정에 지정된 볼트 경로 하위에 Raphael 세션 기록을
쌓는다. 턴마다 덮어쓰기 방식 — 세션 하나당 파일 하나, 세션이 계속되면 같은 파일이
계속 업데이트된다.

경로 레이아웃:
  {vault}/{prefix}/YYYY-MM/YYYYMMDD-HHMM_<제목>.md

기본 prefix: "Raphael". frontmatter의 session_id 로 세션 identity를 유지한다.

활성화 플래그:
  settings["memory"]["obsidian_auto_save"]["enabled"] (기본 False)
  settings["memory"]["obsidian_auto_save"]["prefix"] (기본 "Raphael")
  settings["memory"]["obsidian_auto_save"]["scope"] (기본 ["main"] — 이 에이전트만)
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from loguru import logger

from config.settings import get_settings


_FILENAME_BAD = re.compile(r"[^\w가-힣\s\-\.]+")
_MULTI_SPACE = re.compile(r"\s+")


def _sanitize_title(text: str, limit: int = 40) -> str:
    """첫 사용자 메시지에서 파일명 친화적 제목을 만든다."""
    # 첨부 placeholder 등 노이즈 제거
    text = re.sub(r"\[PDF 첨부:[^\]]*\]", "", text)
    text = re.sub(r"파일 경로:\s*/[^\s]+", "", text)
    text = re.sub(r"\(read_file 도구로[^\)]*\)", "", text)
    text = _FILENAME_BAD.sub(" ", text)
    text = _MULTI_SPACE.sub(" ", text).strip()
    if not text:
        return "세션"
    if len(text) > limit:
        text = text[:limit].rstrip()
    return text.replace(" ", "_")


def _session_created_at(conversation: list[dict]) -> datetime | None:
    """세션 첫 user 메시지 시각을 찾아 반환. 없으면 None."""
    for m in conversation:
        ts = m.get("ts")
        if ts and m.get("role") == "user":
            try:
                return datetime.fromtimestamp(float(ts))
            except Exception:
                pass
    return None


def _first_user_content(conversation: list[dict]) -> str:
    for m in conversation:
        if m.get("role") == "user":
            c = m.get("content", "")
            if c:
                return c
    return ""


def _summarize_tool_args(args: dict, max_value_len: int = 80) -> str:
    """도구 호출 인자를 짧게 요약해 한 줄로 반환."""
    parts = []
    for k, v in args.items():
        s = v if isinstance(v, str) else str(v)
        s = s.replace("\n", " ")
        if len(s) > max_value_len:
            s = s[: max_value_len - 1] + "…"
        parts.append(f"{k}={s}")
    return ", ".join(parts)


def _format_conversation(conversation: list[dict]) -> tuple[str, list[str], dict[str, int]]:
    """대화를 마크다운 본문으로 포맷. 사용된 도구 이름 모음과 카운트도 돌려준다."""
    lines: list[str] = []
    tool_names: list[str] = []
    tool_counts: dict[str, int] = {}

    for m in conversation:
        role = m.get("role")
        content = m.get("content", "") or ""
        if role == "system":
            # 카탈로그·현재시각 같은 프레임워크 system 메시지는 노트에 싣지 않는다.
            continue
        if role == "user":
            # 도구 결과 주입 메시지는 요약만.
            if content.startswith("<tool_results>"):
                tr = re.findall(
                    r'<tool_result\s+name="([^"]+)"\s+status="([^"]+)"[^>]*>([\s\S]*?)</tool_result>',
                    content,
                )
                for name, status, body in tr:
                    snippet = body.strip().replace("\n", " ")
                    if len(snippet) > 140:
                        snippet = snippet[:140] + "…"
                    lines.append(f"> **⟳ tool_result** `{name}` ({status}): {snippet}")
                continue
            # 실패 후 시스템 재시도 지시문 같은 것도 스킵
            if content.startswith("🚨 방금 write_file"):
                continue
            if content.startswith("방금 답변에 부족한 점이 발견"):
                continue
            lines.append(f"### 🧑 User\n\n{content.strip()}\n")
        elif role == "assistant":
            # 도구 호출 블록 분리
            tool_calls = re.findall(
                r'<tool\s+name="([^"]+)"\s*>([\s\S]*?)</tool>',
                content,
            )
            if tool_calls:
                for name, body in tool_calls:
                    tool_names.append(name)
                    tool_counts[name] = tool_counts.get(name, 0) + 1
                    # body에서 arg들 추출 (느슨하게 — 마지막 </arg> 누락 대비)
                    args: dict[str, str] = {}
                    for am in re.finditer(
                        r'<arg\s+name="([^"]+)"[^>]*>([\s\S]*?)(?:</arg>|(?=<arg\s)|$)',
                        body,
                    ):
                        args[am.group(1)] = am.group(2).strip()
                    lines.append(f"> **🔧 tool** `{name}` — {_summarize_tool_args(args)}")
            # 도구 태그 제거한 실제 응답 텍스트
            stripped = re.sub(
                r'<tool\s+name="[^"]+"\s*>[\s\S]*?</tool>',
                "",
                content,
            ).strip()
            if stripped:
                lines.append(f"### 🤖 Raphael\n\n{stripped}\n")

    return "\n".join(lines), tool_names, tool_counts


def _format_frontmatter(
    session_id: str,
    agent_name: str,
    created: datetime,
    updated: datetime,
    models: set[str],
    tool_counts: dict[str, int],
    attachments: list[str],
) -> str:
    """옵시디언 YAML frontmatter 생성."""
    lines = ["---"]
    lines.append(f"session_id: {session_id}")
    lines.append(f"created: {created.strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"updated: {updated.strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"agent: {agent_name}")
    if models:
        lines.append(f"models: [{', '.join(sorted(models))}]")
    # 태그
    tags = ["raphael/chat"]
    for tool_name in sorted(tool_counts.keys()):
        tags.append(f"tool/{tool_name}")
    lines.append(f"tags: [{', '.join(tags)}]")
    if tool_counts:
        total_tools = sum(tool_counts.values())
        tool_summary = ", ".join(f"{k}:{v}" for k, v in sorted(tool_counts.items()))
        lines.append(f"tool_counts: {{{tool_summary}}}")
        lines.append(f"tool_total: {total_tools}")
    if attachments:
        lines.append("attachments:")
        for a in attachments:
            lines.append(f"  - {a}")
    lines.append("---")
    return "\n".join(lines)


def _extract_attachments(conversation: list[dict]) -> list[str]:
    """user 메시지 내 '파일 경로: /...' 패턴을 attachments로 수집."""
    found = []
    for m in conversation:
        if m.get("role") != "user":
            continue
        c = m.get("content", "")
        for match in re.finditer(r"파일 경로:\s*(/[^\s\n)]+)", c):
            p = match.group(1)
            if p not in found:
                found.append(p)
    return found


def _session_models(conversation: list[dict]) -> set[str]:
    """metadata.model 또는 model 필드에서 사용된 모델들 추출."""
    out: set[str] = set()
    for m in conversation:
        for key in ("model",):
            v = m.get(key)
            if v:
                out.add(str(v))
        md = m.get("metadata") or {}
        v = md.get("model") if isinstance(md, dict) else None
        if v:
            out.add(str(v))
    return out


def is_enabled() -> bool:
    """자동 저장 활성화 여부."""
    settings = get_settings()
    mem = (settings.get("memory") or {})
    cfg = mem.get("obsidian_auto_save") or {}
    return bool(cfg.get("enabled"))


def is_scope_allowed(agent_name: str) -> bool:
    """이 에이전트에 대해 자동 저장을 수행해야 하는지."""
    settings = get_settings()
    mem = settings.get("memory") or {}
    cfg = mem.get("obsidian_auto_save") or {}
    scope = cfg.get("scope") or ["main"]
    return agent_name in scope


def _resolve_target_path(session_id: str, agent_name: str, conversation: list[dict]) -> Path | None:
    """세션 저장 파일의 절대 경로를 계산. 볼트 미설정 시 None."""
    settings = get_settings()
    mem = settings.get("memory") or {}
    vault = mem.get("obsidian_vault")
    if not vault:
        return None
    cfg = mem.get("obsidian_auto_save") or {}
    prefix = (cfg.get("prefix") or "Raphael").strip("/")

    created = _session_created_at(conversation) or datetime.now()
    title = _sanitize_title(_first_user_content(conversation))
    month_dir = created.strftime("%Y-%m")
    filename = f"{created.strftime('%Y%m%d-%H%M')}_{title}.md"

    root = Path(vault).expanduser()
    return root / prefix / month_dir / filename


def save_session(session_id: str, agent_name: str, conversation: list[dict]) -> Path | None:
    """현재 세션 대화를 옵시디언 볼트에 저장 (덮어쓰기).

    호출 측에서 활성화 여부·범위 체크 후 호출. 실패 시 로그만 남기고 예외 던지지 않음.
    """
    try:
        target = _resolve_target_path(session_id, agent_name, conversation)
        if target is None:
            logger.debug("obsidian 볼트 경로 미설정 — 자동 저장 스킵")
            return None

        body, tool_names, tool_counts = _format_conversation(conversation)
        if not body.strip():
            return None  # 아직 user 메시지도 없는 빈 세션

        created = _session_created_at(conversation) or datetime.now()
        updated = datetime.now()
        models = _session_models(conversation)
        attachments = _extract_attachments(conversation)

        frontmatter = _format_frontmatter(
            session_id=session_id,
            agent_name=agent_name,
            created=created,
            updated=updated,
            models=models,
            tool_counts=tool_counts,
            attachments=attachments,
        )
        content = f"{frontmatter}\n\n# {_first_user_content(conversation)[:80].strip()}\n\n{body}\n"

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        logger.debug(f"옵시디언 자동 저장: {target} ({len(content):,} bytes, 도구 {sum(tool_counts.values())}회)")
        return target
    except Exception as e:
        logger.warning(f"옵시디언 자동 저장 실패 (무시): {e}")
        return None
