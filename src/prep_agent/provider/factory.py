"""Factory: build ChatProviders for the two stages from Settings.

Two providers (extract + synthesize) because they often use different models
and the project has historically routed them differently for cost reasons.
Both come from the same vendor — we don't mix providers across stages.
"""
from __future__ import annotations

from typing import cast

from prep_agent.config import Settings
from prep_agent.obs.store import TraceStore
from prep_agent.provider.anthropic_provider import AnthropicChatProvider
from prep_agent.provider.gemini_provider import GeminiChatProvider
from prep_agent.provider.types import ChatProvider


def make_provider(
    settings: Settings,
    model: str,
    trace_store: TraceStore,
) -> ChatProvider:
    if settings.llm_provider == "anthropic":
        return cast(
            ChatProvider,
            AnthropicChatProvider(
                api_key=settings.anthropic_api_key,
                model=model,
                trace_store=trace_store,
            ),
        )
    if settings.llm_provider == "gemini":
        return cast(
            ChatProvider,
            GeminiChatProvider(
                api_key=settings.gemini_api_key,
                model=model,
                trace_store=trace_store,
            ),
        )
    raise RuntimeError(f"Unknown llm_provider: {settings.llm_provider}")
