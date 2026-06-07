"""@traced stage decorator.

Marks the entry/exit of a logical stage. Sets the `stage` ContextVar so any
LLM calls made inside the function are tagged with the right stage name.

Why a decorator rather than inline `with` blocks: stages are functions, not
arbitrary blocks. The decorator makes "this function is a stage" a single-word
declaration at the call site. Reads more like a contract than instrumentation.
"""
from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import TypeVar

from prep_agent.obs.context import stage_var

T = TypeVar("T")


def traced(stage: str) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    def decorator(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(fn)
        async def wrapper(*args: object, **kwargs: object) -> T:
            token = stage_var.set(stage)
            try:
                return await fn(*args, **kwargs)
            finally:
                stage_var.reset(token)

        return wrapper

    return decorator
