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
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
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


@asynccontextmanager
async def _lifespan(_: FastAPI):
    _init_runtime()
    yield


app = FastAPI(title="raphaeld", version="0.1.0", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:1420", "tauri://localhost", "http://tauri.localhost"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    active = load_active_agents()
    for d in list_definitions():
        if d.name not in active and d.name != "main":
            continue
        agent = GenericAgent.from_definition(d, router_inst, registry)
        orch_inst.register(agent)
    if "main" in {a.name for a in orch_inst._agents.values()}:
        orch_inst.set_default("main")
    return orch_inst


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
            if not isinstance(data, dict):
                continue
            convo = data.get("conversation", [])
            first_user = next(
                (m["content"] for m in convo if m.get("role") == "user"),
                "(빈 세션)",
            )
            out.append({
                "id": data.get("id") or p.stem,
                "agent": data.get("agent", ""),
                "title": (first_user or "(빈)")[:60],
                "turns": sum(1 for m in convo if m.get("role") == "user"),
                "mtime": p.stat().st_mtime,
                "tags": data.get("tags") or [],
            })
        except Exception as e:
            logger.debug(f"세션 읽기 실패 {p.name}: {e}")
    return out


@app.get("/sessions/{sid}")
def get_session(sid: str):
    s = Session.load(sid)
    if not s:
        raise HTTPException(404, "세션 없음")
    return {"id": s.id, "agent": s.agent, "conversation": s.conversation}


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
    s = Session.load(sid)
    if not s:
        raise HTTPException(404, "세션 없음")
    if fmt == "json":
        content = json.dumps(
            {"id": s.id, "agent": s.agent, "conversation": s.conversation},
            ensure_ascii=False,
            indent=2,
        )
        return {"format": "json", "content": content, "filename": f"{s.id}.json"}
    # markdown
    lines = [f"# Raphael 대화 — {s.id}\n"]
    for m in s.conversation:
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
        "filename": f"{s.id}.md",
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
    p = sessions_dir() / f"{sid}.json"
    if p.exists():
        p.unlink()
        return {"deleted": True}
    raise HTTPException(404, "세션 없음")


class MessageReq(BaseModel):
    content: str
    agent: str | None = None


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

    async def runner():
        try:
            response = await orch.route(
                req.content,
                agent_name=req.agent or sess.agent,
                source=InputSource.WEB_UI,
                session_id=sid,
                stream_tokens=True,
                activity_callback=on_event,
            )
            await queue.put({"type": "final", "data": {"text": response}})
        except Exception as e:
            await queue.put({"type": "error", "data": {"message": str(e)}})
        finally:
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


def _ab_results_dir() -> Path:
    return Path.home() / ".raphael" / "ab_results"


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


@app.get("/ab-results")
def list_ab_results():
    d = _ab_results_dir()
    if not d.exists():
        return []
    out = []
    for p in sorted(d.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            results = data.get("results", [])
            out.append({
                "file": p.name,
                "scenario_id": data.get("scenario_id"),
                "title": data.get("title", ""),
                "mtime": p.stat().st_mtime,
                "models": [r.get("model") for r in results],
                "success_count": sum(1 for r in results if r.get("success")),
                "total": len(results),
            })
        except Exception as e:
            logger.debug(f"ab-result 읽기 실패 {p.name}: {e}")
    return out


@app.get("/ab-results/{name}")
def get_ab_result(name: str):
    if "/" in name or ".." in name:
        raise HTTPException(400, "invalid name")
    p = _ab_results_dir() / name
    if not p.exists():
        raise HTTPException(404, "not found")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(500, f"parse error: {e}")


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


@cli.callback(invoke_without_command=True)
def serve(
    ctx: typer.Context,
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8765, "--port"),
):
    """로컬 데몬 시작."""
    if ctx.invoked_subcommand is not None:
        return
    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    cli()
