"""파일 라이터 — 파일 생성, 수정, 삭제. path_guard로 경로 제한."""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from core.checkpoint import create_checkpoint
from tools.path_guard import check_path


class FileWriter:
    """파일 생성/수정/삭제 도구 — allowed_paths 외부는 거부 + 체크포인트 자동 생성."""

    def write(self, path: str, content: str) -> str:
        file_path = check_path(path)
        try:
            create_checkpoint("write", str(file_path), note=f"size={len(content)}")
        except Exception as e:
            logger.debug(f"체크포인트 생성 실패(무시): {e}")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        logger.info(f"파일 쓰기: {file_path} ({len(content)} chars)")
        return f"파일 저장 완료: {file_path}"

    def append(self, path: str, content: str) -> str:
        file_path = check_path(path)
        if not file_path.exists():
            return self.write(path, content)
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"파일 추가: {file_path} (+{len(content)} chars)")
        return f"파일에 추가 완료: {file_path}"

    def delete(self, path: str) -> str:
        file_path = check_path(path)
        if not file_path.exists():
            return f"파일이 존재하지 않습니다: {file_path}"
        try:
            create_checkpoint("delete", str(file_path), note="before-delete")
        except Exception as e:
            logger.debug(f"체크포인트 생성 실패(무시): {e}")
        file_path.unlink()
        logger.info(f"파일 삭제: {file_path}")
        return f"파일 삭제 완료: {file_path}"

    def mkdir(self, path: str) -> str:
        dir_path = check_path(path)
        dir_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"디렉토리 생성: {dir_path}")
        return f"디렉토리 생성 완료: {dir_path}"
