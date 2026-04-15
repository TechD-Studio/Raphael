"""세션 대화를 별도 ChromaDB 컬렉션에 인덱싱.

`raphael cli session search "키워드"` 검색 가능.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import chromadb
from loguru import logger

from config.settings import get_settings
from core.model_router import ModelRouter
from core.session_store import Session, list_sessions, sessions_dir


@dataclass
class ConvHit:
    session_id: str
    role: str
    content: str
    distance: float


class ConversationIndex:
    COLLECTION = "conversations"

    def __init__(self, router: ModelRouter) -> None:
        self.router = router
        db_path = get_settings()["memory"]["chroma_db_path"]
        self.client = chromadb.PersistentClient(path=db_path)
        self.col = self.client.get_or_create_collection(
            name=self.COLLECTION, metadata={"hnsw:space": "cosine"}
        )

    @staticmethod
    def _id(session_id: str, idx: int, content: str) -> str:
        return hashlib.md5(f"{session_id}|{idx}|{content[:50]}".encode()).hexdigest()

    async def index_session(self, session_id: str) -> int:
        s = Session.load(session_id)
        if not s:
            return 0
        added = 0
        for i, m in enumerate(s.conversation):
            if m.get("role") not in ("user", "assistant"):
                continue
            content = m.get("content", "")
            if not content.strip():
                continue
            doc_id = self._id(session_id, i, content)
            existing = self.col.get(ids=[doc_id])
            if existing and existing.get("ids"):
                continue
            try:
                emb = await self.router.embed(content[:2000])
            except Exception as e:
                logger.warning(f"embed 실패: {e}")
                continue
            self.col.add(
                ids=[doc_id],
                embeddings=[emb],
                documents=[content[:2000]],
                metadatas=[{"session_id": session_id, "role": m["role"], "agent": s.agent}],
            )
            added += 1
        return added

    async def index_all(self) -> int:
        n = 0
        for s in list_sessions():
            n += await self.index_session(s["id"])
        return n

    async def search(self, query: str, n_results: int = 10) -> list[ConvHit]:
        if self.col.count() == 0:
            return []
        try:
            qe = await self.router.embed(query)
        except Exception as e:
            logger.warning(f"검색 embed 실패: {e}")
            return []
        r = self.col.query(query_embeddings=[qe], n_results=min(n_results, self.col.count()))
        hits = []
        for i in range(len(r["ids"][0])):
            md = r["metadatas"][0][i]
            hits.append(ConvHit(
                session_id=md.get("session_id", "?"),
                role=md.get("role", "?"),
                content=r["documents"][0][i],
                distance=r["distances"][0][i],
            ))
        return hits
