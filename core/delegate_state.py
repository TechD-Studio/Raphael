"""delegate 위임 깊이 추적 (재귀 폭주 방지).

asyncio 컨텍스트별 카운터 — push/pop으로 관리.
"""

from __future__ import annotations

import contextvars

MAX_DEPTH = 3

_depth_var: contextvars.ContextVar[int] = contextvars.ContextVar("_raphael_delegate_depth", default=0)


def current_depth() -> int:
    return _depth_var.get()


def push_depth() -> None:
    _depth_var.set(_depth_var.get() + 1)


def pop_depth() -> None:
    _depth_var.set(max(0, _depth_var.get() - 1))
