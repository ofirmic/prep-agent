"""Provider-agnostic chat interface.

Why a Protocol over inheritance:
- Lets AnthropicChatProvider and GeminiChatProvider live as completely
  independent files with no shared base class to constrain them.
- Mypy verifies the shape; nothing else does, and that's fine.

Two methods, both async:
- chat_text       — free-form response, returns the text.
- chat_structured — schema-bound response, returns a validated pydantic model.

The structured method handles the per-provider plumbing differently:
- Anthropic: tool-use with a forced tool whose input_schema is the pydantic
  model's JSON schema. Validated from the tool_use block.
- Gemini: native response_schema + response_mime_type='application/json'.

Both implementations read trace_id_var + stage_var from ContextVars and write
to the same TraceStore, so the observability layer doesn't care which provider
is on the other end.
"""
from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class ChatProvider(Protocol):
    """Two-method chat interface used by every stage in the pipeline."""

    @property
    def name(self) -> str:
        """e.g. 'anthropic' or 'gemini' — used in trace records."""
        ...

    @property
    def model(self) -> str:
        """The active model name, e.g. 'gemini-2.5-flash'."""
        ...

    async def chat_text(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 4096,
    ) -> str:
        """Return the generated text. Used for synthesis (free-form output)."""
        ...

    async def chat_structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        max_tokens: int = 2048,
    ) -> T:
        """Return a validated instance of `schema`.

        The provider is responsible for whatever per-provider trick it takes
        (tool use, JSON mode, response_schema) to make the model output match.
        """
        ...
