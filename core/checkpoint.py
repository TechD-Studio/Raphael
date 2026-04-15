"""파일 작업 체크포인트 — write/delete 전 자동 백업, rollback 지원.

저장 위치: ~/.raphael/backups/<timestamp>__<hash>/
7일 이상 된 백업은 자동 정리.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from hashlib import md5
from pathlib import Path

from loguru import logger


def backups_dir() -> Path:
    p = os.environ.get("RAPHAEL_BACKUPS_DIR")
    if p:
        path = Path(p).expanduser()
    else:
        path = Path.home() / ".raphael" / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class Checkpoint:
    id: str
    operation: str       # "write" | "delete" | "append"
    target: str
    backup_path: str | None
    created: str
    note: str = ""

    def to_dict(self) -> dict:
        return self.__dict__


def _make_id(target: str) -> str:
    h = md5(target.encode()).hexdigest()[:6]
    return f"{int(time.time() * 1000)}__{h}"


def create_checkpoint(operation: str, target_path: str, note: str = "") -> Checkpoint:
    """파일 변경 전에 호출 — 기존 파일이 있으면 백업."""
    cid = _make_id(target_path)
    cp_dir = backups_dir() / cid
    cp_dir.mkdir(parents=True, exist_ok=True)

    target = Path(target_path).expanduser()
    backup_path: str | None = None
    if target.exists() and target.is_file():
        bp = cp_dir / target.name
        shutil.copy2(target, bp)
        backup_path = str(bp)

    cp = Checkpoint(
        id=cid,
        operation=operation,
        target=str(target.resolve() if target.exists() else target),
        backup_path=backup_path,
        created=datetime.now().isoformat(timespec="seconds"),
        note=note,
    )
    (cp_dir / "meta.json").write_text(
        json.dumps(cp.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return cp


def list_checkpoints(limit: int = 50) -> list[Checkpoint]:
    out = []
    dirs = sorted(backups_dir().glob("*__*"), key=lambda p: p.stat().st_mtime, reverse=True)
    for d in dirs[:limit]:
        meta = d / "meta.json"
        if not meta.exists():
            continue
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
            out.append(Checkpoint(**data))
        except Exception:
            continue
    return out


def restore(checkpoint_id: str) -> str:
    """백업된 파일을 원래 위치로 되돌린다."""
    cp_dir = backups_dir() / checkpoint_id
    meta = cp_dir / "meta.json"
    if not meta.exists():
        return f"체크포인트 없음: {checkpoint_id}"
    cp = Checkpoint(**json.loads(meta.read_text(encoding="utf-8")))
    if not cp.backup_path:
        return f"백업이 없는 체크포인트 (생성 전 파일 없음): {checkpoint_id}"
    target = Path(cp.target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(cp.backup_path, target)
    return f"복원됨: {target}"


def cleanup_old(days: int = 7) -> int:
    """오래된 체크포인트 삭제."""
    threshold = datetime.now() - timedelta(days=days)
    removed = 0
    for d in backups_dir().glob("*__*"):
        if datetime.fromtimestamp(d.stat().st_mtime) < threshold:
            shutil.rmtree(d, ignore_errors=True)
            removed += 1
    return removed
