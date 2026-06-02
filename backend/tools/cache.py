"""
Async TTL cache for external API clients.

Wraps an async function so identical calls within ``ttl_seconds`` return a
cached result instead of re-hitting the upstream API. Cache keys are derived
from the call arguments, so distinct queries are stored separately. Failed
calls are not cached.

The ``now`` callable is injectable so TTL behaviour is deterministically
testable without sleeping. The wrapper exposes ``cache_clear()`` for resetting
state (used to isolate tests).
"""

from __future__ import annotations

import functools
import time
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")

# External medical data (literature, trials, adverse-event reports) changes
# slowly, so a one-day window is a safe default for collapsing repeat queries.
DEFAULT_TTL_SECONDS = 60 * 60 * 24


def async_ttl_cache(
    ttl_seconds: float,
    now: Callable[[], float] = time.time,
):
    """
    Decorator factory: caches an async function's results for ``ttl_seconds``.

    Args:
        ttl_seconds: How long a cached result stays valid.
        now: Clock used to stamp and expire entries. Injectable for tests.
    """

    def decorator(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        store: dict[tuple, tuple[float, T]] = {}

        @functools.wraps(fn)
        async def wrapper(*args, **kwargs) -> T:
            key = (args, tuple(sorted(kwargs.items())))
            entry = store.get(key)
            if entry is not None and now() < entry[0]:
                return entry[1]

            value = await fn(*args, **kwargs)
            store[key] = (now() + ttl_seconds, value)
            return value

        wrapper.cache_clear = store.clear
        return wrapper

    return decorator
