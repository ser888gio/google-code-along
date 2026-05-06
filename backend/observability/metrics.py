"""Custom OTel metric definitions for the RS Generator.

All instruments are created lazily on first import — safe to import anywhere.
Callers use the module-level helpers (record_ttft, record_itl, etc.) rather
than touching the raw instruments directly.
"""

from __future__ import annotations

from opentelemetry import metrics

_meter = metrics.get_meter("rs-generator", version="1.0.0")

# ---------------------------------------------------------------------------
# Histograms
# ---------------------------------------------------------------------------

ttft_histogram = _meter.create_histogram(
    name="genai.client.ttft_seconds",
    description="Time to first token from the streaming LLM call.",
    unit="s",
)

itl_histogram = _meter.create_histogram(
    name="genai.client.itl_seconds",
    description="Average inter-token latency across the streaming response.",
    unit="s",
)

token_histogram = _meter.create_histogram(
    name="genai.client.token.usage",
    description="Token counts per LLM call (input, output, cache_read).",
    unit="tokens",
)

operation_duration_histogram = _meter.create_histogram(
    name="genai.client.operation.duration_seconds",
    description="End-to-end duration of a generate_content call.",
    unit="s",
)

# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------

cost_counter = _meter.create_counter(
    name="genai.client.cost_usd",
    description="Estimated USD cost of each LLM call.",
    unit="USD",
)

feedback_counter = _meter.create_counter(
    name="rs.feedback.vote",
    description="User thumbs-up/down votes per assistant message.",
    unit="votes",
)

session_completion_counter = _meter.create_counter(
    name="rs.session.completion_total",
    description="Sessions that reached [FINALIZING] (finalized) or were abandoned.",
    unit="sessions",
)

safety_finish_reason_counter = _meter.create_counter(
    name="rs.safety.finish_reason_safety",
    description="Count of responses blocked by Gemini safety filters.",
    unit="events",
)

# ---------------------------------------------------------------------------
# Gauges (up-down counters used as gauges)
# ---------------------------------------------------------------------------

cache_hit_ratio_gauge = _meter.create_observable_gauge(
    name="rs.cache.hit_ratio",
    description="Ratio of cache_read_tokens to total input_tokens per call.",
    unit="ratio",
    callbacks=[],  # populated externally if needed; per-call values recorded via histogram
)

# ---------------------------------------------------------------------------
# Helper record functions
# ---------------------------------------------------------------------------


def record_ttft(seconds: float, *, model: str, phase: str) -> None:
    ttft_histogram.record(seconds, attributes={"model": model, "phase": phase})


def record_itl(seconds: float) -> None:
    itl_histogram.record(seconds)


def record_tokens(
    count: int,
    *,
    model: str,
    token_type: str,
    feature: str,
) -> None:
    """token_type: 'input' | 'output' | 'cache_read' | 'cache_write'"""
    token_histogram.record(
        count,
        attributes={"model": model, "type": token_type, "feature": feature},
    )


def record_operation_duration(seconds: float, *, model: str, operation: str, status: str) -> None:
    operation_duration_histogram.record(
        seconds,
        attributes={"model": model, "operation": operation, "status": status},
    )


def record_cost(cost_usd: float, *, model: str, feature: str, session_id_hash: str) -> None:
    if cost_usd > 0:
        cost_counter.add(
            cost_usd,
            attributes={"model": model, "feature": feature, "session_id_hash": session_id_hash},
        )


def record_feedback_vote(*, vote: str, phase: str) -> None:
    feedback_counter.add(1, attributes={"vote": vote, "phase": phase})
