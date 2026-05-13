"""Custom OTel metric definitions for the RS Generator.

All instruments are created lazily on first import — safe to import anywhere.
Callers use the module-level helpers (record_ttft, record_itl, etc.) rather
than touching the raw instruments directly.
"""

from __future__ import annotations

from collections.abc import Iterable

from opentelemetry import metrics
from opentelemetry.metrics import Observation

_meter = metrics.get_meter("rs-generator", version="1.0.0")
_cache_hit_ratios: dict[str, float] = {}
_injection_block_rates: dict[str, float] = {}


def _observe_cache_hit_ratio(_options) -> Iterable[Observation]:  # noqa: ANN001
    for model, ratio in _cache_hit_ratios.items():
        yield Observation(ratio, attributes={"model": model})


def _observe_injection_block_rate(_options) -> Iterable[Observation]:  # noqa: ANN001
    for suite, ratio in _injection_block_rates.items():
        yield Observation(ratio, attributes={"suite": suite})


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

session_duration_histogram = _meter.create_histogram(
    name="rs.session.duration_seconds",
    description="Duration from first observed session turn to completion.",
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

cost_circuit_counter = _meter.create_counter(
    name="rs.safety.cost_circuit_tripped",
    description="Count of sessions stopped by a cost circuit breaker.",
    unit="events",
)

prompt_injection_attempt_counter = _meter.create_counter(
    name="rs.safety.injection_attempt_total",
    description=("Known-bad prompt injection or exfiltration attempts seen by safety checks."),
    unit="events",
)

anomalous_session_counter = _meter.create_counter(
    name="rs.safety.anomalous_session",
    description="Sessions flagged for anomalous token or cost usage.",
    unit="events",
)

# ---------------------------------------------------------------------------
# Gauges (up-down counters used as gauges)
# ---------------------------------------------------------------------------

cache_hit_ratio_gauge = _meter.create_observable_gauge(
    name="rs.cache.hit_ratio",
    description="Ratio of cache_read_tokens to total input_tokens per call.",
    unit="ratio",
    callbacks=[_observe_cache_hit_ratio],
)

injection_block_rate_gauge = _meter.create_observable_gauge(
    name="rs.safety.injection_block_rate",
    description="Synthetic red-team prompt block rate.",
    unit="ratio",
    callbacks=[_observe_injection_block_rate],
)

# ---------------------------------------------------------------------------
# Helper record functions
# ---------------------------------------------------------------------------


def record_ttft(seconds: float, *, model: str, phase: str) -> None:
    if seconds >= 0:
        ttft_histogram.record(seconds, attributes={"model": model, "phase": phase})


def record_itl(seconds: float) -> None:
    if seconds >= 0:
        itl_histogram.record(seconds)


def record_tokens(
    count: int,
    *,
    model: str,
    token_type: str,
    feature: str,
) -> None:
    """token_type: 'input' | 'output' | 'cache_read' | 'cache_write'"""
    if count < 0:
        return
    token_histogram.record(
        count,
        attributes={"model": model, "type": token_type, "feature": feature},
    )


def record_operation_duration(
    seconds: float,
    *,
    model: str,
    operation: str,
    status: str,
) -> None:
    if seconds < 0:
        return
    operation_duration_histogram.record(
        seconds,
        attributes={"model": model, "operation": operation, "status": status},
    )


def record_cost(
    cost_usd: float,
    *,
    model: str,
    feature: str,
    session_id_hash: str,
) -> None:
    if cost_usd > 0:
        cost_counter.add(
            cost_usd,
            attributes={
                "model": model,
                "feature": feature,
                "session_id_hash": session_id_hash,
            },
        )


def record_feedback_vote(*, vote: str, phase: str) -> None:
    feedback_counter.add(1, attributes={"vote": vote, "phase": phase})


def record_session_duration(seconds: float, *, outcome: str) -> None:
    if seconds >= 0:
        session_duration_histogram.record(seconds, attributes={"outcome": outcome})


def record_session_completion(*, outcome: str) -> None:
    session_completion_counter.add(1, attributes={"outcome": outcome})


def record_cache_hit_ratio(
    *,
    model: str,
    input_tokens: int,
    cache_read_tokens: int,
) -> None:
    if input_tokens <= 0:
        return
    ratio = max(0.0, min(1.0, cache_read_tokens / input_tokens))
    _cache_hit_ratios[model] = ratio


def record_cost_circuit_tripped(*, session_id_hash: str) -> None:
    cost_circuit_counter.add(1, attributes={"session_id_hash": session_id_hash})


def record_safety_finish_reason(*, model: str) -> None:
    safety_finish_reason_counter.add(1, attributes={"model": model})


def record_prompt_injection_attempt(*, blocked: bool, category: str) -> None:
    prompt_injection_attempt_counter.add(
        1,
        attributes={"blocked": str(blocked).lower(), "category": category},
    )


def record_injection_block_rate(*, suite: str, block_rate: float) -> None:
    _injection_block_rates[suite] = max(0.0, min(1.0, block_rate))


def record_anomalous_session(*, reason: str) -> None:
    anomalous_session_counter.add(1, attributes={"reason": reason})


def force_flush_metrics(timeout_millis: int = 5_000) -> bool:
    """Flush OTel metrics before short-lived jobs exit."""
    provider = metrics.get_meter_provider()
    force_flush = getattr(provider, "force_flush", None)
    if not callable(force_flush):
        return False
    return bool(force_flush(timeout_millis=timeout_millis))
