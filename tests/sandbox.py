"""테스트 샌드박스 — 격리된 임시 환경을 구축한다.

환경변수 RAPHAEL_CONFIG_DIR / RAPHAEL_PROJECT_ROOT를 임시 디렉토리로 설정해
settings 모듈이 프로덕션 경로를 건드리지 않도록 격리한다.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Sandbox:
    """격리된 테스트 환경.

    usage:
        with Sandbox.create() as sb:
            sb.write_note("welcome.md", "## Hi")
            ...
    """

    root: Path
    vault: Path
    chroma: Path
    logs: Path
    tasks_file: Path
    local_yaml: Path
    env_file: Path
    _saved_env: dict = field(default_factory=dict)

    # ── 컨텍스트 매니저 ─────────────────────────────────────

    def __enter__(self) -> "Sandbox":
        return self

    def __exit__(self, *a) -> None:
        self.cleanup()

    # ── 생성 / 정리 ──────────────────────────────────────────

    @classmethod
    def create(
        cls,
        ollama_host: str = "localhost",
        ollama_port: int = 11434,
        default_model: str = "gemma4-e4b",
    ) -> "Sandbox":
        root = Path(tempfile.mkdtemp(prefix="raphael_sandbox_"))
        vault = root / "vault"
        chroma = root / "chroma"
        logs = root / "logs"
        for d in (vault, chroma, logs):
            d.mkdir()

        tasks_file = root / "tasks.json"
        local_yaml = root / "settings.local.yaml"
        env_file = root / ".env"

        local_yaml.write_text(
            yaml.dump({
                "models": {
                    "default": default_model,
                    "ollama": {"host": ollama_host, "port": ollama_port},
                },
                "memory": {
                    "obsidian_vault": str(vault),
                    "chroma_db_path": str(chroma),
                },
                "tools": {
                    "file": {
                        # 테스트용: 샌드박스 root + 홈 + /tmp + /var/folders 접근 허용
                        "allowed_paths": [
                            str(root),
                            str(Path.home()),
                            "/tmp",
                            "/var/folders",
                            "/private",
                        ],
                    },
                    "executor": {
                        "sandbox": False,
                        "log_executions": True,
                        "log_path": str(logs / "exec.log"),
                        "timeout_seconds": 30,
                    },
                },
                "logging": {
                    "level": "WARNING",
                    "file": str(logs / "raphael.log"),
                },
            }, allow_unicode=True),
            encoding="utf-8",
        )
        env_file.write_text("TELEGRAM_BOT_TOKEN=\nDISCORD_BOT_TOKEN=\n", encoding="utf-8")

        sb = cls(
            root=root,
            vault=vault,
            chroma=chroma,
            logs=logs,
            tasks_file=tasks_file,
            local_yaml=local_yaml,
            env_file=env_file,
        )
        sb._install()
        return sb

    def cleanup(self) -> None:
        """샌드박스를 해제하고 원래 경로로 복원한다."""
        self._uninstall()
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)

    # ── 파일 유틸 ────────────────────────────────────────────

    def write_note(self, rel_path: str, content: str) -> Path:
        """볼트에 테스트 노트를 만든다."""
        p = self.vault / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    # ── 내부: 경로 재바인딩 ──────────────────────────────────

    def _install(self) -> None:
        """환경변수 + settings 모듈 rebind."""
        # 기존 환경변수 백업
        for key in ("RAPHAEL_CONFIG_DIR", "RAPHAEL_PROJECT_ROOT", "TELEGRAM_BOT_TOKEN", "DISCORD_BOT_TOKEN"):
            self._saved_env[key] = os.environ.get(key)

        # 경로 재바인딩
        os.environ["RAPHAEL_CONFIG_DIR"] = str(self.root)
        os.environ["RAPHAEL_PROJECT_ROOT"] = str(self.root)
        # 이전 테스트 값 제거
        for key in ("TELEGRAM_BOT_TOKEN", "DISCORD_BOT_TOKEN"):
            os.environ.pop(key, None)

        from config import settings as s
        s.rebind_paths(config_dir=self.root, project_root=self.root)

    def _uninstall(self) -> None:
        """환경변수 원복."""
        for key, val in self._saved_env.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val

        from config import settings as s
        s.rebind_paths(
            config_dir=self._saved_env.get("RAPHAEL_CONFIG_DIR") or s._DEFAULT_CONFIG_DIR,
            project_root=self._saved_env.get("RAPHAEL_PROJECT_ROOT") or s._DEFAULT_CONFIG_DIR.parent,
        )
