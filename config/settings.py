"""설정 로더 — settings.yaml + settings.local.yaml 병합, 환경변수 치환."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# 환경변수로 경로 오버라이드 가능 — 테스트 샌드박스에서 사용
# RAPHAEL_CONFIG_DIR: settings.yaml / settings.local.yaml 위치
# RAPHAEL_PROJECT_ROOT: .env 위치 (기본값 config_dir의 부모)
def _resolve_default_config_dir() -> Path:
    """PyInstaller 번들에서는 sys._MEIPASS/config 사용, 평소엔 패키지 디렉토리."""
    import sys as _sys
    if hasattr(_sys, "_MEIPASS"):
        return Path(_sys._MEIPASS) / "config"
    return Path(__file__).parent


def _resolve_override_config_dir(default: Path) -> Path:
    """오버라이드(settings.local.yaml, .env)가 기록될 영속 경로.

    프로즌 모드에서 _MEIPASS는 프로세스 종료 시 날아가므로 ~/.raphael/config로 라우팅.
    """
    import sys as _sys
    if hasattr(_sys, "_MEIPASS"):
        home_cfg = Path.home() / ".raphael" / "config"
        home_cfg.mkdir(parents=True, exist_ok=True)
        return home_cfg
    return default

_DEFAULT_CONFIG_DIR = _resolve_default_config_dir()
_CONFIG_DIR = Path(os.environ.get("RAPHAEL_CONFIG_DIR", _resolve_override_config_dir(_DEFAULT_CONFIG_DIR)))
_PROJECT_ROOT = Path(os.environ.get("RAPHAEL_PROJECT_ROOT", _CONFIG_DIR.parent))

# .env 로드
load_dotenv(_PROJECT_ROOT / ".env")


def _resolve_env_vars(obj: Any) -> Any:
    """문자열 내 ${VAR} 패턴을 환경변수 값으로 치환한다."""
    if isinstance(obj, str):
        return re.sub(
            r"\$\{(\w+)\}",
            lambda m: os.environ.get(m.group(1), m.group(0)),
            obj,
        )
    if isinstance(obj, dict):
        return {k: _resolve_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_env_vars(v) for v in obj]
    return obj


def _deep_merge(base: dict, override: dict) -> dict:
    """딕셔너리 깊은 병합. override가 base를 덮어쓴다."""
    merged = base.copy()
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_settings() -> dict:
    """settings.yaml을 읽고, settings.local.yaml이 있으면 병합한 뒤 환경변수를 치환해 반환한다.

    기본 settings.yaml은 항상 프로젝트 config 디렉토리에서 읽고,
    오버라이드는 _CONFIG_DIR(환경변수로 재설정 가능)에서 읽는다.
    """
    main_path = _DEFAULT_CONFIG_DIR / "settings.yaml"
    local_path = _local_yaml_path()

    with open(main_path, encoding="utf-8") as f:
        settings = yaml.safe_load(f)

    if local_path.exists():
        with open(local_path, encoding="utf-8") as f:
            local = yaml.safe_load(f) or {}
        settings = _deep_merge(settings, local)

    settings = _resolve_env_vars(settings)
    return settings


# 싱글톤 — 최초 import 시 한 번만 로드
_settings: dict | None = None


def get_settings() -> dict:
    """캐시된 설정을 반환한다."""
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def reload_settings() -> dict:
    """설정을 다시 로드한다 (런타임 설정 변경 시). .env도 함께 재로드."""
    global _settings
    # .env 파일도 다시 읽어 os.environ 업데이트
    load_dotenv(_PROJECT_ROOT / ".env", override=True)
    _settings = load_settings()
    return _settings


def get_ollama_base_url() -> str:
    """Ollama API base URL을 반환한다."""
    s = get_settings()
    host = s["models"]["ollama"]["host"]
    port = s["models"]["ollama"]["port"]
    return f"http://{host}:{port}"


def get_model_config(model_key: str | None = None) -> dict:
    """모델 키에 해당하는 설정을 반환한다. None이면 default 모델."""
    s = get_settings()
    key = model_key or s["models"]["default"]
    available = s["models"]["ollama"]["available"]
    if key not in available:
        raise ValueError(f"Unknown model key: {key}. Available: {list(available.keys())}")
    return {"key": key, **available[key]}


# ── 설정 쓰기 ──────────────────────────────────────────────


def _env_path() -> Path:
    return _PROJECT_ROOT / ".env"


def _local_yaml_path() -> Path:
    return _CONFIG_DIR / "settings.local.yaml"


# 뒷방 호환: 이전 코드에서 상수로 참조하던 경로
_ENV_PATH = _env_path()
_LOCAL_YAML_PATH = _local_yaml_path()


def rebind_paths(config_dir: Path | str | None = None, project_root: Path | str | None = None) -> None:
    """설정 경로를 런타임에 재바인딩한다 (테스트 샌드박스용).

    환경변수 RAPHAEL_CONFIG_DIR, RAPHAEL_PROJECT_ROOT를 설정하는 것과 동등.
    """
    global _CONFIG_DIR, _PROJECT_ROOT, _ENV_PATH, _LOCAL_YAML_PATH
    if config_dir is not None:
        _CONFIG_DIR = Path(config_dir)
        os.environ["RAPHAEL_CONFIG_DIR"] = str(_CONFIG_DIR)
    if project_root is not None:
        _PROJECT_ROOT = Path(project_root)
        os.environ["RAPHAEL_PROJECT_ROOT"] = str(_PROJECT_ROOT)
    _ENV_PATH = _env_path()
    _LOCAL_YAML_PATH = _local_yaml_path()
    load_dotenv(_ENV_PATH, override=True)
    reload_settings()


def save_local_settings(overrides: dict) -> None:
    """settings.local.yaml에 오버라이드 값을 저장한다.

    overrides는 settings.yaml과 동일한 구조의 부분 딕셔너리.
    기존 local 설정과 병합하여 저장한다.
    """
    local_path = _local_yaml_path()
    existing = {}
    if local_path.exists():
        with open(local_path, encoding="utf-8") as f:
            existing = yaml.safe_load(f) or {}

    merged = _deep_merge(existing, overrides)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    with open(local_path, "w", encoding="utf-8") as f:
        yaml.dump(merged, f, default_flow_style=False, allow_unicode=True)

    reload_settings()


def save_env(key: str, value: str) -> None:
    """.env 파일에 키=값을 저장/업데이트한다."""
    env_path = _env_path()
    lines: list[str] = []
    found = False

    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(f"{key}=") or line.strip() == key:
                lines.append(f"{key}={value}")
                found = True
            else:
                lines.append(line)

    if not found:
        lines.append(f"{key}={value}")

    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ[key] = value


def get_current_onboard_values() -> dict:
    """현재 onboard 관련 설정값들을 반환한다."""
    s = get_settings()
    return {
        "ollama_host": s["models"]["ollama"]["host"],
        "ollama_port": s["models"]["ollama"]["port"],
        "obsidian_vault": s["memory"]["obsidian_vault"],
        "telegram_token": os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        "discord_token": os.environ.get("DISCORD_BOT_TOKEN", ""),
        "allowed_paths": s.get("tools", {}).get("file", {}).get("allowed_paths", []) or [],
    }
