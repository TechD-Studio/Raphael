"""파일 리더 — txt, md, pdf, csv, 코드 파일 읽기."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from loguru import logger

from config.settings import get_settings
from tools.path_guard import check_path


class FileReader:
    """다양한 형식의 파일을 읽어 텍스트로 반환한다."""

    def __init__(self) -> None:
        settings = get_settings()
        tool_cfg = settings["tools"]["file"]
        self.max_size_mb = tool_cfg.get("max_file_size_mb", 50)
        self.supported_formats = set(tool_cfg.get("supported_formats", []))

    def read(self, path: str) -> str:
        """파일을 읽어 텍스트로 반환한다."""
        file_path = check_path(path)
        self._validate(file_path)

        ext = file_path.suffix.lower().lstrip(".")
        logger.debug(f"파일 읽기: {file_path} (형식: {ext})")

        if ext == "pdf":
            return self._read_pdf(file_path)
        elif ext == "csv":
            return self._read_csv(file_path)
        else:
            return self._read_text(file_path)

    def _validate(self, file_path: Path) -> None:
        if not file_path.exists():
            raise FileNotFoundError(f"파일이 존재하지 않습니다: {file_path}")

        ext = file_path.suffix.lower().lstrip(".")
        if self.supported_formats and ext not in self.supported_formats:
            raise ValueError(
                f"지원하지 않는 형식: .{ext} (지원: {self.supported_formats})"
            )

        size_mb = file_path.stat().st_size / (1024 * 1024)
        if size_mb > self.max_size_mb:
            raise ValueError(f"파일이 너무 큽니다: {size_mb:.1f}MB (최대: {self.max_size_mb}MB)")

    def _read_text(self, file_path: Path) -> str:
        return file_path.read_text(encoding="utf-8")

    def _read_pdf(self, file_path: Path) -> str:
        import pymupdf
        doc = pymupdf.open(str(file_path))
        pages = []
        for page in doc:
            pages.append(page.get_text())
        doc.close()
        return "\n\n".join(pages)

    def _read_csv(self, file_path: Path) -> str:
        text = file_path.read_text(encoding="utf-8")
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        if not rows:
            return ""
        # 테이블 형태로 반환
        lines = []
        for row in rows:
            lines.append(" | ".join(row))
        return "\n".join(lines)
