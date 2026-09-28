from __future__ import annotations

import asyncio
import sys

_configured = False


def configure_event_loop() -> None:
    """Выбирает реализацию цикла событий, совместимую с asyncpg. Идемпотентна."""
    global _configured
    if _configured or sys.platform != "win32":
        _configured = True
        return

    policy = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if policy is not None and not isinstance(asyncio.get_event_loop_policy(), policy):
        asyncio.set_event_loop_policy(policy())
    _configured = True
