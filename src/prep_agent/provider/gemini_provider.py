"""GeminiChatProvider — uses native response_schema for structured output.

google-genai is the unified Google AI SDK (supersedes google-generativeai).
The async surface is on `client.aio.*`. Structured output is native via
config.response_schema + config.response_mime_type='application/json'.

Retry policy: 5xx and 429 are transient (capacity/rate limits). 4xx-other
are user/config errors and should fail fast. Backoff is exponential with a
small jitter cap so concurrent processes don't synchronize their retries.
"""
from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from google import genai
from google.genai import errors as gerrors
from google.genai import types as gtypes
from pydantic import BaseModel

from prep_agent.obs.context import stage_var, trace_id_var
from prep_agent.obs.pricing import cost_usd
from prep_agent.obs.store import TraceStore

T = TypeVar("T", bound=BaseModel)

# Retry on these: 429 (rate limit), 5xx (service/capacity). 4xx others = user error.
_RETRYABLE_CODES = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 4
_BASE_DELAY_S = 2.0


class GeminiChatProvider:
    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str,
        trace_store: TraceStore,
    ) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._store = trace_store

    @property
    def model(self) -> str:
        return self._model

    async def chat_text(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 4096,
    ) -> str:
        t0 = time.monotonic()
        config = gtypes.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            # Gemini 2.5 "thinking" tokens come out of max_output_tokens.
            # For our synthesis call we have a generous budget, but a small
            # thinking budget keeps quality without burning a quarter of the
            # response budget on internal reasoning.
            thinking_config=gtypes.ThinkingConfig(thinking_budget=512),
        )
        try:
            resp = await _with_retry(
                lambda: self._client.aio.models.generate_content(
                    model=self._model, contents=user, config=config
                )
            )
        except Exception as e:
            self._log_error(t0, system, user, e)
            raise

        text: str = resp.text or ""
        self._log_from_resp(t0, resp, prompt_chars=len(system) + len(user),
                            response_chars=len(text))
        return text

    async def chat_structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        max_tokens: int = 2048,
    ) -> T:
        t0 = time.monotonic()
        config = gtypes.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            response_mime_type="application/json",
            response_schema=schema,
            # No thinking for structured output — the schema is the constraint;
            # thinking adds latency without quality wins.
            thinking_config=gtypes.ThinkingConfig(thinking_budget=0),
        )
        try:
            resp = await _with_retry(
                lambda: self._client.aio.models.generate_content(
                    model=self._model, contents=user, config=config
                )
            )
        except Exception as e:
            self._log_error(t0, system, user, e)
            raise

        # SDK's `parsed` field auto-validates against the schema when available.
        parsed: object | None = getattr(resp, "parsed", None)
        result: T
        if isinstance(parsed, schema):
            result = parsed
        else:
            # Fallback: validate from raw text.
            text = resp.text or ""
            if not text:
                raise RuntimeError(
                    f"Gemini returned empty body for {schema.__name__}"
                )
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as e:
                raise RuntimeError(
                    f"Gemini returned non-JSON for {schema.__name__}: {text[:200]}"
                ) from e
            result = schema.model_validate(payload)

        self._log_from_resp(
            t0, resp,
            prompt_chars=len(system) + len(user),
            response_chars=len(resp.text or ""),
        )
        return result

    # ---- tracing helpers ----

    def _log_from_resp(
        self,
        t0: float,
        resp: object,
        prompt_chars: int,
        response_chars: int,
    ) -> None:
        trace_id = trace_id_var.get()
        if trace_id is None:
            return
        usage = getattr(resp, "usage_metadata", None)
        input_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
        output_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)
        self._store.record_call(
            trace_id=trace_id,
            stage=stage_var.get() or "unknown",
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd(self._model, input_tokens, output_tokens),
            latency_ms=int((time.monotonic() - t0) * 1000),
            prompt_chars=prompt_chars,
            response_chars=response_chars,
        )

    def _log_error(self, t0: float, system: str, user: str, e: Exception) -> None:
        trace_id = trace_id_var.get()
        if trace_id is None:
            return
        self._store.record_call(
            trace_id=trace_id,
            stage=stage_var.get() or "unknown",
            model=self._model,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            latency_ms=int((time.monotonic() - t0) * 1000),
            prompt_chars=len(system) + len(user),
            response_chars=0,
            error=str(e),
        )


async def _with_retry[R](call: Callable[[], Awaitable[R]]) -> R:
    """Retry on transient Gemini errors with exponential backoff + jitter.

    Distinguishes retryable (429, 5xx) from terminal (other 4xx) by status
    code so a bad prompt doesn't wait 14s before failing.
    """
    last_exc: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            return await call()
        except gerrors.APIError as e:
            code = getattr(e, "code", None)
            if code not in _RETRYABLE_CODES or attempt == _MAX_ATTEMPTS - 1:
                raise
            last_exc = e
        # Backoff: 2s, 4s, 8s, plus 0-1s jitter to avoid thundering herd.
        delay = _BASE_DELAY_S * (2**attempt) + random.uniform(0, 1)
        await asyncio.sleep(delay)
    # Unreachable; satisfies typechecker.
    raise last_exc if last_exc else RuntimeError("retry loop exited unexpectedly")
