"""LLM pricing table.

Update when Anthropic changes prices. Computed at call time so the cost
attached to each LLM call reflects the price at the time of the call.

Prices are USD per million tokens, separated by input vs output.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPrice:
    input_per_mtok: float
    output_per_mtok: float


# Approximate published pricing. Tune as needed; if a model is missing we fall
# back to zero (so cost reports never crash, just under-report).
#
# Gemini entries are $0 because the free tier IS free. If you move to paid,
# update these to reflect the real prices on the day of the call.
_PRICES: dict[str, ModelPrice] = {
    # Anthropic
    "claude-sonnet-4-6": ModelPrice(input_per_mtok=3.0, output_per_mtok=15.0),
    "claude-sonnet-4-5": ModelPrice(input_per_mtok=3.0, output_per_mtok=15.0),
    "claude-opus-4-6": ModelPrice(input_per_mtok=15.0, output_per_mtok=75.0),
    "claude-opus-4-7": ModelPrice(input_per_mtok=15.0, output_per_mtok=75.0),
    "claude-haiku-4-5": ModelPrice(input_per_mtok=1.0, output_per_mtok=5.0),
    "claude-haiku-4-5-20251001": ModelPrice(input_per_mtok=1.0, output_per_mtok=5.0),
    # Gemini (free tier — $0; paid prices differ, update if you upgrade)
    "gemini-2.5-flash": ModelPrice(input_per_mtok=0.0, output_per_mtok=0.0),
    "gemini-2.5-pro": ModelPrice(input_per_mtok=0.0, output_per_mtok=0.0),
    "gemini-2.0-flash": ModelPrice(input_per_mtok=0.0, output_per_mtok=0.0),
    "gemini-2.0-flash-001": ModelPrice(input_per_mtok=0.0, output_per_mtok=0.0),
}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return USD cost for a single LLM call.

    Unknown models are billed at $0 — observability stays alive instead of
    crashing the call. Flag in logs by checking if the model is in `_PRICES`.
    """
    price = _PRICES.get(model)
    if price is None:
        return 0.0
    return (
        input_tokens * price.input_per_mtok / 1_000_000
        + output_tokens * price.output_per_mtok / 1_000_000
    )


def is_priced(model: str) -> bool:
    return model in _PRICES
