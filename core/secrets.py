"""시크릿 저장소 — OS Keychain 우선, fallback .env

macOS Keychain / Linux Secret Service / Windows Credential Manager 자동 사용.
keyring 라이브러리 설치 안되거나 백엔드 없으면 .env로 대체.
"""

from __future__ import annotations

import os

from loguru import logger

SERVICE_NAME = "raphael"


def _has_keyring() -> bool:
    try:
        import keyring  # noqa
        return True
    except Exception:
        return False


def get_secret(key: str) -> str | None:
    """OS keychain → 환경변수 순으로 조회."""
    if _has_keyring():
        try:
            import keyring
            v = keyring.get_password(SERVICE_NAME, key)
            if v:
                return v
        except Exception as e:
            logger.debug(f"keyring 조회 실패({key}): {e}")
    return os.environ.get(key)


def set_secret(key: str, value: str) -> str:
    """우선 keychain에 저장 시도, 실패 시 .env로 fallback. 사용된 backend 반환."""
    if _has_keyring():
        try:
            import keyring
            keyring.set_password(SERVICE_NAME, key, value)
            os.environ[key] = value  # 현재 프로세스에도 즉시 반영
            return "keychain"
        except Exception as e:
            logger.warning(f"keyring 저장 실패, .env로 fallback: {e}")
    # fallback
    from config.settings import save_env
    save_env(key, value)
    return ".env"


def delete_secret(key: str) -> bool:
    if _has_keyring():
        try:
            import keyring
            keyring.delete_password(SERVICE_NAME, key)
            os.environ.pop(key, None)
            return True
        except Exception as e:
            logger.debug(f"keyring 삭제 실패: {e}")
    return False
