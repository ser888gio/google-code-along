"""SSE streaming pipeline for /chat/stream.

Turns ADK runner events into Server-Sent Events: text chunks, field updates,
choices, keepalives, and the [DONE] terminator. Post-turn persistence is
delegated to chat_turn.run_turn_postprocessing.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from typing import AsyncIterator

import runtime
from agent.discovery_agent import extract_discovery_fields
from chat_turn import run_turn_postprocessing
from config import FINALIZING_MARKER, MODEL_ORCHESTRATOR
from firestore import get_discovery_state
from logger import get_logger
from observability.metrics import record_itl, record_ttft
from observability.safety import FRIENDLY_COST_ERROR, CostCircuitBreakerTripped
from observability.tracing import current_trace_ids
from observability.turns import (
    current_turn,
    reset_turn,
    set_stream_timings,
    start_turn,
    summarize_turn,
)

logger = get_logger(__name__)


@dataclass
class StreamReplyState:
    reply_parts: list[str] = field(default_factory=list)
    chunk_times: list[float] = field(default_factory=list)
    cost_aborted: bool = False
    stream_started_at: float = field(default_factory=time.perf_counter)
    ttft_recorded: bool = False


_CHOICES_PATTERN = re.compile(r"\s*<choices>(\[.*?])</choices>\s*", re.DOTALL)


def _sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _event_text_parts(event) -> list[str]:
    if not event.content or not event.content.parts:
        return []
    return [part.text for part in event.content.parts if part.text]


def _field_update_sse_events(prev_fields: dict, new_fields: dict) -> list[str]:
    events: list[str] = []
    for key, entry in new_fields.items():
        if not entry or not entry.get("filled"):
            continue
        new_value = entry.get("value")
        if new_value is None:
            continue
        prev_entry = prev_fields.get(key) or {}
        prev_filled = bool(prev_entry.get("filled"))
        prev_value = prev_entry.get("value")
        if (not prev_filled) or (prev_value != new_value):
            events.append(_sse_event({"field_update": {"key": key, "value": new_value}}))
    return events


def _record_agent_text_chunk(text: str, state: StreamReplyState) -> str | None:
    now = time.perf_counter()
    if not state.ttft_recorded:
        ttft = now - state.stream_started_at
        record_ttft(ttft, model=MODEL_ORCHESTRATOR, phase="chat")
        set_stream_timings(ttft_ms=int(ttft * 1000))
        state.ttft_recorded = True
    state.chunk_times.append(now)
    state.reply_parts.append(text)

    clean = text.replace(FINALIZING_MARKER, "").strip()
    if not clean:
        return None
    return _sse_event({"text": clean})


async def _pre_stream_field_update_events(session_id: str, workflow_turn: dict) -> list[str]:
    try:
        loop = asyncio.get_running_loop()
        prev_state = await loop.run_in_executor(None, get_discovery_state, session_id)
        new_state = await asyncio.wait_for(
            extract_discovery_fields(
                workflow_turn["tail_text"],
                session_id=session_id,
                solution_type=workflow_turn.get("solution_type"),
            ),
            timeout=4.0,
        )
        events = _field_update_sse_events(
            (prev_state or {}).get("fields") or {},
            new_state.get("fields") or {},
        )
        logger.info(f"Pre-stream field_update: session={session_id} emitted={len(events)}")
        return events
    except asyncio.TimeoutError:
        logger.warning(
            f"Pre-stream extract timed out (>4s): event=extract_timeout_total session_id={session_id} timeout_seconds=4"
        )
    except CostCircuitBreakerTripped:
        raise
    except Exception as exc:
        logger.warning(f"Pre-stream extract failed: session={session_id} {exc}")
    return []


async def _agent_stream_events(
    *,
    user_id: str,
    user_content,
    session_id: str,
    state: StreamReplyState,
) -> AsyncIterator[str]:
    try:
        async for event in runtime.runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=user_content,
        ):
            for text in _event_text_parts(event):
                if stream_event := _record_agent_text_chunk(text, state):
                    yield stream_event
    except CostCircuitBreakerTripped as exc:
        state.cost_aborted = True
        logger.warning(f"Stream aborted by cost circuit: session_id={session_id} cost_usd={exc.cost_usd:.6f}")
        yield _sse_event({"error": FRIENDLY_COST_ERROR})
    except Exception as exc:
        logger.error(
            f"Streaming error for session_id={session_id}: {exc}",
            exc_info=True,
        )
        yield _sse_event({"error": "An internal error occurred. Please try again."})


async def _keepalive_merged(
    agent_gen: AsyncIterator[str],
    interval: float = 20.0,
) -> AsyncIterator[str]:
    """Interleave SSE keepalive comments with agent events to prevent Cloud Run idle-stream timeouts."""
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def drain_agent() -> None:
        async for event in agent_gen:
            await queue.put(event)
        await queue.put(None)

    async def keepalive_ticker() -> None:
        while True:
            await asyncio.sleep(interval)
            await queue.put(": keepalive\n\n")

    agent_task = asyncio.create_task(drain_agent())
    ticker_task = asyncio.create_task(keepalive_ticker())
    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item
    finally:
        ticker_task.cancel()
        agent_task.cancel()
        with suppress(asyncio.CancelledError):
            await agent_task


async def chat_stream_event_generator(
    *,
    session_id: str,
    user_id: str,
    message: str,
    workflow_turn: dict,
    user_content,
) -> AsyncIterator[str]:
    message_id = str(uuid.uuid4())
    trace_id, span_id = current_trace_ids()
    turn_token = start_turn(
        session_id=session_id,
        message_id=message_id,
        phase="chat",
    )
    turn_t0 = time.perf_counter()

    yield _sse_event({"session_id": session_id, "message_id": message_id})
    active_field = workflow_turn["workflow"].get("active_field")
    if active_field:
        yield _sse_event({"active_field": active_field})

    try:
        for update_event in await _pre_stream_field_update_events(session_id, workflow_turn):
            yield update_event
    except CostCircuitBreakerTripped as exc:
        logger.warning(
            f"Stream aborted by cost circuit during extraction: session_id={session_id} cost_usd={exc.cost_usd:.6f}"
        )
        reset_turn(turn_token)
        yield _sse_event({"error": FRIENDLY_COST_ERROR})
        yield "data: [DONE]\n\n"
        return

    stream_state = StreamReplyState()
    async for stream_event in _keepalive_merged(
        _agent_stream_events(
            user_id=user_id,
            user_content=user_content,
            session_id=session_id,
            state=stream_state,
        )
    ):
        yield stream_event

    if stream_state.cost_aborted:
        reset_turn(turn_token)
        yield "data: [DONE]\n\n"
        return

    if len(stream_state.chunk_times) >= 2:
        avg_itl = (stream_state.chunk_times[-1] - stream_state.chunk_times[0]) / (len(stream_state.chunk_times) - 1)
        record_itl(avg_itl)
        set_stream_timings(itl_ms=int(avg_itl * 1000))

    full_reply = "".join(stream_state.reply_parts)
    set_stream_timings(latency_ms=int((time.perf_counter() - turn_t0) * 1000))
    turn_summary = summarize_turn(current_turn())
    logger.info(f"Stream complete: session_id={session_id} reply_chars={len(full_reply)}")

    is_finalizing = FINALIZING_MARKER in full_reply
    if is_finalizing:
        logger.info(f"[FINALIZING] detected for session_id={session_id} launching finalizer pipeline")
        yield _sse_event({"event": "finalizing"})

    choices_match = _CHOICES_PATTERN.search(full_reply)
    if choices_match:
        try:
            choices = json.loads(choices_match.group(1))
            if isinstance(choices, list) and 2 <= len(choices) <= 4:
                clean_text = _CHOICES_PATTERN.sub("", full_reply)
                clean_text = clean_text.replace(FINALIZING_MARKER, "").strip()
                yield _sse_event({"choices": choices})
                yield _sse_event({"text_replace": clean_text})
                logger.info(f"Choices emitted: session_id={session_id} count={len(choices)}")
        except (json.JSONDecodeError, ValueError):
            pass

    asyncio.create_task(
        run_turn_postprocessing(
            session_id=session_id,
            user_id=user_id,
            user_text=message,
            assistant_text=full_reply,
            is_finalizing=is_finalizing,
            fallback_transcript=full_reply,
            message_id=message_id,
            trace_id=trace_id,
            span_id=span_id,
            turn_summary=turn_summary,
        )
    )

    reset_turn(turn_token)
    yield "data: [DONE]\n\n"
