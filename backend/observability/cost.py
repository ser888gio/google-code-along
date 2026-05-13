"""Gemini pricing table and per-call cost calculator.

Prices are in USD per 1M tokens as of May 2026.
Source: https://ai.google.dev/pricing

Usage:
    from observability.cost import compute_cost
    usd = compute_cost(model, usage_metadata)
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Pricing table — USD per 1M tokens
# Prompts > 200K tokens use the "long" tier for models that distinguish.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ModelPrice:
    input_short: float  # input tokens, context ≤ 200K
    input_long: float  # input tokens, context > 200K
    output: float  # output tokens
    cache_read: float = 0.0  # cached input tokens (context cache hit)
    cache_write: float = 0.0  # cached input tokens (context cache write)


# Key: model ID prefix (matched with startswith so minor version suffixes work)
_PRICES: dict[str, _ModelPrice] = {
    # Gemini 2.5 Pro
    "gemini-2.5-pro": _ModelPrice(
        input_short=1.25,
        input_long=2.50,
        output=10.00,
        cache_read=0.31,
        cache_write=4.50,
    ),
    # Gemini 2.5 Flash
    "gemini-2.5-flash": _ModelPrice(
        input_short=0.15,
        input_long=0.15,
        output=0.60,
        cache_read=0.0375,
        cache_write=1.00,
    ),
    # Gemini 3.1 Pro (placeholder — update when pricing is published)
    "gemini-3.1-pro": _ModelPrice(
        input_short=1.25,
        input_long=2.50,
        output=10.00,
        cache_read=0.31,
        cache_write=4.50,
    ),
    # Gemini 3.1 Flash
    "gemini-3.1-flash": _ModelPrice(
        input_short=0.15,
        input_long=0.15,
        output=0.60,
        cache_read=0.0375,
        cache_write=1.00,
    ),
    # Gemini 2.0 Flash (Live API)
    "gemini-2.0-flash": _ModelPrice(
        input_short=0.10,
        input_long=0.10,
        output=0.40,
        cache_read=0.025,
    ),
}

_PER_MILLION = 1_000_000
_LONG_CONTEXT_THRESHOLD = 200_000


def _lookup_price(model: str) -> _ModelPrice | None:
    for prefix, price in _PRICES.items():
        if model.startswith(prefix):
            return price
    return None


def compute_cost(model: str, usage_metadata) -> float:
    """Return the estimated USD cost of one generate_content call.

    Args:
        model:          Model ID string (e.g. "gemini-2.5-pro-preview-05-06").
        usage_metadata: google.genai UsageMetadata object (or any object with
                        prompt_token_count / candidates_token_count /
                        cached_content_token_count attributes).

    Returns:
        Estimated cost in USD. Returns 0.0 when the model is unknown or usage
        metadata is missing — never raises.
    """
    try:
        price = _lookup_price(model)
        if price is None:
            return 0.0

        input_tokens: int = getattr(usage_metadata, "prompt_token_count", 0) or 0
        output_tokens: int = getattr(usage_metadata, "candidates_token_count", 0) or 0
        cache_read_tokens: int = (
            getattr(usage_metadata, "cached_content_token_count", 0) or 0
        )
        cache_write_tokens: int = (
            getattr(usage_metadata, "cache_creation_token_count", 0) or 0
        )

        # Uncached input = total input minus the cache-read portion
        uncached_input = max(0, input_tokens - cache_read_tokens)

        # Choose long vs. short context tier based on total input
        input_rate = (
            price.input_long
            if input_tokens > _LONG_CONTEXT_THRESHOLD
            else price.input_short
        )

        cost = (
            uncached_input * input_rate / _PER_MILLION
            + cache_read_tokens * price.cache_read / _PER_MILLION
            + cache_write_tokens * price.cache_write / _PER_MILLION
            + output_tokens * price.output / _PER_MILLION
        )
        return round(cost, 8)
    except Exception:
        return 0.0
