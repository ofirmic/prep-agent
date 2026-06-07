"""AnthropicChatProvider — uses Claude tool-use for structured output."""
from __future__ import annotations

import time
from typing import TypeVar, cast

from anthropic import AsyncAnthropic
from anthropic.types import ToolParam
from pydantic import BaseModel

from prep_agent.obs.context import stage_var, trace_id_var
from prep_agent.obs.pricing import cost_usd
from prep_agent.obs.store import TraceStore

T = TypeVar("T", bound=BaseModel)


class AnthropicChatProvider:
    name = "anthropic"

    def __init__(
        self,
        api_key: str,
        model: str,
        trace_store: TraceStore,
    ) -> None:
        self._client = AsyncAnthropic(api_key=api_key)
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
        try:
            msg = await self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except Exception as e:
            self._log_error(t0, system, user, e)
            raise

        text = "".join(b.text for b in msg.content if b.type == "text")
        self._log(
            t0=t0,
            input_tokens=msg.usage.input_tokens,
            output_tokens=msg.usage.output_tokens,
            prompt_chars=len(system) + len(user),
            response_chars=len(text),
        )
        return text

    async def chat_structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        max_tokens: int = 2048,
    ) -> T:
        tool: ToolParam = cast(
            ToolParam,
            {
                "name": "record",
                "description": f"Record a structured {schema.__name__}.",
                "input_schema": schema.model_json_schema(),
            },
        )
        t0 = time.monotonic()
        try:
            msg = await self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=system,
                tools=[tool],
                tool_choice={"type": "tool", "name": "record"},
                messages=[{"role": "user", "content": user}],
            )
        except Exception as e:
            self._log_error(t0, system, user, e)
            raise

        for block in msg.content:
            if block.type == "tool_use" and block.name == "record":
                self._log(
                    t0=t0,
                    input_tokens=msg.usage.input_tokens,
                    output_tokens=msg.usage.output_tokens,
                    prompt_chars=len(system) + len(user),
                    response_chars=len(str(block.input)),
                )
                return schema.model_validate(block.input)
        raise RuntimeError(
            f"Anthropic did not return a tool_use block for {schema.__name__}"
        )

    # ---- tracing helpers ----

    def _log(
        self,
        *,
        t0: float,
        input_tokens: int,
        output_tokens: int,
        prompt_chars: int,
        response_chars: int,
    ) -> None:
        trace_id = trace_id_var.get()
        if trace_id is None:
            return
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
