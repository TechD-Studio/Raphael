"""옵시디언 볼트 로더 — MD 파일 파싱, 청킹, ChromaDB 인덱싱."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from config.settings import get_settings


@dataclass
class Document:
    """파싱된 문서 청크 하나."""

    id: str
    content: str
    metadata: dict = field(default_factory=dict)


class ObsidianLoader:
    """옵시디언 볼트에서 마크다운 파일을 읽고 청크로 분할한다."""

    def __init__(
        self,
        vault_path: str | None = None,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
    ) -> None:
        settings = get_settings()
        self.vault_path = Path(vault_path or settings["memory"]["obsidian_vault"]).expanduser()
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    # ── 볼트 스캔 ──────────────────────────────────────────

    def scan_files(self) -> list[Path]:
        """볼트 내 모든 .md 파일을 반환한다."""
        if not self.vault_path.exists():
            logger.warning(f"볼트 경로가 존재하지 않습니다: {self.vault_path}")
            return []
        files = sorted(self.vault_path.rglob("*.md"))
        logger.info(f"볼트 스캔 완료: {len(files)}개 파일 발견")
        return files

    # ── 파일 파싱 ──────────────────────────────────────────

    def parse_file(self, file_path: Path) -> dict:
        """마크다운 파일을 읽고 프론트매터와 본문을 분리한다."""
        text = file_path.read_text(encoding="utf-8")
        frontmatter = {}
        body = text

        # YAML 프론트매터 추출
        fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
        if fm_match:
            import yaml
            try:
                frontmatter = yaml.safe_load(fm_match.group(1)) or {}
            except yaml.YAMLError:
                pass
            body = text[fm_match.end():]

        # 옵시디언 링크 [[...]] → 텍스트만 추출
        body = re.sub(r"\[\[([^|\]]+)\|([^\]]+)\]\]", r"\2", body)
        body = re.sub(r"\[\[([^\]]+)\]\]", r"\1", body)

        rel_path = str(file_path.relative_to(self.vault_path))
        return {
            "path": rel_path,
            "title": file_path.stem,
            "frontmatter": frontmatter,
            "body": body.strip(),
        }

    # ── 청킹 ──────────────────────────────────────────────

    def chunk_text(self, text: str, source_path: str, title: str) -> list[Document]:
        """텍스트를 헤딩 기반 + 크기 기반으로 청크 분할한다."""
        if not text.strip():
            return []

        # 1차: 헤딩(##) 기준으로 섹션 분리
        sections = self._split_by_headings(text)

        # 2차: 큰 섹션은 크기 기반으로 추가 분할
        chunks: list[Document] = []
        for section_title, section_body in sections:
            if len(section_body) <= self.chunk_size:
                doc_id = self._make_id(source_path, section_title, section_body)
                chunks.append(Document(
                    id=doc_id,
                    content=section_body,
                    metadata={
                        "source": source_path,
                        "title": title,
                        "section": section_title,
                    },
                ))
            else:
                sub_chunks = self._split_by_size(section_body)
                for i, sub in enumerate(sub_chunks):
                    doc_id = self._make_id(source_path, section_title, sub)
                    chunks.append(Document(
                        id=doc_id,
                        content=sub,
                        metadata={
                            "source": source_path,
                            "title": title,
                            "section": section_title,
                            "chunk_index": i,
                        },
                    ))

        return chunks

    def _split_by_headings(self, text: str) -> list[tuple[str, str]]:
        """마크다운 헤딩 기준으로 (제목, 본문) 쌍 리스트를 반환한다."""
        parts = re.split(r"^(#{1,6}\s+.+)$", text, flags=re.MULTILINE)
        sections: list[tuple[str, str]] = []
        current_heading = ""

        for part in parts:
            stripped = part.strip()
            if re.match(r"^#{1,6}\s+", stripped):
                current_heading = re.sub(r"^#+\s*", "", stripped)
            elif stripped:
                sections.append((current_heading, stripped))

        if not sections and text.strip():
            sections.append(("", text.strip()))

        return sections

    def _split_by_size(self, text: str) -> list[str]:
        """텍스트를 chunk_size 기준으로 문단 단위 분할한다."""
        paragraphs = text.split("\n\n")
        chunks: list[str] = []
        current = ""

        for para in paragraphs:
            if len(current) + len(para) + 2 > self.chunk_size and current:
                chunks.append(current.strip())
                # overlap: 이전 청크 끝부분 유지
                overlap_text = current[-self.chunk_overlap:] if self.chunk_overlap else ""
                current = overlap_text + para
            else:
                current = current + "\n\n" + para if current else para

        if current.strip():
            chunks.append(current.strip())

        return chunks

    @staticmethod
    def _make_id(source: str, section: str, content: str) -> str:
        """청크 고유 ID 생성."""
        raw = f"{source}::{section}::{content[:100]}"
        return hashlib.md5(raw.encode()).hexdigest()

    # ── 전체 로드 ──────────────────────────────────────────

    def load_all(self) -> list[Document]:
        """볼트 전체를 스캔하고 청크로 분할해 반환한다.

        각 Document의 metadata에 'mtime'(float, 파일 수정 시각)이 포함된다.
        """
        files = self.scan_files()
        all_docs: list[Document] = []

        for f in files:
            try:
                mtime = f.stat().st_mtime
                parsed = self.parse_file(f)
                docs = self.chunk_text(parsed["body"], parsed["path"], parsed["title"])
                for d in docs:
                    d.metadata["mtime"] = mtime
                all_docs.extend(docs)
            except Exception as e:
                logger.error(f"파일 처리 실패: {f} — {e}")

        logger.info(f"총 {len(all_docs)}개 청크 생성 (파일 {len(files)}개)")
        return all_docs

    def load_file(self, file_path: Path) -> list[Document]:
        """특정 파일 하나만 파싱해 청크 리스트를 반환한다."""
        mtime = file_path.stat().st_mtime
        parsed = self.parse_file(file_path)
        docs = self.chunk_text(parsed["body"], parsed["path"], parsed["title"])
        for d in docs:
            d.metadata["mtime"] = mtime
        return docs
