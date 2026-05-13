"""ADK agent callbacks for OTel span enrichment and cost/token recording.

Wire these into Agent constructors via:
    before_model_callback=before_model_cb,
    after_model_callback=after_model_cb,
    before_tool_callback=before_tool_cb,
    after_tool_callback=after_tool_cb,

The callbacks stamp the *current* OTel span (opened by ADK's internal
`generate_content` span) with GenAI semantic convention attributes, record
token/cost metrics, and attach short redacted message snippets as span events.
They never modify the LLM request/response — always return None.
"""

from __future__ import annotations

import hashlib
import time

from opentelemetry import trace

from observability.cost import compute_cost
from observability.metrics import (
    record_cache_hit_ratio,
    record_cost,
    record_operation_duration,
    record_safety_finish_reason,
    record_tokens,
)
from observability.safety import add_session_cost
from observability.turns import record_model_call, record_tool_call

_SNIPPET_MAX_CHARS = 500  # max chars captured as span event content


def _redact_snippet(text: str, max_chars: int = _SNIPPET_MAX_CHARS) -> str:
    """Truncate to max_chars. No regex-based PII removal — minimise what we store."""
    if not text:
        return ""
    return text[:max_chars] + ("…" if len(text) > max_chars else "")


def _hash_id(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def _extract_text_from_content(content) -> str:
    """Pull plain text out of a google.genai Content object."""
    if content is None:
        return ""
    parts = getattr(content, "parts", None) or []
    return " ".join(getattr(p, "text", "") or "" for p in parts).strip()


# ---------------------------------------------------------------------------
# before_model_callback
# ---------------------------------------------------------------------------

# Per-invocation start time tracked via invocation_id so after_model can
# compute duration without needing closure state.
_call_start: dict[str, float] = {}


def before_model_cb(callback_context, llm_request) -> None:
    """Stamp the current span with request-side GenAI attributes."""
    span = trace.get_current_span()
    if not span.is_recording():
        return None  # type: ignore[return-value]

    invocation_id: str = getattr(callback_context, "invocation_id", "") or ""
    session_id: str = ""
    user_id: str = ""
    try:
        session_id = callback_context.session.id or ""
        user_id = callback_context.user_id or ""
    except Exception:
        pass

    model: str = getattr(llm_request, "model", "") or ""
    agent_name: str = getattr(callback_context, "agent_name", "") or ""

    span.set_attribute("gen_ai.system", "gemini")
    if model:
        span.set_attribute("gen_ai.request.model", model)
    if session_id:
        span.set_attribute("session_id", session_id)
    if user_id:
        span.set_attribute("user_id_hash", _hash_id(user_id))
    if agent_name:
        span.set_attribute("agent_name", agent_name)

    # Capture a short redacted snippet of the latest user message as a span event
    try:
        user_content = getattr(callback_context, "user_content", None)
        snippet = _redact_snippet(_extract_text_from_content(user_content))
        if snippet:
            span.add_event("gen_ai.user.message", attributes={"content": snippet})
    except Exception:
        pass

    # Record call start time keyed by invocation so after_model can compute duration
    if invocation_id:
        _call_start[invocation_id] = time.perf_counter()

    return None  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# after_model_callback
# ---------------------------------------------------------------------------


def after_model_cb(callback_context, llm_response) -> None:
    """Stamp the current span with response-side GenAI attributes and record metrics."""
    span = trace.get_current_span()
    pending_session_cost_usd = 0.0

    invocation_id: str = getattr(callback_context, "invocation_id", "") or ""
    session_id: str = ""
    try:
        session_id = callback_context.session.id or ""
    except Exception:
        pass
    model: str = getattr(llm_response, "model_version", "") or ""
    finish_reason = getattr(llm_response, "finish_reason", None)
    usage = getattr(llm_response, "usage_metadata", None)

    if span.is_recording():
        if model:
            span.set_attribute("gen_ai.response.model", model)
        if finish_reason is not None:
            span.set_attribute("gen_ai.response.finish_reasons", str(finish_reason))

        if usage:
            input_tokens = getattr(usage, "prompt_token_count", 0) or 0
            output_tokens = getattr(usage, "candidates_token_count", 0) or 0
            cache_read = getattr(usage, "cached_content_token_count", 0) or 0
            cache_write = getattr(usage, "cache_creation_token_count", 0) or 0
            span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
            span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
            span.set_attribute("gen_ai.usage.cache_read.input_tokens", cache_read)
            span.set_attribute("gen_ai.usage.cache_creation.input_tokens", cache_write)

        # Capture a short snippet of the assistant's reply as a span event
        try:
            reply_content = getattr(llm_response, "content", None)
            snippet = _redact_snippet(_extract_text_from_content(reply_content))
            if snippet:
                span.add_event(
                    "gen_ai.assistant.message",
                    attributes={"content": snippet},
                )
        except Exception:
            pass

    # Compute and record cost + token metrics
    if usage and model:
        cost_usd = compute_cost(model, usage)
        sid_hash = _hash_id(session_id) if session_id else "unknown"
        agent_name = getattr(callback_context, "agent_name", "unknown") or "unknown"

        if span.is_recording() and cost_usd:
            span.set_attribute("cost_usd", cost_usd)

        record_cost(cost_usd, model=model, feature=agent_name, session_id_hash=sid_hash)

        input_tokens = getattr(usage, "prompt_token_count", 0) or 0
        output_tokens = getattr(usage, "candidates_token_count", 0) or 0
        cache_read = getattr(usage, "cached_content_token_count", 0) or 0

        record_tokens(input_tokens, model=model, token_type="input", feature=agent_name)
        record_tokens(
            output_tokens,
            model=model,
            token_type="output",
            feature=agent_name,
        )
        if cache_read:
            record_tokens(
                cache_read,
                model=model,
                token_type="cache_read",
                feature=agent_name,
            )
        record_cache_hit_ratio(
            model=model,
            input_tokens=input_tokens,
            cache_read_tokens=cache_read,
        )
        if "SAFETY" in str(finish_reason).upper():
            record_safety_finish_reason(model=model)
        record_model_call(
            model=model,
            feature=agent_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read,
            cache_write_tokens=getattr(usage, "cache_creation_token_count", 0) or 0,
            cost_usd=cost_usd,
            finish_reason=str(finish_reason) if finish_reason is not None else None,
        )
        pending_session_cost_usd = cost_usd

    # Record operation duration
    if invocation_id and invocation_id in _call_start:
        elapsed = time.perf_counter() - _call_start.pop(invocation_id)
        status = "ok" if finish_reason not in ("SAFETY", "ERROR") else str(finish_reason)
        record_operation_duration(
            elapsed,
            model=model or "unknown",
            operation="generate_content",
            status=status,
        )

    add_session_cost(session_id, pending_session_cost_usd)

    return None  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# before_tool_callback
# ---------------------------------------------------------------------------


def before_tool_cb(  # type: ignore[return-value]
    tool,
    args,
    tool_context,
) -> None:
    """Record a span event for the tool call start."""
    span = trace.get_current_span()
    tool_name = getattr(tool, "name", None) or str(tool)
    record_tool_call(
        {
            "tool_name": tool_name,
            "event": "call",
            "args_preview": _redact_snippet(str(args), 200),
        }
    )
    if not span.is_recording():
        return None

    span.add_event(
        "gen_ai.tool.call",
        attributes={
            "tool_name": tool_name,
            "args_preview": _redact_snippet(str(args), 200),
        },
    )
    return None


# ---------------------------------------------------------------------------
# after_tool_callback
# ---------------------------------------------------------------------------


def after_tool_cb(  # type: ignore[return-value]
    tool,
    args,
    tool_context,
    tool_response,
) -> None:
    """Record a span event for the tool call result."""
    span = trace.get_current_span()
    tool_name = getattr(tool, "name", None) or str(tool)
    record_tool_call(
        {
            "tool_name": tool_name,
            "event": "result",
            "result_preview": _redact_snippet(str(tool_response), 200),
        }
    )
    if not span.is_recording():
        return None

    span.add_event(
        "gen_ai.tool.result",
        attributes={
            "tool_name": tool_name,
            "result_preview": _redact_snippet(str(tool_response), 200),
        },
    )
    return None
