"""ContextVars for trace + stage propagation.

Why ContextVars instead of explicit arguments:
- The Anthropic client is constructed once in Pipeline.__init__ and shared
  across stages. Threading trace_id through every stage method's signature is
  noise.
- ContextVars are async-safe in Python 3.7+; each asyncio task sees its own
  copy. Concurrent pipeline runs do not bleed traces.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar

from prep_agent.obs.store import TraceStore

# None when no trace is active. Stages without an active trace skip logging
# rather than crash — useful for unit tests and ad-hoc invocations.
trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)
stage_var: ContextVar[str | None] = ContextVar("stage", default=None)


@asynccontextmanager
async def trace_context(
    store: TraceStore,
    label: str,
    kind: str = "research",
) -> AsyncIterator[str]:
    """Open a trace, set the ContextVar, close on exit (ok or error)."""
    trace_id = store.start_trace(label=label, kind=kind)
    token = trace_id_var.set(trace_id)
    try:
        yield trace_id
        store.end_trace(trace_id, status="ok")
    except Exception:
        store.end_trace(trace_id, status="error")
        raise
    finally:
        trace_id_var.reset(token)
