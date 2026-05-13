"""Per-turn telemetry collected from callbacks and streaming wrappers."""

from __future__ import annotations

import contextvars
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ModelCallTelemetry:
    model: str = ""
    feature: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    finish_reason: str | None = None


@dataclass
class TurnTelemetry:
    session_id: str
    message_id: str
    phase: str = "chat"
    model_calls: list[ModelCallTelemetry] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    ttft_ms: int | None = None
    itl_ms: int | None = None
    latency_ms: int | None = None


_current_turn: contextvars.ContextVar[TurnTelemetry | None] = contextvars.ContextVar(
    "rs_current_turn",
    default=None,
)


def start_turn(*, session_id: str, message_id: str, phase: str = "chat"):
    """Set the active telemetry bucket for the current async context."""
    telemetry = TurnTelemetry(session_id=session_id, message_id=message_id, phase=phase)
    token = _current_turn.set(telemetry)
    return token


def reset_turn(token) -> None:  # noqa: ANN001
    _current_turn.reset(token)


def current_turn() -> TurnTelemetry | None:
    return _current_turn.get()


def record_model_call(
    *,
    model: str,
    feature: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    cost_usd: float = 0.0,
    finish_reason: str | None = None,
) -> None:
    telemetry = current_turn()
    if telemetry is None:
        return
    telemetry.model_calls.append(
        ModelCallTelemetry(
            model=model,
            feature=feature,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            cost_usd=cost_usd,
            finish_reason=finish_reason,
        )
    )


def record_tool_call(tool_call: dict[str, Any]) -> None:
    telemetry = current_turn()
    if telemetry is None:
        return
    telemetry.tool_calls.append(tool_call)


def set_stream_timings(
    *,
    ttft_ms: int | None = None,
    itl_ms: int | None = None,
    latency_ms: int | None = None,
) -> None:
    telemetry = current_turn()
    if telemetry is None:
        return
    if ttft_ms is not None:
        telemetry.ttft_ms = ttft_ms
    if itl_ms is not None:
        telemetry.itl_ms = itl_ms
    if latency_ms is not None:
        telemetry.latency_ms = latency_ms


def summarize_turn(telemetry: TurnTelemetry | None) -> dict[str, Any]:
    """Aggregate collected callback data into Firestore message fields."""
    if telemetry is None:
        return {}

    input_tokens = sum(call.input_tokens for call in telemetry.model_calls)
    output_tokens = sum(call.output_tokens for call in telemetry.model_calls)
    cache_read_tokens = sum(call.cache_read_tokens for call in telemetry.model_calls)
    cost_usd = round(sum(call.cost_usd for call in telemetry.model_calls), 8)
    model = next(
        (call.model for call in reversed(telemetry.model_calls) if call.model), None
    )
    finish_reason = next(
        (
            call.finish_reason
            for call in reversed(telemetry.model_calls)
            if call.finish_reason
        ),
        None,
    )

    return {
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cost_usd": cost_usd,
        "ttft_ms": telemetry.ttft_ms,
        "itl_ms": telemetry.itl_ms,
        "latency_ms": telemetry.latency_ms,
        "tool_calls": telemetry.tool_calls,
        "phase": telemetry.phase,
        "finish_reason": finish_reason,
    }
