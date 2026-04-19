"""raphaeld — Tauri 데스크톱 앱이 sidecar로 띄우는 FastAPI 데몬.

엔드포인트 (모두 localhost):
- GET  /healthz
- GET  /sessions                — 저장된 세션 목록
- GET  /sessions/{id}           — 세션 대화 로드
- DELETE /sessions/{id}         — 세션 삭제
- POST /sessions/{id}/messages  — 메시지 전송 (스트리밍 SSE)
- GET  /agents                  — 활성 에이전트 목록
- GET  /models                  — 모델 목록
- POST /models/use              — 현재 모델 변경

기본 포트: 8765 (--port로 변경)
"""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

import typer
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pydantic import BaseModel

from core.input_guard import InputSource
from core.model_router import ModelRouter
from core.orchestrator import Orchestrator
from core.session_store import Session, sessions_dir
from core.agent_definitions import (
    AgentDefinition,
    install_defaults_if_empty, list_definitions, load_active_agents,
    get_definition, save_definition, delete_definition, set_enabled,
    get_recommendations,
    GenericAgent,
)
from tools.tool_registry import create_default_registry


def _cleanup_empty_sessions():
    """빈 세션 파일 자동 삭제."""
    d = sessions_dir()
    count = 0
    for p in list(d.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            convo = data if isinstance(data, list) else data.get("conversation", [])
            user_msgs = [m for m in convo if isinstance(m, dict) and m.get("role") == "user"]
            if not user_msgs:
                p.unlink()
                count += 1
        except Exception:
            pass
    if count:
        logger.info(f"빈 세션 {count}개 자동 삭제")


@asynccontextmanager
async def _lifespan(_: FastAPI):
    _init_runtime()
    _cleanup_empty_sessions()
    yield


app = FastAPI(title="raphaeld", version="0.1.0", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# React UI 정적 파일 서빙 — desktop/dist/ 가 있으면 마운트
_WEB_UI_DIR = Path(__file__).parent.parent / "desktop" / "dist"
if not _WEB_UI_DIR.exists():
    import sys as _sys
    if hasattr(_sys, "_MEIPASS"):
        _WEB_UI_DIR = Path(_sys._MEIPASS) / "web"

router_inst: ModelRouter | None = None
orch_inst: Orchestrator | None = None


def _init_runtime() -> Orchestrator:
    global router_inst, orch_inst
    if orch_inst is not None:
        return orch_inst
    install_defaults_if_empty()
    router_inst = ModelRouter()
    orch_inst = Orchestrator(router=router_inst)
    registry = create_default_registry()
    registry.register("_orchestrator", orch_inst, "내부 오케스트레이터 참조 (delegate용)")
    active = load_active_agents()
    for d in list_definitions():
        if d.name not in active and d.name != "main":
            continue
        agent = GenericAgent.from_definition(d, router_inst, registry)
        orch_inst.register(agent)
    if "main" in {a.name for a in orch_inst._agents.values()}:
        orch_inst.set_default("main")
    return orch_inst


@app.get("/")
def root_redirect():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/app")


@app.get("/healthz")
def healthz():
    return {"ok": True, "version": app.version}


@app.get("/sessions")
def list_sessions():
    files = sorted(sessions_dir().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for p in files:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, list):
                convo = data
                sid = p.stem.split("__")[0]
                agent = p.stem.split("__")[1] if "__" in p.stem else ""
                tags = []
            elif isinstance(data, dict):
                convo = data.get("conversation", [])
                sid = data.get("id") or p.stem.split("__")[0]
                agent = data.get("agent", p.stem.split("__")[1] if "__" in p.stem else "")
                tags = data.get("tags") or []
            else:
                continue
            first_user = next(
                (m["content"] for m in convo if isinstance(m, dict) and m.get("role") == "user"),
                "(빈 세션)",
            )
            turns = sum(1 for m in convo if isinstance(m, dict) and m.get("role") == "user")
            if turns == 0:
                continue
            out.append({
                "id": sid,
                "agent": agent,
                "title": (first_user or "(빈)")[:60],
                "turns": turns,
                "mtime": p.stat().st_mtime,
                "tags": tags,
            })
        except Exception as e:
            logger.debug(f"세션 읽기 실패 {p.name}: {e}")
    return out


@app.get("/sessions/{sid}")
def get_session(sid: str):
    s = Session.load(sid)
    if s:
        return {"id": s.id, "agent": s.agent, "conversation": s.conversation}
    for p in sessions_dir().glob(f"{sid}__*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            convo = data if isinstance(data, list) else data.get("conversation", [])
            agent = p.stem.split("__")[1] if "__" in p.stem else ""
            return {"id": sid, "agent": agent, "conversation": convo}
        except Exception:
            pass
    raise HTTPException(404, "세션 없음")


class SessionSearchReq(BaseModel):
    query: str
    n_results: int = 10


@app.post("/sessions/search")
async def search_sessions(req: SessionSearchReq):
    if not req.query.strip():
        raise HTTPException(400, "query required")
    orch = _init_runtime()
    try:
        from memory.conversation_index import ConversationIndex
    except Exception as e:
        raise HTTPException(500, f"ChromaDB unavailable: {e}")
    idx = ConversationIndex(orch.router)
    hits = await idx.search(req.query, n_results=req.n_results)
    return [
        {
            "session_id": h.session_id,
            "role": h.role,
            "content": h.content,
            "distance": h.distance,
        }
        for h in hits
    ]


@app.post("/sessions/reindex")
async def reindex_sessions():
    orch = _init_runtime()
    try:
        from memory.conversation_index import ConversationIndex
    except Exception as e:
        raise HTTPException(500, f"ChromaDB unavailable: {e}")
    idx = ConversationIndex(orch.router)
    n = await idx.index_all()
    return {"indexed": n}


@app.get("/sessions/{sid}/export")
def export_session(sid: str, fmt: str = "markdown"):
    convo = None
    agent = ""
    s = Session.load(sid)
    if s:
        convo = s.conversation
        agent = s.agent
    else:
        for p in sessions_dir().glob(f"{sid}__*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                convo = data if isinstance(data, list) else data.get("conversation", [])
                agent = p.stem.split("__")[1] if "__" in p.stem else ""
                break
            except Exception:
                pass
    if convo is None:
        raise HTTPException(404, "세션 없음")
    if fmt == "json":
        content = json.dumps(
            {"id": sid, "agent": agent, "conversation": convo},
            ensure_ascii=False,
            indent=2,
        )
        return {"format": "json", "content": content, "filename": f"{sid}.json"}
    # markdown
    lines = [f"# Raphael 대화 — {sid}\n"]
    for m in convo:
        role = m.get("role", "")
        content = m.get("content", "")
        if role == "user":
            lines.append(f"\n**User**\n\n{content}\n")
        elif role == "assistant":
            lines.append(f"\n**Raphael**\n\n{content}\n")
        elif role == "system":
            lines.append(f"\n_system: {content}_\n")
    return {
        "format": "markdown",
        "content": "\n".join(lines),
        "filename": f"{sid}.md",
    }


@app.get("/models/token-stats")
def token_stats():
    orch = _init_runtime()
    try:
        stats = orch.router.get_token_stats()
    except Exception as e:
        raise HTTPException(500, f"토큰 통계 오류: {e}")
    return stats or {}


@app.delete("/sessions/{sid}")
def delete_session(sid: str):
    d = sessions_dir()
    deleted = False
    for p in list(d.glob(f"{sid}*.json")):
        p.unlink()
        deleted = True
    if deleted:
        orch = _init_runtime()
        orch.reset_session(sid)
        return {"deleted": True}
    raise HTTPException(404, "세션 없음")


class SessionBulkDeleteReq(BaseModel):
    ids: list[str] = []
    all: bool = False


@app.post("/sessions/delete-bulk")
def delete_sessions_bulk(req: SessionBulkDeleteReq):
    d = sessions_dir()
    orch = _init_runtime()
    count = 0
    if req.all:
        for p in list(d.glob("*.json")):
            sid = p.stem.split("__")[0]
            orch.reset_session(sid)
            p.unlink()
            count += 1
    else:
        for sid in req.ids:
            orch.reset_session(sid)
            for p in list(d.glob(f"{sid}*.json")):
                p.unlink()
                count += 1
    return {"deleted": count}


class MessageReq(BaseModel):
    content: str
    agent: str | None = None
    images: list[str] = []  # data URLs (data:image/png;base64,...) or absolute file paths
    skill: str | None = None  # if set, prepend skill prompt as system addendum


_pending_approvals: dict[str, asyncio.Future] = {}


class ApprovalReq(BaseModel):
    approved: bool


@app.post("/approvals/{token}")
def resolve_approval(token: str, req: ApprovalReq):
    fut = _pending_approvals.get(token)
    if fut is None or fut.done():
        raise HTTPException(404, "no pending approval for that token")
    fut.set_result(bool(req.approved))
    return {"ok": True, "token": token, "approved": req.approved}


@app.post("/sessions/{sid}/messages")
async def post_message(sid: str, req: MessageReq):
    """메시지 전송 → SSE 스트림 (token_chunk + done)."""
    orch = _init_runtime()
    sess = Session.load(sid) or Session.new(req.agent or "main")
    if sid != sess.id:
        # 새로 생성 시 클라이언트 지정 sid 사용
        sess.id = sid

    queue: asyncio.Queue = asyncio.Queue()

    def on_event(ev: dict):
        try:
            queue.put_nowait(ev)
        except Exception:
            pass

    # ── 위험 도구 승인 콜백: SSE로 알림 + token 기반 future로 응답 대기 ──
    loop = asyncio.get_event_loop()

    async def approval_cb(tool_name: str, tool_args: dict) -> bool:
        import secrets

        token = secrets.token_urlsafe(8)
        fut: asyncio.Future = loop.create_future()
        _pending_approvals[token] = fut
        try:
            queue.put_nowait({
                "type": "approval_required",
                "data": {
                    "token": token,
                    "tool": tool_name,
                    "args": tool_args,
                    "timeout": 60,
                },
            })
            try:
                return await asyncio.wait_for(fut, timeout=60)
            except asyncio.TimeoutError:
                return False
        finally:
            _pending_approvals.pop(token, None)

    target_agent_name = req.agent or sess.agent
    try:
        target_agent = orch.get_agent(target_agent_name)
    except Exception:
        target_agent = None
    saved_cb = None
    if target_agent is not None:
        saved_cb = target_agent.approval_callback
        target_agent.approval_callback = approval_cb

    # Normalize images: data URLs → strip header, paths → kept as-is
    images_norm: list[str] = []
    for img in req.images or []:
        if not img:
            continue
        if img.startswith("data:"):
            # data:image/png;base64,XXXX → XXXX (ModelRouter accepts base64 string)
            if "," in img:
                images_norm.append(img.split(",", 1)[1])
            else:
                images_norm.append(img)
        else:
            images_norm.append(img)

    # Skill injection: prepend skill prompt to user content as guidance.
    user_content = req.content
    if req.skill:
        try:
            from core.skills import get_skill

            sk = get_skill(req.skill)
            if sk:
                user_content = (
                    f"[skill={sk.name}]\n{sk.prompt.strip()}\n\n---\n\n"
                    f"{req.content}"
                )
        except Exception as e:
            logger.warning(f"skill 적용 실패: {e}")

    async def runner():
        try:
            route_kwargs = dict(
                agent_name=req.agent or sess.agent,
                source=InputSource.WEB_UI,
                session_id=sid,
                stream_tokens=True,
                activity_callback=on_event,
            )
            if images_norm:
                route_kwargs["images"] = images_norm
            response = await orch.route(user_content, **route_kwargs)
            await queue.put({"type": "final", "data": {"text": response}})
        except Exception as e:
            await queue.put({"type": "error", "data": {"message": str(e)}})
        finally:
            # restore previous approval callback
            if target_agent is not None:
                target_agent.approval_callback = saved_cb
            await queue.put({"type": "done"})

    async def sse_gen():
        task = asyncio.create_task(runner())
        try:
            while True:
                ev = await queue.get()
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                if ev.get("type") == "done":
                    break
        finally:
            await task

    return StreamingResponse(sse_gen(), media_type="text/event-stream")


@app.get("/agents")
def list_agents():
    active = load_active_agents()
    return [
        {"name": d.name, "description": d.description, "active": d.name in active,
         "model": d.model, "tools": d.tools or "ALL"}
        for d in list_definitions()
    ]


@app.get("/agents/recommendations")
def agent_recommendations(limit: int = 3):
    recs = get_recommendations(load_active_agents(), limit=limit)
    return [{"name": n, "reason": r} for n, r in recs]


@app.get("/agents/{name}")
def get_agent(name: str):
    d = get_definition(name)
    if not d:
        raise HTTPException(404, "agent not found")
    active = load_active_agents()
    return {
        "name": d.name,
        "description": d.description,
        "model": d.model,
        "tools": d.tools,
        "system_prompt": d.system_prompt,
        "default_enabled": d.default_enabled,
        "active": d.name in active,
    }


class AgentUpsertReq(BaseModel):
    name: str
    description: str = ""
    model: str | None = None
    tools: list[str] = []
    system_prompt: str = ""
    default_enabled: bool = False
    active: bool | None = None


@app.post("/agents")
def upsert_agent(req: AgentUpsertReq):
    if not req.name.strip():
        raise HTTPException(400, "name required")
    d = AgentDefinition(
        name=req.name.strip(),
        description=req.description,
        model=req.model,
        tools=req.tools,
        system_prompt=req.system_prompt,
        default_enabled=req.default_enabled,
    )
    save_definition(d)
    if req.active is not None:
        set_enabled(d.name, req.active)
    global orch_inst
    orch_inst = None  # force re-init to pick up new persona
    return {"ok": True, "name": d.name}


@app.delete("/agents/{name}")
def remove_agent(name: str):
    if name == "main":
        raise HTTPException(400, "cannot delete main")
    ok = delete_definition(name)
    if not ok:
        raise HTTPException(404, "agent not found")
    global orch_inst
    orch_inst = None
    return {"deleted": True, "name": name}


class AgentToggleReq(BaseModel):
    active: bool


@app.post("/agents/{name}/toggle")
def toggle_agent(name: str, req: AgentToggleReq):
    if not get_definition(name):
        raise HTTPException(404, "agent not found")
    if name == "main" and not req.active:
        raise HTTPException(400, "cannot disable main")
    set_enabled(name, req.active)
    global orch_inst
    orch_inst = None
    return {"name": name, "active": req.active}


@app.get("/models")
def list_models():
    orch = _init_runtime()
    return {
        "current": orch.router.current_key,
        "available": list(orch.router.list_models().keys()),
    }




@app.get("/activity")
def activity_tail(tail: int = 200, session: str = ""):
    from core.activity_log import log_path

    p = log_path()
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    out = []
    for line in lines[-tail:]:
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except Exception:
            continue
        if session and e.get("session") != session:
            continue
        out.append(e)
    return out


@app.get("/audit")
def audit_show(tail: int = 200):
    from core import audit

    return audit.show(tail)


@app.get("/audit/verify")
def audit_verify():
    from core import audit

    ok, count, msg = audit.verify()
    return {"ok": ok, "count": count, "message": msg}


@app.get("/checkpoints")
def list_checkpoints_api(limit: int = 100):
    from core import checkpoint

    out = []
    for cp in checkpoint.list_checkpoints(limit=limit):
        out.append({
            "id": cp.id,
            "operation": cp.operation,
            "target": cp.target,
            "backup_path": cp.backup_path,
            "created": cp.created,
            "note": cp.note,
        })
    return out


class CheckpointRestoreReq(BaseModel):
    id: str


@app.post("/checkpoints/restore")
def restore_checkpoint_api(req: CheckpointRestoreReq):
    from core import checkpoint

    msg = checkpoint.restore(req.id)
    ok = "복원" in msg or "restored" in msg.lower() or msg.startswith("OK") or "없음" not in msg and "오류" not in msg
    return {"ok": ok, "message": msg}


class CheckpointCleanupReq(BaseModel):
    days: int = 7


@app.post("/checkpoints/cleanup")
def cleanup_checkpoints(req: CheckpointCleanupReq):
    from core import checkpoint

    n = checkpoint.cleanup_old(days=req.days)
    return {"deleted": n, "days": req.days}


def _failures_dir() -> Path:
    return Path.home() / ".raphael" / "failures"


@app.get("/failures")
def list_failures():
    d = _failures_dir()
    if not d.exists():
        return []
    out = []
    for p in sorted(d.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            out.append({
                "file": p.name,
                "agent": data.get("agent", ""),
                "model": data.get("model", ""),
                "reason": data.get("reason", ""),
                "user_input": (data.get("user_input") or "")[:200],
                "mtime": p.stat().st_mtime,
                "turns": len(data.get("conversation", [])),
            })
        except Exception as e:
            logger.debug(f"failure 읽기 실패 {p.name}: {e}")
    return out


@app.get("/failures/{name}")
def get_failure(name: str):
    if "/" in name or ".." in name:
        raise HTTPException(400, "invalid name")
    p = _failures_dir() / name
    if not p.exists():
        raise HTTPException(404, "not found")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(500, f"parse error: {e}")


@app.delete("/failures/{name}")
def delete_failure(name: str):
    if "/" in name or ".." in name:
        raise HTTPException(400, "invalid name")
    p = _failures_dir() / name
    if not p.exists():
        raise HTTPException(404, "not found")
    p.unlink()
    return {"deleted": True, "name": name}


@app.delete("/failures")
def clear_failures():
    d = _failures_dir()
    count = 0
    if d.exists():
        for p in d.glob("*.json"):
            p.unlink()
            count += 1
    return {"deleted": count}


@app.get("/rag/status")
def rag_status():
    from config.settings import get_settings

    s = get_settings()
    mem = s.get("memory") or {}
    vault = mem.get("obsidian_vault", "")
    try:
        from memory.rag import RAGManager

        orch = _init_runtime()
        rag = RAGManager(orch.router)
        return {
            "vault_path": vault,
            "doc_count": rag.collection.count(),
            "embedding_model": mem.get("embedding_model", ""),
            "chroma_db_path": mem.get("chroma_db_path", ""),
        }
    except Exception as e:
        return {
            "vault_path": vault,
            "doc_count": 0,
            "embedding_model": mem.get("embedding_model", ""),
            "chroma_db_path": mem.get("chroma_db_path", ""),
            "error": str(e),
        }


class RagVaultReq(BaseModel):
    vault_path: str


@app.post("/rag/vault")
def set_rag_vault(req: RagVaultReq):
    from config.settings import save_local_settings

    if not req.vault_path.strip():
        raise HTTPException(400, "vault_path required")
    save_local_settings({"memory": {"obsidian_vault": req.vault_path.strip()}})
    return {"ok": True, "vault_path": req.vault_path}


@app.post("/rag/sync")
async def rag_sync():
    try:
        from memory.rag import RAGManager
    except Exception as e:
        raise HTTPException(500, f"RAG 사용 불가: {e}")
    orch = _init_runtime()
    rag = RAGManager(orch.router)
    try:
        stats = await rag.sync_vault()
        return stats
    except Exception as e:
        raise HTTPException(500, f"sync 실패: {e}")


@app.post("/rag/reindex")
async def rag_reindex():
    try:
        from memory.rag import RAGManager
    except Exception as e:
        raise HTTPException(500, f"RAG 사용 불가: {e}")
    orch = _init_runtime()
    rag = RAGManager(orch.router)
    try:
        n = await rag.index_vault(force=True)
        return {"indexed": n}
    except Exception as e:
        raise HTTPException(500, f"reindex 실패: {e}")


@app.get("/settings/routing")
def get_routing():
    from core.router_strategy import load_config

    return load_config()


class RoutingReq(BaseModel):
    strategy: str
    rules: list[dict] = []


@app.post("/settings/routing")
def save_routing(req: RoutingReq):
    from core.router_strategy import save_config

    if req.strategy not in ("auto", "manual"):
        raise HTTPException(400, "strategy must be 'auto' or 'manual'")
    save_config(strategy=req.strategy, rules=req.rules)
    global router_inst, orch_inst
    router_inst = None
    orch_inst = None
    return {"ok": True, "strategy": req.strategy, "rules_count": len(req.rules)}


# ── 파인튜닝 ──────────────────────────────────────────────

@app.get("/finetune/check")
def finetune_check():
    from tools.finetune import FineTuneTool
    return FineTuneTool().check_deps()


class FtPrepareReq(BaseModel):
    vault_path: str
    method: str = "section_qa"


@app.post("/finetune/prepare")
def finetune_prepare(req: FtPrepareReq):
    from tools.finetune import FineTuneTool
    return FineTuneTool().prepare(req.vault_path, req.method)


class FtTrainReq(BaseModel):
    base_model: str = "mlx-community/gemma-4-E2B-it-4bit"
    iters: int = 600
    batch_size: int = 2
    lora_layers: int = 16
    learning_rate: float = 1e-4


@app.post("/finetune/train")
def finetune_train(req: FtTrainReq):
    from tools.finetune import FineTuneTool
    return FineTuneTool().train(
        base_model=req.base_model,
        iters=req.iters,
        batch_size=req.batch_size,
        lora_layers=req.lora_layers,
        learning_rate=req.learning_rate,
    )


class FtBuildReq(BaseModel):
    adapter_name: str
    model_name: str = ""


@app.post("/finetune/build")
def finetune_build(req: FtBuildReq):
    from tools.finetune import FineTuneTool
    return FineTuneTool().build(req.adapter_name, req.model_name)


@app.get("/finetune/models")
def finetune_models():
    from tools.finetune import FineTuneTool
    return FineTuneTool().list_models()


@app.delete("/finetune/{name}")
def finetune_delete(name: str):
    from tools.finetune import FineTuneTool
    return FineTuneTool().delete(name)


# ── 기억 시스템 ──────────────────────────────────────────

@app.get("/memory/daily-log")
def get_daily_log_api():
    from core.memory import get_daily_log, get_recent_logs
    return {"today": get_daily_log(), "recent": get_recent_logs(3)}


@app.get("/memory/context")
def get_context_api():
    from core.memory import get_project_context
    return {"text": get_project_context()}


class ContextReq(BaseModel):
    text: str


@app.post("/memory/context")
def save_context_api(req: ContextReq):
    from core.memory import update_project_context
    update_project_context(req.text)
    return {"ok": True}


@app.get("/memory/patterns")
def get_patterns_api():
    from core.memory import learn_from_feedback
    return {"text": learn_from_feedback()}


@app.get("/settings/custom-instructions")
def get_custom_instructions():
    from config.settings import get_settings
    return {"text": (get_settings().get("tools") or {}).get("custom_instructions", "")}


class CustomInstructionsReq(BaseModel):
    text: str


@app.post("/settings/custom-instructions")
def save_custom_instructions(req: CustomInstructionsReq):
    from config.settings import save_local_settings, reload_settings
    save_local_settings({"tools": {"custom_instructions": req.text}})
    reload_settings()
    return {"ok": True}


@app.get("/settings/escalation")
def get_escalation():
    from config.settings import get_settings

    s = get_settings()
    ladder = s.get("models", {}).get("escalation_ladder", [])
    available = list((s.get("models", {}).get("ollama", {}).get("available") or {}).keys())
    return {"ladder": ladder, "available": available}


class EscalationReq(BaseModel):
    ladder: list[str]


@app.post("/settings/escalation")
def save_escalation(req: EscalationReq):
    from config.settings import save_local_settings

    save_local_settings({"models": {"escalation_ladder": req.ladder}})
    global router_inst, orch_inst
    router_inst = None
    orch_inst = None
    return {"ok": True, "ladder": req.ladder}


@app.get("/hooks/watches")
def get_hook_watches():
    from config.settings import get_settings

    s = get_settings()
    return {"watches": (s.get("hooks") or {}).get("watches") or []}


class HookWatchesReq(BaseModel):
    watches: list[dict]


@app.post("/hooks/watches")
def save_hook_watches(req: HookWatchesReq):
    from config.settings import save_local_settings

    cleaned = []
    for w in req.watches:
        if not w.get("path"):
            raise HTTPException(400, "each watch needs 'path'")
        cleaned.append({
            "path": w["path"],
            "patterns": list(w.get("patterns") or []),
            "events": list(w.get("events") or ["modified", "created"]),
            "agent": w.get("agent", ""),
            "prompt": w.get("prompt", ""),
            "debounce_seconds": int(w.get("debounce_seconds", 3)),
        })
    save_local_settings({"hooks": {"watches": cleaned}})
    return {"ok": True, "count": len(cleaned)}


@app.get("/pool")
async def pool_status():
    from config.settings import get_settings

    s = get_settings()
    pool_cfg = (s.get("models") or {}).get("ollama_pool") or []
    try:
        from core.ollama_pool import OllamaPool

        pool = OllamaPool()
        health = await pool.health_all()
    except Exception as e:
        health = [{"error": str(e)}]
    return {"configured": pool_cfg, "health": health}


class PoolReq(BaseModel):
    servers: list[dict]


@app.post("/pool")
def save_pool(req: PoolReq):
    from config.settings import save_local_settings

    cleaned = []
    for srv in req.servers:
        if not srv.get("name") or not srv.get("host"):
            raise HTTPException(400, "name + host required for each server")
        cleaned.append({
            "name": srv["name"],
            "host": srv["host"],
            "port": int(srv.get("port", 11434)),
            "weight": int(srv.get("weight", 1)),
            "models": list(srv.get("models") or []),
            "timeout": int(srv.get("timeout", 120)),
        })
    save_local_settings({"models": {"ollama_pool": cleaned}})
    global router_inst, orch_inst
    router_inst = None
    orch_inst = None
    return {"ok": True, "count": len(cleaned)}


@app.get("/models/installed")
async def list_installed_models():
    """현재 설정된 ollama host에 실제 설치된 모델 목록 (Ollama /api/tags)."""
    import httpx
    from config.settings import get_ollama_base_url

    base = get_ollama_base_url()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{base}/api/tags")
            r.raise_for_status()
            data = r.json()
        return {
            "host": base,
            "models": [m["name"] for m in data.get("models", [])],
        }
    except Exception as e:
        return {"host": base, "models": [], "error": str(e)}


class ModelPullReq(BaseModel):
    name: str


@app.post("/models/pull")
async def pull_model(req: ModelPullReq):
    """ollama pull <name> 트리거 (전체 다운로드 완료까지 블로킹)."""
    import httpx
    from config.settings import get_ollama_base_url

    base = get_ollama_base_url()
    if not req.name.strip():
        raise HTTPException(400, "name required")
    try:
        async with httpx.AsyncClient(timeout=1800) as client:
            r = await client.post(
                f"{base}/api/pull",
                json={"name": req.name.strip(), "stream": False},
            )
            r.raise_for_status()
            return {"ok": True, "name": req.name, "result": r.json()}
    except Exception as e:
        raise HTTPException(500, f"pull failed: {e}")


@app.get("/profile")
def get_profile():
    from core.profile import Profile

    p = Profile.load()
    return {
        "facts": [
            {"id": f.id, "text": f.text, "added": f.added, "source": f.source}
            for f in p.facts
        ]
    }


class ProfileAddReq(BaseModel):
    text: str
    source: str = "user"


@app.post("/profile")
def add_profile_fact(req: ProfileAddReq):
    from core.profile import Profile

    p = Profile.load()
    try:
        f = p.add(req.text, source=req.source)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"id": f.id, "text": f.text, "added": f.added, "source": f.source}


@app.delete("/profile/{fact_id}")
def delete_profile_fact(fact_id: str):
    from core.profile import Profile

    p = Profile.load()
    before = len(p.facts)
    p.facts = [f for f in p.facts if f.id != fact_id]
    if len(p.facts) == before:
        raise HTTPException(404, "fact not found")
    p.save()
    return {"deleted": True, "id": fact_id}


@app.delete("/profile")
def clear_profile():
    from core.profile import Profile

    p = Profile.load()
    n = p.clear()
    return {"deleted": n}


class ConvertReq(BaseModel):
    operation: str  # md_to_html | md_to_pdf | csv_to_chart | image_resize
    src: str
    dst: str = ""
    x: str = ""
    y: str = ""
    width: int = 1024


@app.post("/convert")
def convert_file(req: ConvertReq):
    """파일 변환 도구 직접 호출."""
    try:
        from tools.converter_tool import ConverterTool
    except Exception as e:
        raise HTTPException(500, f"converter 사용 불가: {e}")
    tool = ConverterTool()
    try:
        if req.operation == "md_to_html":
            out = tool.md_to_html(req.src, req.dst)
        elif req.operation == "md_to_pdf":
            out = tool.md_to_pdf(req.src, req.dst)
        elif req.operation == "csv_to_chart":
            out = tool.csv_to_chart(req.src, req.dst, req.x, req.y)
        elif req.operation == "image_resize":
            out = tool.image_resize(req.src, req.width, req.dst)
        else:
            raise HTTPException(400, f"unknown operation: {req.operation}")
        return {"ok": True, "operation": req.operation, "output": str(out)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"변환 실패: {e}")


@app.post("/screenshot")
def take_screenshot():
    """OS 스크린샷을 캡처해 base64 PNG로 반환."""
    import base64
    import platform
    import subprocess
    import tempfile

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    try:
        sys_name = platform.system()
        if sys_name == "Darwin":
            r = subprocess.run(["screencapture", "-x", tmp.name], capture_output=True)
        elif sys_name == "Windows":
            # PowerShell .NET fallback
            ps = (
                "Add-Type -AssemblyName System.Windows.Forms;"
                "$b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds;"
                "$bmp=New-Object System.Drawing.Bitmap($b.Width,$b.Height);"
                "$g=[System.Drawing.Graphics]::FromImage($bmp);"
                "$g.CopyFromScreen(0,0,0,0,$bmp.Size);"
                f"$bmp.Save('{tmp.name}',[System.Drawing.Imaging.ImageFormat]::Png)"
            )
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps], capture_output=True
            )
        else:
            for cmd in (
                ["scrot", tmp.name],
                ["gnome-screenshot", "-f", tmp.name],
                ["import", "-window", "root", tmp.name],
            ):
                try:
                    r = subprocess.run(cmd, capture_output=True)
                    if r.returncode == 0:
                        break
                except FileNotFoundError:
                    continue
            else:
                raise HTTPException(500, "no screenshot tool found")
        if r.returncode != 0:
            raise HTTPException(500, f"screenshot failed: {r.stderr.decode(errors='replace')}")
        data = Path(tmp.name).read_bytes()
        b64 = base64.b64encode(data).decode("ascii")
        return {"data_url": f"data:image/png;base64,{b64}", "size": len(data)}
    finally:
        try:
            Path(tmp.name).unlink()
        except Exception:
            pass


@app.get("/file-preview")
def file_preview(path: str):
    """로컬 파일을 HTTP로 서빙 (이미지 프리뷰용). allowed_paths 검증."""
    from pathlib import Path as _P
    from fastapi.responses import FileResponse
    from tools.path_guard import check_path

    p = _P(path).expanduser().resolve()
    raphael_dir = _P.home() / ".raphael"
    if not str(p).startswith(str(raphael_dir)):
        try:
            check_path(str(p))
        except Exception:
            raise HTTPException(403, "path not allowed")
    if not p.exists():
        raise HTTPException(404, "file not found")
    suffix = p.suffix.lower()
    media = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
    }.get(suffix, "application/octet-stream")
    return FileResponse(str(p), media_type=media)


class ImageGenReq(BaseModel):
    prompt: str
    negative_prompt: str = ""
    size: str = ""
    backend: str = ""


@app.post("/image/generate")
async def generate_image_endpoint(req: ImageGenReq):
    from tools.image_gen import ImageGenTool

    tool = ImageGenTool()
    result = await tool.generate(
        prompt=req.prompt,
        negative_prompt=req.negative_prompt,
        size=req.size,
        backend=req.backend or None,
    )
    if result.get("ok") and result.get("path"):
        from pathlib import Path as _P
        p = _P(result["path"])
        if p.exists():
            import base64 as _b64
            b64 = _b64.b64encode(p.read_bytes()).decode("ascii")
            result["data_url"] = f"data:image/png;base64,{b64}"
    return result


@app.get("/image/backends")
def list_image_backends():
    from tools.image_gen import ImageGenTool

    return ImageGenTool().list_backends()


class ImageGenSettingsReq(BaseModel):
    backend: str = "auto"
    local_model: str = ""
    openai_model: str = ""
    default_size: str = ""


@app.get("/settings/image-gen")
def get_image_gen_settings():
    from config.settings import get_settings

    cfg = (get_settings().get("tools") or {}).get("image_gen") or {}
    return {
        "backend": cfg.get("backend", "auto"),
        "local_model": cfg.get("local_model", ""),
        "openai_model": cfg.get("openai_model", "dall-e-3"),
        "default_size": cfg.get("default_size", "1024x1024"),
    }


@app.post("/settings/image-gen")
def save_image_gen_settings(req: ImageGenSettingsReq):
    from config.settings import save_local_settings

    overrides: dict = {"tools": {"image_gen": {"backend": req.backend}}}
    if req.local_model:
        overrides["tools"]["image_gen"]["local_model"] = req.local_model
    if req.openai_model:
        overrides["tools"]["image_gen"]["openai_model"] = req.openai_model
    if req.default_size:
        overrides["tools"]["image_gen"]["default_size"] = req.default_size
    save_local_settings(overrides)
    return {"ok": True}


@app.post("/stt")
async def stt_endpoint(audio: UploadFile = File(...)):
    """업로드된 오디오를 텍스트로 변환 (whisper)."""
    import tempfile

    from interfaces.voice import stt_transcribe

    suffix = Path(audio.filename or "audio.webm").suffix or ".webm"
    data = await audio.read()
    if not data:
        raise HTTPException(400, "empty audio")
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        tmp.write(data)
        tmp.close()
        text = stt_transcribe(tmp.name)
        return {"text": text}
    finally:
        try:
            Path(tmp.name).unlink()
        except Exception:
            pass


class TtsReq(BaseModel):
    text: str


@app.post("/tts")
async def tts_endpoint(req: TtsReq):
    """텍스트를 OS TTS로 발화 (백그라운드)."""
    from interfaces.voice import tts_speak

    if not req.text.strip():
        return {"ok": False, "message": "empty text"}
    msg = await tts_speak(req.text)
    return {"ok": True, "message": msg}


@app.get("/mcp/servers")
def list_mcp_servers():
    from config.settings import get_settings

    s = get_settings()
    servers = (s.get("mcp") or {}).get("servers") or []
    # Try to get runtime-registered tools (registry keys: "mcp:<server>:<tool>")
    runtime_tools: list[dict] = []
    try:
        orch = _init_runtime()
        # registry is shared across agents
        reg = None
        for a in orch._agents.values():
            if getattr(a, "tool_registry", None) is not None:
                reg = a.tool_registry
                break
        if reg is not None:
            for entry in reg.list_tools():
                key = entry["name"]
                if key.startswith("mcp:"):
                    parts = key.split(":", 2)
                    if len(parts) == 3:
                        runtime_tools.append({
                            "server": parts[1],
                            "tool": parts[2],
                            "description": entry.get("description", ""),
                        })
    except Exception:
        pass
    return {
        "configured": servers,
        "runtime_tools": runtime_tools,
    }


class MCPCallReq(BaseModel):
    server: str
    tool: str
    args: dict = {}


_bot_processes: dict[str, object] = {}
BOT_COMMANDS = {"telegram", "discord", "slack"}


@app.get("/bots")
def list_bots():
    out = []
    for name in BOT_COMMANDS:
        p = _bot_processes.get(name)
        if p is not None:
            rc = getattr(p, "returncode", None)
            if rc is None and hasattr(p, "poll"):
                try:
                    p.poll()
                    rc = p.returncode
                except Exception:
                    rc = None
            running = rc is None
            out.append({
                "name": name,
                "running": running,
                "pid": getattr(p, "pid", None),
                "exit_code": rc,
            })
        else:
            out.append({"name": name, "running": False, "pid": None, "exit_code": None})
    return out


class BotStartReq(BaseModel):
    name: str


@app.post("/bots/start")
def start_bot(req: BotStartReq):
    import subprocess
    import sys

    if req.name not in BOT_COMMANDS:
        raise HTTPException(400, f"unknown bot: {req.name}")
    existing = _bot_processes.get(req.name)
    if existing is not None:
        try:
            existing.poll()
            if existing.returncode is None:
                raise HTTPException(409, f"{req.name} already running (pid={existing.pid})")
        except Exception:
            pass
    try:
        project_root = str(Path(__file__).resolve().parent.parent)
        p = subprocess.Popen(
            [sys.executable, "main.py", req.name],
            cwd=project_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _bot_processes[req.name] = p
        return {"ok": True, "name": req.name, "pid": p.pid}
    except Exception as e:
        raise HTTPException(500, f"start failed: {e}")


@app.post("/bots/stop")
def stop_bot(req: BotStartReq):
    if req.name not in BOT_COMMANDS:
        raise HTTPException(400, f"unknown bot: {req.name}")
    p = _bot_processes.get(req.name)
    if p is None:
        raise HTTPException(404, "not running")
    try:
        p.terminate()
        try:
            p.wait(timeout=5)
        except Exception:
            p.kill()
        _bot_processes.pop(req.name, None)
        return {"ok": True, "name": req.name}
    except Exception as e:
        raise HTTPException(500, f"stop failed: {e}")


@app.post("/mcp/call")
async def mcp_call_api(req: MCPCallReq):
    """MCP 도구 직접 호출 — 채팅을 거치지 않고 인자를 그대로 전달."""
    orch = _init_runtime()
    registry = None
    for a in orch._agents.values():
        if getattr(a, "tool_registry", None) is not None:
            registry = a.tool_registry
            break
    if registry is None:
        raise HTTPException(500, "registry unavailable")
    key = f"mcp:{req.server}:{req.tool}"
    if not registry.has(key):
        raise HTTPException(404, f"MCP tool not registered: {key}")
    proxy = registry.get(key)
    try:
        result = await proxy.call(req.args or {})
        return {"ok": True, "result": str(result)}
    except Exception as e:
        raise HTTPException(500, f"MCP call failed: {e}")


@app.get("/plugins")
def list_plugins():
    try:
        from importlib.metadata import entry_points

        try:
            tool_eps = list(entry_points(group="raphael.tools"))
            agent_eps = list(entry_points(group="raphael.agents"))
        except TypeError:  # py <3.10 fallback
            eps = entry_points()
            tool_eps = eps.get("raphael.tools", []) if hasattr(eps, "get") else []
            agent_eps = eps.get("raphael.agents", []) if hasattr(eps, "get") else []
        return {
            "tools": [{"name": ep.name, "value": ep.value} for ep in tool_eps],
            "agents": [{"name": ep.name, "value": ep.value} for ep in agent_eps],
        }
    except Exception as e:
        return {"tools": [], "agents": [], "error": str(e)}


@app.get("/metrics")
def prometheus_metrics():
    """daemon 내부에서 Prometheus-style 텍스트 메트릭 생성."""
    from fastapi.responses import PlainTextResponse

    orch = _init_runtime()
    try:
        stats = orch.router.get_token_stats() or {}
    except Exception:
        stats = {}
    lines: list[str] = []
    lines.append("# HELP raphael_model_calls Total model calls")
    lines.append("# TYPE raphael_model_calls counter")
    for model, s in stats.items():
        safe = model.replace('"', '\\"')
        lines.append(f'raphael_model_calls{{model="{safe}"}} {s.get("calls", 0)}')
    lines.append("# HELP raphael_model_tokens_prompt Prompt tokens used")
    lines.append("# TYPE raphael_model_tokens_prompt counter")
    for model, s in stats.items():
        safe = model.replace('"', '\\"')
        lines.append(f'raphael_model_tokens_prompt{{model="{safe}"}} {s.get("prompt", 0)}')
    lines.append("# HELP raphael_model_tokens_completion Completion tokens used")
    lines.append("# TYPE raphael_model_tokens_completion counter")
    for model, s in stats.items():
        safe = model.replace('"', '\\"')
        lines.append(f'raphael_model_tokens_completion{{model="{safe}"}} {s.get("completion", 0)}')
    lines.append("# HELP raphael_model_latency_ms Total model latency in ms")
    lines.append("# TYPE raphael_model_latency_ms counter")
    for model, s in stats.items():
        safe = model.replace('"', '\\"')
        lines.append(f'raphael_model_latency_ms{{model="{safe}"}} {s.get("total_ms", 0)}')
    return PlainTextResponse("\n".join(lines) + "\n")


@app.get("/health-panel")
async def health_panel():
    orch = _init_runtime()
    agents_list = [a.name for a in orch._agents.values()]
    try:
        stats = orch.router.get_token_stats() or {}
    except Exception:
        stats = {}
    total_tokens = sum(
        (s.get("prompt", 0) + s.get("completion", 0)) for s in stats.values()
    )
    total_calls = sum(s.get("calls", 0) for s in stats.values())

    ollama_ok = False
    try:
        health = await orch.router.health_check()
        ollama_ok = health.get("status") == "ok"
    except Exception:
        pass

    return {
        "ok": ollama_ok,
        "ollama_status": "ok" if ollama_ok else "unreachable",
        "agents": agents_list,
        "models_available": list(orch.router.list_models().keys()),
        "current_model": orch.router.current_key,
        "total_calls": total_calls,
        "total_tokens": total_tokens,
        "per_model": stats,
    }


@app.get("/feedback/stats")
def feedback_stats():
    from core import feedback

    return feedback.stats()


class FeedbackReq(BaseModel):
    session: str = ""
    agent: str = ""
    question: str = ""
    response: str = ""
    score: int  # +1 / -1 / 0
    comment: str = ""


@app.post("/feedback")
def feedback_record(req: FeedbackReq):
    from core import feedback

    feedback.record(
        session=req.session,
        agent=req.agent,
        question=req.question,
        response=req.response,
        score=req.score,
        comment=req.comment,
    )
    return {"ok": True}


@app.post("/system/update")
def system_update():
    import subprocess

    try:
        r1 = subprocess.run(
            ["git", "pull"],
            cwd=str(Path(__file__).resolve().parent.parent),
            capture_output=True,
            text=True,
            timeout=120,
        )
        pull_out = (r1.stdout or "") + (r1.stderr or "")
        if r1.returncode != 0:
            return {"ok": False, "stage": "git pull", "output": pull_out}
        r2 = subprocess.run(
            ["pip", "install", "-e", ".", "--quiet"],
            cwd=str(Path(__file__).resolve().parent.parent),
            capture_output=True,
            text=True,
            timeout=300,
        )
        pip_out = (r2.stdout or "") + (r2.stderr or "")
        return {
            "ok": r2.returncode == 0,
            "pull": pull_out.strip(),
            "pip": pip_out.strip(),
            "note": "앱 재시작이 필요할 수 있습니다.",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/skills")
def list_skills_api():
    from core.skills import list_skills

    return [
        {
            "name": s.name,
            "description": s.description,
            "agent": s.agent,
            "tags": s.tags,
        }
        for s in list_skills()
    ]


@app.get("/skills/{name}")
def get_skill_api(name: str):
    from core.skills import get_skill

    s = get_skill(name)
    if not s:
        raise HTTPException(404, "skill not found")
    return {
        "name": s.name,
        "description": s.description,
        "agent": s.agent,
        "tags": s.tags,
        "prompt": s.prompt,
    }


class SkillUpsertReq(BaseModel):
    name: str
    description: str = ""
    prompt: str
    agent: str = ""
    tags: list[str] = []


@app.post("/skills")
def upsert_skill_api(req: SkillUpsertReq):
    from core.skills import save_skill

    if not req.name.strip():
        raise HTTPException(400, "name required")
    save_skill(
        name=req.name.strip(),
        description=req.description,
        prompt=req.prompt,
        agent=req.agent,
        tags=req.tags,
    )
    return {"ok": True, "name": req.name}


@app.delete("/skills/{name}")
def delete_skill_api(name: str):
    from core.skills import delete_skill

    if not delete_skill(name):
        raise HTTPException(404, "skill not found")
    return {"deleted": True, "name": name}


@app.get("/settings/allowed-paths")
def get_allowed_paths_api():
    from config.settings import get_settings

    s = get_settings()
    paths = (s.get("tools") or {}).get("file", {}).get("allowed_paths", []) or []
    return {"allowed_paths": list(paths)}


class AllowedPathsReq(BaseModel):
    allowed_paths: list[str]


@app.post("/settings/allowed-paths")
def set_allowed_paths_api(req: AllowedPathsReq):
    from config.settings import save_local_settings

    paths = [p.strip() for p in req.allowed_paths if p.strip()]
    save_local_settings({"tools": {"file": {"allowed_paths": paths}}})
    return {"ok": True, "count": len(paths), "allowed_paths": paths}


@app.get("/secrets")
def list_secrets():
    """알려진 키 + .env 키를 조합하여 표시."""
    from pathlib import Path as _P

    known_keys: set[str] = set()
    known: list[dict] = []

    # Well-known keys
    for k in ["OPENAI_API_KEY", "HUGGINGFACE_TOKEN", "BRAVE_API_KEY", "TAVILY_API_KEY", "SERPER_API_KEY"]:
        known_keys.add(k)

    # .env files
    env = _P.home() / ".raphael" / ".env"
    project_env = Path.cwd() / ".env"
    for src_path, source in [(env, "user-env"), (project_env, "project-env")]:
        if src_path.exists():
            for line in src_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _ = line.split("=", 1)
                    known_keys.add(k.strip())

    try:
        from core.secrets import get_secret

        for k in sorted(known_keys):
            val = get_secret(k)
            if val:
                masked = val[:4] + "..." + val[-4:] if len(val) > 12 else "****"
                known.append({"key": k, "source": "keychain", "in_keychain": True, "masked": masked})
            else:
                known.append({"key": k, "source": "미설정", "in_keychain": False, "masked": ""})
    except Exception:
        for e in known:
            e["in_keychain"] = False

    return {"keys": known}


class SecretSetReq(BaseModel):
    key: str
    value: str


@app.post("/secrets")
def set_secret_api(req: SecretSetReq):
    from core.secrets import set_secret

    if not req.key.strip():
        raise HTTPException(400, "key required")
    backend = set_secret(req.key.strip(), req.value)
    return {"ok": True, "key": req.key, "backend": backend}


@app.delete("/secrets/{key}")
def delete_secret_api(key: str):
    from core.secrets import delete_secret

    ok = delete_secret(key)
    return {"deleted": ok, "key": key}


@app.get("/settings/server")
def get_server_settings():
    from config.settings import get_settings

    s = get_settings()
    o = (s.get("models") or {}).get("ollama") or {}
    return {
        "host": o.get("host", "localhost"),
        "port": int(o.get("port", 11434)),
        "timeout": int(o.get("timeout", 120)),
    }


class ServerSettingsReq(BaseModel):
    host: str
    port: int = 11434
    timeout: int = 120


@app.post("/settings/server")
def set_server_settings(req: ServerSettingsReq):
    from config.settings import save_local_settings

    if not req.host.strip():
        raise HTTPException(400, "host required")
    save_local_settings({
        "models": {
            "ollama": {
                "host": req.host.strip(),
                "port": req.port,
                "timeout": req.timeout,
            }
        }
    })
    global router_inst, orch_inst
    router_inst = None
    orch_inst = None  # force re-init with new base URL
    return {"ok": True, "host": req.host, "port": req.port, "timeout": req.timeout}


class ModelUseReq(BaseModel):
    key: str


@app.post("/models/use")
def use_model(req: ModelUseReq):
    orch = _init_runtime()
    orch.router.switch_model(req.key)
    return {"current": orch.router.current_key}


# ── CLI 진입 ──────────────────────────────────────────

cli = typer.Typer(help="Raphael 데몬 (Tauri 데스크톱 앱용)")


def _mount_web_ui():
    """React UI 정적 서빙 마운트 (API 라우트 등록 후 호출)."""
    if _WEB_UI_DIR.exists() and (_WEB_UI_DIR / "index.html").exists():
        from fastapi.responses import FileResponse

        @app.get("/app")
        async def web_ui_root():
            return FileResponse(str(_WEB_UI_DIR / "index.html"))

        @app.get("/app/{rest:path}")
        async def web_ui_catch(rest: str = ""):
            file_path = _WEB_UI_DIR / rest
            if file_path.is_file():
                return FileResponse(str(file_path))
            return FileResponse(str(_WEB_UI_DIR / "index.html"))

        @app.get("/{filename:path}")
        async def web_static_fallback(filename: str):
            """루트 레벨 정적 파일 (vite.svg 등)."""
            file_path = _WEB_UI_DIR / filename
            if file_path.is_file() and ".." not in filename:
                return FileResponse(str(file_path))
            raise HTTPException(404, "not found")

        app.mount("/assets", StaticFiles(directory=str(_WEB_UI_DIR / "assets")), name="web-assets")
        logger.info(f"Web UI: /app → {_WEB_UI_DIR}")


_mount_web_ui()


@cli.callback(invoke_without_command=True)
def serve(
    ctx: typer.Context,
    host: str = typer.Option("0.0.0.0", "--host"),
    port: int = typer.Option(8765, "--port"),
):
    """로컬 데몬 시작."""
    if ctx.invoked_subcommand is not None:
        return
    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    cli()
