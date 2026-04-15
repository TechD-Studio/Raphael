"""파일 경로 샌드박스 — allowed_paths 외부 접근 차단.

settings.yaml 의 tools.file.allowed_paths 내에서만 읽기/쓰기/삭제를 허용한다.
allowed_paths가 비어있으면 제한 없음(기본 `~/`)으로 동작.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from config.settings import get_settings


class PathNotAllowedError(PermissionError):
    """허용되지 않은 경로 접근."""


def get_allowed_paths() -> list[Path]:
    """설정의 tools.file.allowed_paths를 Path 리스트로 반환한다 (~ 확장)."""
    settings = get_settings()
    raw = settings.get("tools", {}).get("file", {}).get("allowed_paths", []) or []
    paths = []
    for p in raw:
        if not p:
            continue
        try:
            paths.append(Path(p).expanduser().resolve())
        except Exception:
            logger.warning(f"잘못된 allowed_path: {p}")
    return paths


def _default_allowed() -> list[Path]:
    """allowed_paths가 비어있을 때 사용할 기본 허용 경로."""
    import os
    paths = [
        Path.home().resolve(),
        Path("/tmp").resolve(),
        Path("/var/folders").resolve(),
        Path(os.getcwd()).resolve(),  # 현재 작업 디렉토리
    ]
    return paths


def check_path(path: str) -> Path:
    """경로가 허용된 범위 내인지 검증하고 resolved Path를 반환한다.

    - 상대 경로는 현재 작업 디렉토리 기준으로 해석
    - allowed_paths가 비어있으면 홈/tmp/cwd 자동 허용
    - 심볼릭 링크는 resolve해서 실제 경로로 비교
    """
    try:
        p = Path(path).expanduser()
        # 상대 경로는 cwd 기준으로 절대화
        if not p.is_absolute():
            p = Path.cwd() / p
        resolved = p.resolve()
    except Exception as e:
        raise PathNotAllowedError(f"잘못된 경로: {path} ({e})")

    allowed = get_allowed_paths()
    if not allowed:
        allowed = _default_allowed()

    for base in allowed:
        try:
            resolved.relative_to(base)
            return resolved
        except ValueError:
            continue

    raise PathNotAllowedError(
        f"경로 '{path}' (→ {resolved})는 허용 범위 밖입니다.\n"
        f"허용 경로:\n  - " + "\n  - ".join(str(p) for p in allowed) + "\n\n"
        f"해결 방법:\n"
        f"  1. 웹 UI 설정 탭에서 '파일 접근 허용 경로'에 추가\n"
        f"  2. raphael onboard 재실행\n"
        f"  3. settings.yaml의 tools.file.allowed_paths에 직접 추가"
    )
