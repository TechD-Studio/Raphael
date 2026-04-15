"""RAG 모듈 — ChromaDB 저장/검색, 컨텍스트 주입."""

from __future__ import annotations

from dataclasses import dataclass

import chromadb
from loguru import logger

from config.settings import get_settings
from core.model_router import ModelRouter
from memory.obsidian_loader import Document, ObsidianLoader


@dataclass
class SearchResult:
    """검색 결과 한 건."""

    content: str
    metadata: dict
    distance: float


class RAGManager:
    """ChromaDB 기반 RAG — 문서 인덱싱, 유사도 검색, 컨텍스트 주입."""

    COLLECTION_NAME = "obsidian_notes"

    def __init__(self, router: ModelRouter) -> None:
        settings = get_settings()
        db_path = settings["memory"]["chroma_db_path"]

        self.router = router
        self.client = chromadb.PersistentClient(path=db_path)
        self.collection = self.client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        self.loader = ObsidianLoader()
        logger.info(f"RAG 초기화 완료 (DB: {db_path}, 문서 수: {self.collection.count()})")

    # ── 인덱싱 ─────────────────────────────────────────────

    async def sync_vault(self) -> dict:
        """파일 mtime을 기준으로 증분 인덱싱을 수행한다.

        - 새 파일: 청크 추가
        - 수정된 파일(mtime 변경): 기존 청크 삭제 후 재삽입
        - 삭제된 파일: DB에서 해당 source의 청크 삭제
        - 변경 없는 파일: 건너뜀

        Returns: {"added": int, "updated": int, "deleted": int, "unchanged": int}
        """
        stats = {"added": 0, "updated": 0, "deleted": 0, "unchanged": 0}

        # 1) 볼트 스캔
        disk_files = {
            str(f.relative_to(self.loader.vault_path)): f.stat().st_mtime
            for f in self.loader.scan_files()
        }

        # 2) DB에 있는 (source → 최신 mtime) 수집
        db_sources: dict[str, float] = {}
        if self.collection.count() > 0:
            all_data = self.collection.get()
            for meta in all_data["metadatas"]:
                src = meta.get("source")
                mt = meta.get("mtime", 0)
                if src:
                    db_sources[src] = max(db_sources.get(src, 0), mt)

        # 3) 삭제된 파일 처리
        for src in list(db_sources.keys()):
            if src not in disk_files:
                self._delete_source(src)
                stats["deleted"] += 1

        # 4) 새/수정된 파일 처리
        new_docs = []
        for src, disk_mt in disk_files.items():
            db_mt = db_sources.get(src)
            if db_mt is None:
                # 새 파일
                file_path = self.loader.vault_path / src
                try:
                    docs = self.loader.load_file(file_path)
                    new_docs.extend(docs)
                    stats["added"] += 1
                except Exception as e:
                    logger.error(f"파일 로드 실패: {src} — {e}")
            elif disk_mt > db_mt + 0.001:  # 부동소수 여유
                # 수정된 파일
                self._delete_source(src)
                file_path = self.loader.vault_path / src
                try:
                    docs = self.loader.load_file(file_path)
                    new_docs.extend(docs)
                    stats["updated"] += 1
                except Exception as e:
                    logger.error(f"파일 로드 실패: {src} — {e}")
            else:
                stats["unchanged"] += 1

        if new_docs:
            await self._add_documents(new_docs)

        logger.info(
            f"RAG 동기화: +{stats['added']} /{stats['updated']} -{stats['deleted']} "
            f"(변경 없음 {stats['unchanged']})"
        )
        return stats

    def _delete_source(self, source: str) -> None:
        """특정 source의 모든 청크를 DB에서 삭제한다."""
        try:
            self.collection.delete(where={"source": source})
        except Exception as e:
            logger.warning(f"source 삭제 실패: {source} — {e}")

    async def _add_documents(self, docs: list[Document]) -> None:
        """Document 리스트를 임베딩 + 저장."""
        batch_size = 50
        for i in range(0, len(docs), batch_size):
            batch = docs[i : i + batch_size]
            embeddings = await self._embed_batch([d.content for d in batch])
            self.collection.add(
                ids=[d.id for d in batch],
                embeddings=embeddings,
                documents=[d.content for d in batch],
                metadatas=[d.metadata for d in batch],
            )

    async def index_vault(self, force: bool = False) -> int:
        """옵시디언 볼트 전체를 인덱싱한다.

        force=True면 기존 데이터를 삭제하고 재인덱싱한다.
        """
        if force:
            self.client.delete_collection(self.COLLECTION_NAME)
            self.collection = self.client.get_or_create_collection(
                name=self.COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info("기존 인덱스 삭제 완료")

        docs = self.loader.load_all()
        if not docs:
            logger.warning("인덱싱할 문서가 없습니다.")
            return 0

        # 이미 존재하는 ID 필터링
        existing_ids = set()
        if not force and self.collection.count() > 0:
            all_data = self.collection.get()
            existing_ids = set(all_data["ids"])

        new_docs = [d for d in docs if d.id not in existing_ids]
        if not new_docs:
            logger.info("모든 문서가 이미 인덱싱되어 있습니다.")
            return 0

        # 배치 단위로 임베딩 + 저장
        batch_size = 50
        indexed = 0
        for i in range(0, len(new_docs), batch_size):
            batch = new_docs[i : i + batch_size]
            embeddings = await self._embed_batch([d.content for d in batch])

            self.collection.add(
                ids=[d.id for d in batch],
                embeddings=embeddings,
                documents=[d.content for d in batch],
                metadatas=[d.metadata for d in batch],
            )
            indexed += len(batch)
            logger.debug(f"인덱싱 진행: {indexed}/{len(new_docs)}")

        logger.info(f"인덱싱 완료: 신규 {indexed}개 (전체 {self.collection.count()}개)")
        return indexed

    # ── 검색 ───────────────────────────────────────────────

    async def search(self, query: str, n_results: int = 5) -> list[SearchResult]:
        """쿼리와 유사한 문서를 검색한다."""
        if self.collection.count() == 0:
            logger.warning("인덱스가 비어 있습니다. 먼저 index_vault()를 실행하세요.")
            return []

        from core.model_router import ModelNotInstalledError
        try:
            query_embedding = await self.router.embed(query)
        except ModelNotInstalledError as e:
            logger.warning(str(e))
            return []

        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=min(n_results, self.collection.count()),
        )

        search_results: list[SearchResult] = []
        for i in range(len(results["ids"][0])):
            search_results.append(SearchResult(
                content=results["documents"][0][i],
                metadata=results["metadatas"][0][i],
                distance=results["distances"][0][i],
            ))

        logger.debug(f"검색 '{query[:40]}...' → {len(search_results)}건")
        return search_results

    # ── 컨텍스트 주입 ──────────────────────────────────────

    async def build_context(self, query: str, n_results: int = 3) -> str:
        """쿼리 관련 문서를 검색해 LLM 컨텍스트 문자열로 조합한다.

        검색 결과는 외부 문서이므로 명령어 인젝션 패턴을 정제한 뒤 주입한다.
        """
        from core.input_guard import sanitize_external_text

        results = await self.search(query, n_results)
        if not results:
            return ""

        parts: list[str] = []
        for i, r in enumerate(results, 1):
            source = r.metadata.get("source", "unknown")
            section = r.metadata.get("section", "")
            header = f"[{i}] {source}"
            if section:
                header += f" > {section}"
            safe_content = sanitize_external_text(r.content)
            parts.append(f"{header}\n{safe_content}")

        context = "\n\n---\n\n".join(parts)
        return f"<context>\n{context}\n</context>"

    # ── 상태 ───────────────────────────────────────────────

    def stats(self) -> dict:
        return {
            "collection": self.COLLECTION_NAME,
            "document_count": self.collection.count(),
            "vault_path": str(self.loader.vault_path),
        }

    # ── 내부 ───────────────────────────────────────────────

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """텍스트 리스트를 임베딩 벡터로 변환한다. 제한된 동시성으로 병렬 실행."""
        if not texts:
            return []

        import asyncio
        semaphore = asyncio.Semaphore(8)  # Ollama 동시 요청 수 제한

        async def _one(t: str) -> list[float]:
            async with semaphore:
                return await self.router.embed(t)

        return await asyncio.gather(*(_one(t) for t in texts))
