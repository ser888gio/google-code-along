from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
import weakref
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import partial
from typing import AsyncIterator, Literal

from admin_sessions import (
    get_admin_metrics,
    get_admin_session,
    list_admin_sessions,
    require_admin,
)
from agent import audio_agent, rs_agent
from agent.discovery_agent import (
    extract_discovery_fields,
    initialize_workflow_state,
    is_not_applicable_allowed,
    pick_next_active_field,
    sync_workflow_with_discovery_state,
)
from agent.finalizer_agent import run_finalizer
from answer_classifier import (
    DIRECT_FIELD_KEYS,
    ClassifierResult,
    classify_user_turn,
    is_deferred_answer,
    normalize_for_match,
)
from answer_quality import rate_answer
from audio_websocket import AudioWebsocketDeps, run_audio_websocket
from bpmn import check_completeness, generate_bpmn_diagram
from config import (
    APP_NAME,
    FINALIZING_MARKER,
    GCS_PREFIX_SESSIONS,
    MODEL_AUDIO,
    MODEL_ORCHESTRATOR,
    validate_config,
)
from dataflow import check_dfd_completeness, generate_dataflow_diagram
from direct_field_context import build_augmented_user_message, merge_direct_fields
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    WebSocket,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from field_schema import FIELD_LABELS, FIELD_SCHEMA, REQUIRED_FIELDS
from firestore import (
    append_conversation_turn,
    get_conversation_history,
    get_deferred_fields,
    get_direct_fields,
    get_discovery_state,
    get_final_analysis,
    get_srs_fields,
    get_workflow_state,
    list_sessions,
    remove_deferred_fields,
    set_finalization_error,
    set_finalization_pending,
    update_feedback_comment,
    upsert_deferred_fields,
    upsert_direct_fields,
    upsert_discovery_state,
    upsert_message_feedback,
    upsert_session_feedback,
    upsert_srs_fields,
    upsert_workflow_state,
)
from gcs import get_bucket_name, list_files, write_file
from generation import (
    compile_rs_from_session,
    compile_srs_json_from_session,
    markdown_to_pdf,
    rs_template_to_docx,
    srs_json_to_docx,
)
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from google.genai.types import (
    AudioTranscriptionConfig,
    SpeechConfig,
    VoiceConfig,
)
from logger import get_logger, setup_logging
from observability.metrics import (
    record_feedback_vote,
    record_itl,
    record_operation_duration,
    record_session_completion,
    record_session_duration,
    record_ttft,
)
from observability.safety import (
    FRIENDLY_COST_ERROR,
    FRIENDLY_PROMPT_ERROR,
    CostCircuitBreakerTripped,
    UnsafePromptBlocked,
    assert_session_within_budget,
    check_user_prompt_or_raise,
)
from observability.tracing import setup_telemetry
from observability.turns import (
    current_turn,
    reset_turn,
    set_stream_timings,
    start_turn,
    summarize_turn,
)
from opentelemetry import trace
from pydantic import BaseModel
from session_bridge import SessionBridge
from starlette.requests import Request
from utils import extract_conversation_text, sanitize_gcs_filename, sanitize_gcs_segment

setup_logging()
logger = get_logger(__name__)

app = FastAPI(title="RS Generator API")

_raw_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")
_allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
    allow_credentials=True,
)

setup_telemetry(app)
logger.info(f"RS Generator API initializing (app_name={APP_NAME})")


@app.on_event("startup")
async def validate_runtime_config() -> None:
    """Fail fast with explicit config errors before serving traffic."""
    for warning in validate_config():
        logger.warning(warning)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Return a JSON 500 for any unhandled exception.

    This ensures the response flows through CORSMiddleware so the browser
    always receives Access-Control-Allow-Origin headers — even on errors.
    """
    logger.error(
        f"Unhandled exception on {request.method} {request.url.path}: {exc}",
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


# --- ADK runner setup ---

# NOTE: ADK sessions are in-memory only. A backend restart drops all live sessions.
# Firestore persists conversation history and discovery state, so /context/extract
# can reconstruct context after a restart, but any in-flight [FINALIZING] trigger
# will be lost. Migrate to a persistent ADK session store before production.
session_service = InMemorySessionService()

runner = Runner(
    app_name=APP_NAME,
    agent=rs_agent,
    session_service=session_service,
)

# Audio runner for bidi voice streaming (uses native-audio model).
# Intentionally shares session_service with the text runner so SessionBridge
# can inject voice transcripts into the orchestrator's ADK session. The shared
# service is by design — see SessionBridge below.
audio_runner = Runner(
    app_name=APP_NAME,
    agent=audio_agent,
    session_service=session_service,
)

# Bridge: injects voice transcripts into the text orchestrator's ADK session
# so the orchestrator has full context when the user switches back to text.
session_bridge = SessionBridge(
    session_service=session_service,
    app_name=APP_NAME,
    orchestrator_agent_name=rs_agent.name,
)

# Per-session dedup lock for /context/extract.
# Prevents multiple parallel Gemini extraction calls for the same session
# (common in voice mode where turn_complete events arrive faster than
# the ~40s extraction call can finish).
# WeakValueDictionary so entries are evicted automatically once no request
# holds a reference to the lock — no unbounded growth across sessions.
_extract_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()
_session_started_at: dict[str, float] = {}
_session_outcomes_recorded: set[str] = set()


def _mark_session_seen(session_id: str) -> None:
    """Remember first-seen time for session duration metrics."""
    _session_started_at.setdefault(session_id, time.monotonic())


def _record_session_outcome(
    session_id: str,
    outcome: Literal["finalized", "abandoned"],
) -> None:
    """Record session completion once per backend process."""
    if session_id in _session_outcomes_recorded:
        return
    _session_outcomes_recorded.add(session_id)
    started_at = _session_started_at.pop(session_id, None)
    if started_at is not None:
        record_session_duration(time.monotonic() - started_at, outcome=outcome)
    record_session_completion(outcome=outcome)


def _current_trace_ids() -> tuple[str | None, str | None]:
    """Return current OTel trace/span IDs as hex strings, if a span is active."""
    span_context = trace.get_current_span().get_span_context()
    if not span_context or not span_context.is_valid:
        return None, None
    return f"{span_context.trace_id:032x}", f"{span_context.span_id:016x}"


def _run_safety_preflight(message: str, session_id: str) -> None:
    assert_session_within_budget(session_id)
    check_user_prompt_or_raise(message, session_id=session_id)


def _safety_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, CostCircuitBreakerTripped):
        return HTTPException(status_code=429, detail=FRIENDLY_COST_ERROR)
    if isinstance(exc, UnsafePromptBlocked):
        return HTTPException(status_code=400, detail=FRIENDLY_PROMPT_ERROR)
    return HTTPException(status_code=400, detail="Safety check failed.")


def _safety_error_stream(session_id: str, detail: str) -> StreamingResponse:
    async def generator():
        yield f"data: {json.dumps({'session_id': session_id, 'error': detail})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generator(), media_type="text/event-stream")


def _conversation_event_line(event) -> str | None:
    if not event.content or not event.content.parts:
        return None

    text = "".join(p.text for p in event.content.parts if p.text).strip()
    if not text:
        return None

    label = "User" if event.content.role == "user" else "Consultant"
    return f"{label}: {text}"


def _build_conversation_tail(session, latest_user_message: str, limit: int = 12) -> str:
    """Build a compact transcript tail for classifiers/extractors."""
    events = getattr(session, "events", None) if session else None
    tail_lines = [line for event in (events or [])[-limit:] if (line := _conversation_event_line(event))]
    tail_lines.append(f"User: {latest_user_message}")
    return "\n".join(tail_lines)


def _answered_field_values(
    discovery_state: dict | None,
    direct_fields: dict[str, str],
) -> dict[str, str]:
    """Return answered field values for hidden workflow context."""
    values: dict[str, str] = {}
    for key, entry in ((discovery_state or {}).get("fields") or {}).items():
        if isinstance(entry, dict) and entry.get("filled") and entry.get("value"):
            values[key] = str(entry["value"])
    for key, value in direct_fields.items():
        if str(value or "").strip():
            values[key] = str(value).strip()
    return values


def _is_finalize_choice(message: str) -> bool:
    """Detect a wrap-up user choice to finalize with open questions."""
    text = normalize_for_match(message)
    return any(
        phrase in text
        for phrase in [
            "finalize",
            "finalise",
            "generate",
            "vygeneruj",
            "finalizuj",
            "dokoncit",
            "nechat",
            "pozdeji",
        ]
    )


async def _reopen_first_deferred_field(
    *,
    session_id: str,
    workflow: dict,
    deferred_fields: dict,
) -> None:
    """Move wrap-up back to discovery for the first deferred field."""
    if not deferred_fields:
        return

    field_key = next(iter(deferred_fields))
    deferred_fields.pop(field_key, None)
    workflow["phase"] = "discovery"
    workflow["active_field"] = field_key
    workflow.setdefault("field_status", {})[field_key] = "missing"
    workflow.setdefault("miss_counts", {})[field_key] = 0

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, remove_deferred_fields, session_id, [field_key])


def _field_entry(value: str) -> dict:
    return {"filled": True, "value": value}


def _recompute_discovery_completeness(state: dict) -> None:
    fields = state.setdefault("fields", {})
    filled = sum(1 for key in REQUIRED_FIELDS if fields.get(key, {}).get("filled"))
    state["completeness"] = round((filled / len(REQUIRED_FIELDS)) * 100)


def _empty_discovery_state() -> dict:
    return {"completeness": 0, "fields": {}, "missing_priority": []}


async def _classify_and_update_active_field(
    *,
    session_id: str,
    field_key: str,
    message: str,
    tail_text: str,
    solution_type: str | None,
    workflow: dict,
    discovery_state: dict | None,
    direct_fields: dict[str, str],
    deferred_fields: dict,
) -> tuple[ClassifierResult, dict | None]:
    """Run the classifier for the active field and persist the resulting status changes."""
    loop = asyncio.get_running_loop()

    classification: ClassifierResult = await classify_user_turn(
        field_key, message, tail_text, solution_type=solution_type
    )
    await rate_answer(
        field_key,
        str((workflow.get("last_question_by_field") or {}).get(field_key, "")),
        message,
        classification["classification"],
    )

    statuses = workflow["field_status"]
    miss_counts = workflow.setdefault("miss_counts", {})
    clarification_counts = workflow.setdefault("clarification_counts", {})
    coverage_gaps_by_field = workflow.setdefault("coverage_gaps", {})

    latest_gaps = list(classification.get("coverage_gaps") or [])
    if latest_gaps:
        coverage_gaps_by_field[field_key] = latest_gaps
    else:
        coverage_gaps_by_field.pop(field_key, None)

    clf = classification["classification"]
    if clf == "answered":
        value = classification.get("value")
        if value:
            statuses[field_key] = "answered"
            miss_counts[field_key] = 0
            if discovery_state is None:
                discovery_state = _empty_discovery_state()
            discovery_state.setdefault("fields", {})[field_key] = _field_entry(value)
            _recompute_discovery_completeness(discovery_state)
            await loop.run_in_executor(None, upsert_discovery_state, session_id, discovery_state)
            if field_key in DIRECT_FIELD_KEYS:
                direct_fields[field_key] = value
                await loop.run_in_executor(None, upsert_direct_fields, session_id, {field_key: value})
            if field_key in deferred_fields:
                deferred_fields.pop(field_key, None)
                await loop.run_in_executor(None, remove_deferred_fields, session_id, [field_key])
        else:
            statuses[field_key] = "missing"
    elif clf == "deferred":
        statuses[field_key] = "deferred"
        miss_counts[field_key] = 0
        deferred_fields[field_key] = {"deferred_at": datetime.now(timezone.utc).isoformat()}
        await loop.run_in_executor(None, upsert_deferred_fields, session_id, {field_key: deferred_fields[field_key]})
    elif clf == "clarification_requested":
        statuses[field_key] = "clarification_requested"
        clarification_counts[field_key] = int(clarification_counts.get(field_key) or 0) + 1
    else:
        if is_deferred_answer(message):
            statuses[field_key] = "deferred"
            deferred_fields[field_key] = {"deferred_at": datetime.now(timezone.utc).isoformat()}
            await loop.run_in_executor(
                None, upsert_deferred_fields, session_id, {field_key: deferred_fields[field_key]}
            )
        else:
            statuses[field_key] = "missing"
            miss_counts[field_key] = int(miss_counts.get(field_key) or 0) + 1

    return classification, discovery_state


async def _apply_proactive_updates(
    *,
    session_id: str,
    classification: ClassifierResult,
    active_field: str,
    workflow: dict,
    discovery_state: dict | None,
) -> dict | None:
    """Persist any side-channel field values the classifier extracted proactively."""
    loop = asyncio.get_running_loop()

    proactive_updates: dict[str, str] = {}
    for key, entry in (classification.get("proactive_fields") or {}).items():
        if key not in FIELD_SCHEMA or key == active_field:
            continue
        value = str(entry.get("value") or "").strip()
        if value:
            workflow["field_status"][key] = "answered"
            proactive_updates[key] = value

    if not proactive_updates:
        return discovery_state

    if discovery_state is None:
        discovery_state = _empty_discovery_state()
    fields = discovery_state.setdefault("fields", {})
    for key, value in proactive_updates.items():
        fields[key] = _field_entry(value)
    _recompute_discovery_completeness(discovery_state)
    await loop.run_in_executor(None, upsert_discovery_state, session_id, discovery_state)
    return discovery_state


async def _prepare_workflow_turn(
    *,
    session_id: str,
    req: ChatRequest,
    session,
    direct_fields: dict[str, str],
) -> dict:
    """Advance backend-owned workflow state before the LLM turn starts."""
    loop = asyncio.get_running_loop()

    discovery_state = await loop.run_in_executor(None, get_discovery_state, session_id)
    deferred_fields = await loop.run_in_executor(None, get_deferred_fields, session_id)
    stored_workflow = await loop.run_in_executor(None, get_workflow_state, session_id)
    workflow = sync_workflow_with_discovery_state(
        stored_workflow or initialize_workflow_state(),
        discovery_state,
        direct_fields,
        deferred_fields,
    )

    incoming_deferred = {
        key: {"deferred_at": datetime.now(timezone.utc).isoformat()}
        for key in (req.deferred_fields or [])
        if key in FIELD_SCHEMA
    }
    if incoming_deferred:
        deferred_fields.update(incoming_deferred)
        await loop.run_in_executor(None, upsert_deferred_fields, session_id, incoming_deferred)

    previous_active = workflow.get("active_field")
    classification: ClassifierResult = {
        "classification": "not_answered",
        "value": None,
        "confidence": 0.0,
        "proactive_fields": {},
        "coverage_gaps": [],
    }

    solution_type_value: str | None = (
        ((discovery_state or {}).get("fields") or {}).get("solution_type", {}).get("value")
    )

    tail_text = _build_conversation_tail(session, req.message)
    if workflow.get("phase") == "wrap_up":
        if _is_finalize_choice(req.message):
            workflow["phase"] = "ready_to_finalize"
            workflow["active_field"] = None
        else:
            await _reopen_first_deferred_field(
                session_id=session_id,
                workflow=workflow,
                deferred_fields=deferred_fields,
            )
    elif previous_active:
        classification, discovery_state = await _classify_and_update_active_field(
            session_id=session_id,
            field_key=previous_active,
            message=req.message,
            tail_text=tail_text,
            solution_type=solution_type_value,
            workflow=workflow,
            discovery_state=discovery_state,
            direct_fields=direct_fields,
            deferred_fields=deferred_fields,
        )
        discovery_state = await _apply_proactive_updates(
            session_id=session_id,
            classification=classification,
            active_field=previous_active,
            workflow=workflow,
            discovery_state=discovery_state,
        )

    if workflow.get("phase") == "ready_to_finalize":
        active_field = None
    else:
        active_field = pick_next_active_field(
            workflow,
            discovery_state,
            direct_fields,
            deferred_fields,
        )
        if active_field is None:
            workflow["phase"] = "wrap_up"
        elif workflow.get("phase") != "wrap_up":
            workflow["phase"] = "discovery"
        workflow["active_field"] = active_field

    # Treat disallowed not-applicable statuses as deferred to avoid required-field skips.
    for key, status in list(workflow.get("field_status", {}).items()):
        if status == "not_applicable" and not is_not_applicable_allowed(key):
            workflow["field_status"][key] = "deferred"

    await loop.run_in_executor(None, upsert_workflow_state, session_id, workflow)

    answered_values = _answered_field_values(discovery_state, direct_fields)
    active_field_for_ctx = workflow.get("active_field")
    coverage_gaps_map = workflow.get("coverage_gaps") or {}
    workflow_context = {
        "phase": workflow.get("phase"),
        "active_field": active_field_for_ctx,
        "clarification_requested": classification["classification"] == "clarification_requested",
        "miss_count": int((workflow.get("miss_counts") or {}).get(active_field_for_ctx) or 0),
        "answered_fields": answered_values,
        "deferred_fields": list(deferred_fields.keys()),
        "ready_to_finalize": workflow.get("phase") == "ready_to_finalize",
        "active_field_coverage_gaps": list(coverage_gaps_map.get(active_field_for_ctx) or []),
        "previous_field_coverage_gaps": list(coverage_gaps_map.get(previous_active) or []) if previous_active else [],
    }

    return {
        "workflow": workflow,
        "workflow_context": workflow_context,
        "direct_fields": direct_fields,
        "deferred_fields": list(deferred_fields.keys()),
        "classification": classification,
        "tail_text": tail_text,
        "solution_type": solution_type_value,
    }


# --- Request / response models ---


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    user_id: str = "default_user"
    direct_fields: dict[str, str] | None = None
    deferred_fields: list[str] | None = None


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    message_id: str


class FeedbackRequest(BaseModel):
    session_id: str
    message_id: str
    vote: Literal["up", "down"]
    comment: str | None = None


class FeedbackCommentRequest(BaseModel):
    session_id: str
    comment: str | None = None


class SessionFeedbackRequest(BaseModel):
    session_id: str
    rating: int
    comment: str | None = None


class AdminSessionSummary(BaseModel):
    id: str
    session_id: str
    project_name: str
    message_count: int
    cost_usd: float
    dominant_feedback: str
    thumbs_down_count: int
    thumbs_up_count: int
    session_rating: int | None = None
    updated_at: str | None = None
    trace_id: str | None = None
    cloud_trace_url: str | None = None


class AdminMessageFeedback(BaseModel):
    vote: str
    comment_redacted: str | None = None


class AdminTranscriptMessage(BaseModel):
    message_id: str | None = None
    role: str
    text_redacted: str
    created_at: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    model: str | None = None
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cost_usd: float
    ttft_ms: int | None = None
    itl_ms: int | None = None
    latency_ms: int | None = None
    tool_calls: list[dict]
    phase: str | None = None
    finish_reason: str | None = None
    feedback: AdminMessageFeedback | None = None
    cloud_trace_url: str | None = None


class AdminSessionDetail(BaseModel):
    id: str
    session_id: str
    project_name: str
    message_count: int
    cost_usd: float
    trace_id: str | None = None
    cloud_trace_url: str | None = None
    messages: list[AdminTranscriptMessage]


class AdminMetricsSource(BaseModel):
    messages_view: str
    feedback_view: str


class AdminMetricsSummary(BaseModel):
    sessions: int
    messages: int
    assistant_messages: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cost_usd: float
    avg_ttft_ms: float | None = None
    p50_ttft_ms: float | None = None
    p95_ttft_ms: float | None = None
    avg_itl_ms: float | None = None
    p50_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    safety_finishes: int
    thumbs_up: int
    thumbs_down: int
    avg_session_rating: float | None = None


class AdminModelMetric(BaseModel):
    model: str
    phase: str
    calls: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cost_usd: float
    avg_ttft_ms: float | None = None
    p95_ttft_ms: float | None = None
    avg_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    safety_finishes: int


class AdminDailyMetric(BaseModel):
    date: str
    sessions: int
    assistant_messages: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cost_usd: float
    avg_ttft_ms: float | None = None
    p95_latency_ms: float | None = None


class AdminMetricsResponse(BaseModel):
    window_days: int
    generated_at: str
    source: AdminMetricsSource
    summary: AdminMetricsSummary
    by_model: list[AdminModelMetric]
    daily: list[AdminDailyMetric]


@dataclass
class StreamReplyState:
    reply_parts: list[str] = field(default_factory=list)
    chunk_times: list[float] = field(default_factory=list)
    cost_aborted: bool = False
    stream_started_at: float = field(default_factory=time.perf_counter)
    ttft_recorded: bool = False


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
    req: ChatRequest,
    user_content: types.Content,
    session_id: str,
    state: StreamReplyState,
) -> AsyncIterator[str]:
    try:
        async for event in runner.run_async(
            user_id=req.user_id,
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


async def _chat_stream_event_generator(
    *,
    req: ChatRequest,
    session_id: str,
    workflow_turn: dict,
    user_content: types.Content,
) -> AsyncIterator[str]:
    message_id = str(uuid.uuid4())
    trace_id, span_id = _current_trace_ids()
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
            req=req,
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

    asyncio.create_task(
        _run_turn_postprocessing(
            session_id=session_id,
            user_id=req.user_id,
            user_text=req.message,
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


# --- Endpoints ---


@app.get("/health")
def health():
    return {"status": "ok"}


# --- File upload endpoint ---


class UploadResponse(BaseModel):
    gcs_path: str
    filename: str


class SessionUpload(BaseModel):
    filename: str
    gcs_path: str


class SessionUploadsResponse(BaseModel):
    session_id: str
    files: list[SessionUpload]


_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


@app.post("/upload", response_model=UploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    session_id: str = Form(...),
):
    """Upload a file to GCS under sessions/{session_id}/{filename}."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is missing")

    try:
        safe_session_id = sanitize_gcs_segment(session_id, field_name="session_id")
        safe_filename = sanitize_gcs_filename(file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    destination = f"{GCS_PREFIX_SESSIONS}/{safe_session_id}/{safe_filename}"
    contents = await file.read()
    if len(contents) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(f"File exceeds maximum allowed size of {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB."),
        )
    logger.info(f"Upload received: file={safe_filename} size={len(contents)}B session_id={safe_session_id}")
    gcs_path = write_file(
        path=destination,
        data=contents,
        content_type=file.content_type or "application/octet-stream",
    )
    logger.debug(f"File uploaded to GCS: {gcs_path}")
    return UploadResponse(gcs_path=gcs_path, filename=safe_filename)


@app.get("/uploads/{session_id}", response_model=SessionUploadsResponse)
async def session_uploads(session_id: str):
    """List files stored in GCS under sessions/{session_id}/."""
    try:
        safe_session_id = sanitize_gcs_segment(session_id, field_name="session_id")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    prefix = f"{GCS_PREFIX_SESSIONS}/{safe_session_id}/"
    try:
        paths = list_files(prefix=prefix)
    except Exception as exc:
        logger.error(
            f"Failed to list session uploads: session_id={safe_session_id} error={exc}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=502,
            detail="Could not list uploaded files for this session.",
        ) from exc

    bucket_name = get_bucket_name()
    files = [
        SessionUpload(
            filename=path.split("/")[-1],
            gcs_path=f"gs://{bucket_name}/{path}",
        )
        for path in paths
        if path.split("/")[-1]
    ]
    return SessionUploadsResponse(session_id=safe_session_id, files=files)


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Send a message to the RS consultant agent and get a response."""

    session_id = req.session_id or str(uuid.uuid4())
    _mark_session_seen(session_id)
    try:
        _run_safety_preflight(req.message, session_id)
    except (CostCircuitBreakerTripped, UnsafePromptBlocked) as exc:
        raise _safety_http_error(exc) from exc
    logger.debug(f"Chat request: session_id={session_id} user_id={req.user_id}")
    loop = asyncio.get_running_loop()

    # Ensure session exists
    session = await session_service.get_session(
        app_name=APP_NAME,
        user_id=req.user_id,
        session_id=session_id,
    )
    if session is None:
        session = await session_service.create_session(
            app_name=APP_NAME,
            user_id=req.user_id,
            session_id=session_id,
        )
        logger.info(f"New session created: {session_id}")
    else:
        logger.debug(f"Resumed existing session: {session_id}")

    stored_direct_fields = await loop.run_in_executor(None, get_direct_fields, session_id)
    direct_fields = merge_direct_fields(stored_direct_fields, req.direct_fields)
    if req.direct_fields:
        await loop.run_in_executor(None, upsert_direct_fields, session_id, req.direct_fields)

    workflow_turn = await _prepare_workflow_turn(
        session_id=session_id,
        req=req,
        session=session,
        direct_fields=direct_fields,
    )

    user_content = types.Content(
        role="user",
        parts=[
            types.Part.from_text(
                text=build_augmented_user_message(
                    req.message,
                    workflow_turn["direct_fields"],
                    workflow_turn["deferred_fields"],
                    workflow_context=workflow_turn["workflow_context"],
                    field_labels=FIELD_LABELS,
                )
            )
        ],
    )

    # Collect the agent's final text response
    message_id = str(uuid.uuid4())
    trace_id, span_id = _current_trace_ids()
    turn_token = start_turn(session_id=session_id, message_id=message_id, phase="chat")
    turn_t0 = time.perf_counter()
    reply_parts: list[str] = []
    turn_summary: dict = {}
    try:
        async for event in runner.run_async(
            user_id=req.user_id,
            session_id=session_id,
            new_message=user_content,
        ):
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        reply_parts.append(part.text)
        set_stream_timings(latency_ms=int((time.perf_counter() - turn_t0) * 1000))
        turn_summary = summarize_turn(current_turn())
    except CostCircuitBreakerTripped as exc:
        turn_summary = summarize_turn(current_turn())
        logger.warning(f"Chat aborted by cost circuit: session_id={session_id} cost_usd={exc.cost_usd:.6f}")
        raise HTTPException(status_code=429, detail=FRIENDLY_COST_ERROR) from exc
    finally:
        reset_turn(turn_token)

    reply = "".join(reply_parts)
    logger.info(f"Agent reply ready: session_id={session_id} reply_chars={len(reply)}")

    loop.run_in_executor(
        None,
        partial(
            append_conversation_turn,
            session_id,
            req.message,
            reply,
            message_id=message_id,
            trace_id=trace_id,
            span_id=span_id,
            **turn_summary,
        ),
    )

    return ChatResponse(reply=reply, session_id=session_id, message_id=message_id)


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    """Stream the agent's response as Server-Sent Events."""

    session_id = req.session_id or str(uuid.uuid4())
    _mark_session_seen(session_id)
    try:
        _run_safety_preflight(req.message, session_id)
    except CostCircuitBreakerTripped:
        return _safety_error_stream(session_id, FRIENDLY_COST_ERROR)
    except UnsafePromptBlocked:
        return _safety_error_stream(session_id, FRIENDLY_PROMPT_ERROR)
    logger.debug(f"Stream chat request: session_id={session_id} user_id={req.user_id}")
    loop = asyncio.get_running_loop()

    session = await session_service.get_session(
        app_name=APP_NAME,
        user_id=req.user_id,
        session_id=session_id,
    )
    if session is None:
        session = await session_service.create_session(
            app_name=APP_NAME,
            user_id=req.user_id,
            session_id=session_id,
        )
        logger.info(f"New session created: {session_id}")
    else:
        logger.debug(f"Resumed existing session: {session_id}")

    stored_direct_fields = await loop.run_in_executor(None, get_direct_fields, session_id)
    direct_fields = merge_direct_fields(stored_direct_fields, req.direct_fields)
    if req.direct_fields:
        await loop.run_in_executor(None, upsert_direct_fields, session_id, req.direct_fields)

    workflow_turn = await _prepare_workflow_turn(
        session_id=session_id,
        req=req,
        session=session,
        direct_fields=direct_fields,
    )

    user_content = types.Content(
        role="user",
        parts=[
            types.Part.from_text(
                text=build_augmented_user_message(
                    req.message,
                    workflow_turn["direct_fields"],
                    workflow_turn["deferred_fields"],
                    workflow_context=workflow_turn["workflow_context"],
                    field_labels=FIELD_LABELS,
                )
            )
        ],
    )

    return StreamingResponse(
        _chat_stream_event_generator(
            req=req,
            session_id=session_id,
            workflow_turn=workflow_turn,
            user_content=user_content,
        ),
        media_type="text/event-stream",
    )


@app.post("/feedback")
async def submit_feedback(req: FeedbackRequest):
    """Persist thumbs feedback for a saved assistant message."""
    loop = asyncio.get_running_loop()
    feedback = None
    for attempt in range(4):
        try:
            feedback = await loop.run_in_executor(
                None,
                partial(
                    upsert_message_feedback,
                    session_id=req.session_id,
                    message_id=req.message_id,
                    vote=req.vote,
                    comment=req.comment,
                ),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if feedback is not None:
            break
        if attempt < 3:
            await asyncio.sleep(0.4)

    if feedback is None:
        raise HTTPException(status_code=404, detail="Assistant message not found")

    phase = str(feedback.get("phase") or "chat")
    record_feedback_vote(vote=req.vote, phase=phase)
    logger.info(
        "User feedback recorded: "
        f"event=user_feedback session_id={req.session_id} "
        f"message_id={req.message_id} vote={req.vote} phase={phase}"
    )
    return {"status": "ok"}


@app.patch("/feedback/{message_id}")
async def patch_feedback(message_id: str, req: FeedbackCommentRequest):
    """Attach or replace the free-text comment on an existing feedback vote."""
    loop = asyncio.get_running_loop()
    feedback = await loop.run_in_executor(
        None,
        partial(
            update_feedback_comment,
            session_id=req.session_id,
            message_id=message_id,
            comment=req.comment,
        ),
    )
    if feedback is None:
        raise HTTPException(status_code=404, detail="Feedback not found")

    logger.info(
        "User feedback comment updated: "
        f"event=user_feedback_comment session_id={req.session_id} "
        f"message_id={message_id}"
    )
    return {"status": "ok"}


@app.post("/feedback/session")
async def submit_session_feedback(req: SessionFeedbackRequest):
    """End a chat session and persist its overall conversation rating."""
    loop = asyncio.get_running_loop()
    try:
        feedback = await loop.run_in_executor(
            None,
            partial(
                upsert_session_feedback,
                session_id=req.session_id,
                rating=req.rating,
                comment=req.comment,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if feedback is None:
        raise HTTPException(status_code=404, detail="Session not found")

    _record_session_outcome(req.session_id, "abandoned")
    record_feedback_vote(vote=f"rating_{req.rating}", phase="session")
    logger.info(f"Session feedback recorded: event=session_feedback session_id={req.session_id} rating={req.rating}")
    return {"status": "ok"}


# --- Document generation & export endpoints ---


class SessionRef(BaseModel):
    session_id: str
    user_id: str = "default_user"


class DocumentResponse(BaseModel):
    markdown: str | None
    ready: bool


@app.post("/document", response_model=DocumentResponse)
async def get_document(req: SessionRef):
    """Extract the generated RS document from a session.

    Returns the markdown if [GENERATE_RS] was found in the conversation,
    otherwise returns ready=False.
    """
    t0 = time.perf_counter()
    markdown = await compile_rs_from_session(
        session_service=session_service,
        app_name=APP_NAME,
        user_id=req.user_id,
        session_id=req.session_id,
    )
    record_operation_duration(
        time.perf_counter() - t0,
        model="none",
        operation="document.compile",
        status="ready" if markdown is not None else "not_ready",
    )
    return DocumentResponse(
        markdown=markdown,
        ready=markdown is not None,
    )


@app.post("/document/pdf")
async def download_pdf(req: SessionRef):
    """Download the RS document as a PDF.

    Extracts the RS markdown from the session and converts it to PDF.
    Returns 404 if no document has been generated yet.
    """
    t0 = time.perf_counter()
    status = "ok"
    markdown = await compile_rs_from_session(
        session_service=session_service,
        app_name=APP_NAME,
        user_id=req.user_id,
        session_id=req.session_id,
    )
    if markdown is None:
        status = "not_ready"
        record_operation_duration(
            time.perf_counter() - t0,
            model="none",
            operation="document.pdf",
            status=status,
        )
        logger.warning(f"PDF export requested but no RS document found: session_id={req.session_id}")
        raise HTTPException(
            status_code=404,
            detail="No RS document found. Complete the conversation first.",
        )

    logger.info(f"Generating PDF export: session_id={req.session_id}")
    pdf_bytes = markdown_to_pdf(markdown)
    record_operation_duration(
        time.perf_counter() - t0,
        model="none",
        operation="document.pdf",
        status=status,
    )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=requirement_specification.pdf"},
    )


@app.post("/document/docx")
async def download_docx(req: SessionRef):
    """Generate and download the SRS as a populated Word (.docx) document.

    Uses Gemini to compile the full SRS structure from the conversation,
    then writes it into a Word document using the SRS template structure.
    Returns 404 if the session is not found, 422 if compilation fails.
    """
    t0 = time.perf_counter()
    status = "ok"
    srs_json = await compile_srs_json_from_session(
        session_service=session_service,
        app_name=APP_NAME,
        user_id=req.user_id,
        session_id=req.session_id,
    )
    if srs_json is None:
        status = "compile_failed"
        record_operation_duration(
            time.perf_counter() - t0,
            model="none",
            operation="document.docx",
            status=status,
        )
        logger.warning(f"DOCX export failed — SRS could not be compiled: session_id={req.session_id}")
        raise HTTPException(
            status_code=422,
            detail="Could not compile SRS from the conversation. Keep chatting to provide more details.",
        )

    logger.info(f"Generating DOCX export: session_id={req.session_id}")
    docx_bytes = srs_json_to_docx(srs_json)
    record_operation_duration(
        time.perf_counter() - t0,
        model="none",
        operation="document.docx",
        status=status,
    )

    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": "attachment; filename=requirement_specification.docx"},
    )


@app.post("/document/rs-template/docx")
async def download_rs_template_docx(req: SessionRef):
    """Generate a Word doc from the 22 RSLiveTemplate fields.

    Save to GCS and return it for download.
    """
    t0 = time.perf_counter()
    loop = asyncio.get_running_loop()
    # Use only user-confirmed direct fields as the source of truth.
    # AI-extracted values are never written to the document unless the user
    # explicitly accepted them in the Preview.
    direct = await loop.run_in_executor(None, get_direct_fields, req.session_id)
    fields: dict = {
        key: {"filled": True, "value": value, "source": "user"}
        for key, value in direct.items()
        if value and str(value).strip()
    }

    docx_bytes = rs_template_to_docx(fields)

    gcs_path = f"{GCS_PREFIX_SESSIONS}/{req.session_id}/rs_template.docx"
    await loop.run_in_executor(
        None,
        lambda: write_file(
            gcs_path,
            docx_bytes,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
    )
    logger.info(f"RS template DOCX saved to GCS: {gcs_path}")
    record_operation_duration(
        time.perf_counter() - t0,
        model="none",
        operation="document.rs_template_docx",
        status="ok",
    )

    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": "attachment; filename=rs_template.docx",
            "X-GCS-Path": f"gs://{get_bucket_name()}/{gcs_path}",
        },
    )


# --- BPMN diagram generation ---


class BpmnRequest(BaseModel):
    session_id: str
    user_id: str = "default_user"


class BpmnResponse(BaseModel):
    ready: bool
    mermaid: str | None = None
    score: int | None = None
    missing: list[str] | None = None


@app.post("/bpmn/generate", response_model=BpmnResponse)
async def bpmn_generate(req: BpmnRequest):
    """Check RS completeness and generate a Mermaid BPMN diagram if ≥ 90%."""
    t0 = time.perf_counter()
    session = await session_service.get_session(
        app_name=APP_NAME,
        user_id=req.user_id,
        session_id=req.session_id,
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    conversation_text = extract_conversation_text(session)

    completeness = await check_completeness(conversation_text)
    score: int = completeness.get("score", 0)
    missing: list[str] = completeness.get("missing", [])
    logger.info(f"BPMN completeness check: session_id={req.session_id} score={score}%")

    if score < 90:
        logger.debug(f"BPMN not ready (score < 90): missing={missing}")
        record_operation_duration(
            time.perf_counter() - t0,
            model=MODEL_ORCHESTRATOR,
            operation="diagram.bpmn",
            status="not_ready",
        )
        return BpmnResponse(ready=False, score=score, missing=missing)

    logger.info(f"Generating BPMN diagram: session_id={req.session_id}")
    mermaid = await generate_bpmn_diagram(conversation_text)
    record_operation_duration(
        time.perf_counter() - t0,
        model=MODEL_ORCHESTRATOR,
        operation="diagram.bpmn",
        status="ok",
    )
    return BpmnResponse(ready=True, mermaid=mermaid, score=score)


# --- DataFlow diagram generation ---


class DataflowRequest(BaseModel):
    session_id: str
    user_id: str = "default_user"


class DataflowResponse(BaseModel):
    ready: bool
    mermaid: str | None = None
    score: int | None = None
    missing: list[str] | None = None


@app.post("/dataflow/generate", response_model=DataflowResponse)
async def dataflow_generate(req: DataflowRequest):
    """Check DFD readiness and generate a Mermaid Data Flow Diagram if score ≥ 70%."""
    t0 = time.perf_counter()
    session = await session_service.get_session(
        app_name=APP_NAME,
        user_id=req.user_id,
        session_id=req.session_id,
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    conversation_text = extract_conversation_text(session)

    completeness = await check_dfd_completeness(conversation_text)
    score: int = completeness.get("score", 0)
    missing: list[str] = completeness.get("missing", [])
    logger.info(f"Dataflow completeness check: session_id={req.session_id} score={score}%")

    if score < 70:
        logger.debug(f"Dataflow not ready (score < 70): missing={missing}")
        record_operation_duration(
            time.perf_counter() - t0,
            model=MODEL_ORCHESTRATOR,
            operation="diagram.dataflow",
            status="not_ready",
        )
        return DataflowResponse(ready=False, score=score, missing=missing)

    logger.info(f"Generating Dataflow diagram: session_id={req.session_id}")
    mermaid = await generate_dataflow_diagram(conversation_text)
    record_operation_duration(
        time.perf_counter() - t0,
        model=MODEL_ORCHESTRATOR,
        operation="diagram.dataflow",
        status="ok",
    )
    return DataflowResponse(ready=True, mermaid=mermaid, score=score)


# --- Live RS context extraction ---


class ContextRequest(BaseModel):
    session_id: str
    user_id: str = "default_user"


class FieldData(BaseModel):
    filled: bool
    value: str | None
    source: str | None = None  # "user" | "ai" | "upload" | null


class ContextResponse(BaseModel):
    completeness: int
    fields: dict[str, FieldData]


@app.post("/context/extract", response_model=ContextResponse)
async def context_extract(req: ContextRequest):
    """Extract all 22 discovery form fields from the current conversation.

    Calls Gemini Flash to map what has been discussed into the 22-field schema.
    Always returns all 22 field keys.

    Per-session deduplication: if an extraction is already in-flight for this
    session, subsequent requests wait for that result instead of spawning
    parallel Gemini calls.  This is critical in voice mode where turn_complete
    events arrive much faster than the ~40s extraction call.

    Fallback order when the ADK session is missing (e.g. after a backend restart
    or when loading a historical session that was never replayed in ADK):
      1. Try the ADK InMemorySessionService — extract fresh from live events.
      2. If not found, return the last saved discovery state from Firestore.
      3. If nothing saved yet, return empty state (completeness=0).
    """
    sid = req.session_id
    try:
        assert_session_within_budget(sid)
    except CostCircuitBreakerTripped as exc:
        raise HTTPException(status_code=429, detail=FRIENDLY_COST_ERROR) from exc

    try:
        session = await session_service.get_session(
            app_name=APP_NAME,
            user_id=req.user_id,
            session_id=sid,
        )
    except Exception as exc:
        logger.error(
            f"Failed to get session for extraction: session_id={sid}: {exc}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=f"Session lookup failed: {type(exc).__name__}")

    if session is None:
        # ADK session gone — return last persisted discovery state if available
        try:
            loop = asyncio.get_running_loop()
            saved = await loop.run_in_executor(None, get_discovery_state, sid)
        except Exception as exc:
            logger.error(f"Firestore fallback failed for session_id={sid}: {exc}", exc_info=True)
            raise HTTPException(status_code=502, detail=f"Firestore unavailable: {type(exc).__name__}")
        if saved:
            logger.info(
                "ADK session missing, returning saved discovery state: "
                f"session_id={sid} "
                f"completeness={saved.get('completeness')}%"
            )
            return {"completeness": saved["completeness"], "fields": saved["fields"]}
        logger.info(f"No ADK session and no saved state for session_id={sid}")
        return {"completeness": 0, "fields": {}}

    # --- Per-session dedup lock ---
    # Ensure only one Gemini extraction runs per session at a time.
    # Additional callers wait for the lock and then read the freshly
    # persisted result from Firestore (avoids a second Gemini call).
    new_lock = asyncio.Lock()
    lock = _extract_locks.setdefault(sid, new_lock)
    # Keep a strong local reference so the WeakValueDictionary entry stays
    # alive for the duration of this request (del new_lock is fine here).

    if lock.locked():
        # Another extraction is already running for this session.
        # Wait for it to finish, then return the persisted result.
        logger.info(f"Extraction already in-flight, waiting for lock: session_id={sid}")
        async with lock:
            # The first caller has finished and persisted the result.
            loop = asyncio.get_running_loop()
            try:
                saved = await loop.run_in_executor(None, get_discovery_state, sid)
            except Exception as exc:
                logger.warning(f"Firestore get_discovery_state (coalesced) failed: session_id={sid} {exc}")
                saved = None
            if saved:
                logger.info(
                    f"Returning coalesced extraction result: session_id={sid} completeness={saved.get('completeness')}%"
                )
                return {
                    "completeness": saved["completeness"],
                    "fields": saved["fields"],
                }
            return {"completeness": 0, "fields": {}}

    async with lock:
        # Re-fetch session inside the lock to pick up events that were
        # appended between the initial get_session() and acquiring the lock
        # (e.g. SessionBridge injections that run before turn_complete).
        session = await session_service.get_session(
            app_name=APP_NAME,
            user_id=req.user_id,
            session_id=sid,
        )
        if session is None:
            logger.warning(f"Session disappeared during extraction: session_id={sid}")
            return {"completeness": 0, "fields": {}}

        conversation_text = extract_conversation_text(session)
        logger.info(
            f"Conversation text for extraction: session_id={sid} "
            f"events={len(session.events)} text_len={len(conversation_text)} "
            f"preview={conversation_text[:200]!r}"
        )
        try:
            loop = asyncio.get_running_loop()
            _saved_state = await loop.run_in_executor(None, get_discovery_state, sid)
            _sol_type: str | None = ((_saved_state or {}).get("fields") or {}).get("solution_type", {}).get("value")
            result = await extract_discovery_fields(conversation_text, session_id=sid, solution_type=_sol_type)
        except CostCircuitBreakerTripped as exc:
            raise HTTPException(status_code=429, detail=FRIENDLY_COST_ERROR) from exc
        logger.info(f"Discovery fields extracted: session_id={sid} completeness={result.get('completeness')}%")

        # Fire-and-forget: persist discovery state + full SRS to Firestore
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, upsert_discovery_state, sid, result)
        except Exception as exc:
            logger.warning(f"Firestore upsert_discovery_state failed: session_id={sid} {exc}")

        asyncio.create_task(
            _persist_srs_to_firestore(
                session_id=sid,
                user_id=req.user_id,
            )
        )

        # Return merged state: direct fields overlay AI-extracted fields
        try:
            merged = await loop.run_in_executor(None, get_discovery_state, sid)
        except Exception as exc:
            logger.warning(f"Firestore get_discovery_state failed: session_id={sid} {exc}")
            merged = None
        if merged:
            return {"completeness": merged["completeness"], "fields": merged["fields"]}
        return {"completeness": result["completeness"], "fields": result["fields"]}


@app.get("/discovery/{session_id}", response_model=ContextResponse)
async def discovery_state(session_id: str):
    """Return the last saved 22-field discovery state for *session_id*.

    Used by the frontend when loading a historical session to restore the
    Preview panel without re-running Gemini extraction.
    Returns completeness=0 with empty fields if nothing has been saved yet.
    """
    loop = asyncio.get_running_loop()
    saved = await loop.run_in_executor(None, get_discovery_state, session_id)
    if saved:
        logger.debug(f"Discovery state retrieved: session_id={session_id} completeness={saved.get('completeness')}%")
        return {"completeness": saved["completeness"], "fields": saved["fields"]}
    logger.debug(f"No saved discovery state for session_id={session_id}")
    return {"completeness": 0, "fields": {}}


class DirectFieldsPatch(BaseModel):
    fields: dict[str, str]


@app.patch("/discovery/{session_id}/fields", response_model=ContextResponse)
async def patch_direct_fields(session_id: str, body: DirectFieldsPatch):
    """Directly set field values, bypassing AI extraction.

    These values are stored in a separate Firestore key (direct_fields_json)
    so subsequent AI extraction runs never erase them.  The merged state
    (direct + AI) is returned so the frontend can update completeness
    immediately without a separate polling call.
    """
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, upsert_direct_fields, session_id, body.fields)
    logger.info(f"Direct fields patched: session_id={session_id} keys={list(body.fields.keys())}")
    merged = await loop.run_in_executor(None, get_discovery_state, session_id)
    if merged:
        return {"completeness": merged["completeness"], "fields": merged["fields"]}
    return {"completeness": 0, "fields": {}}


async def _persist_srs_to_firestore(session_id: str, user_id: str) -> None:
    """Compile the full SRS JSON and upsert it into Firestore.

    Runs in the background — failures are logged and never surface to the user.
    """
    try:
        srs_json = await compile_srs_json_from_session(
            session_service=session_service,
            app_name=APP_NAME,
            user_id=user_id,
            session_id=session_id,
        )
        if srs_json:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, upsert_srs_fields, session_id, srs_json)
            logger.debug(f"SRS persisted to Firestore: session_id={session_id}")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Firestore SRS upsert failed: session_id={session_id} error={exc}")


# --- Firestore data retrieval ---


@app.get("/admin/metrics", response_model=AdminMetricsResponse)
async def admin_metrics(
    _: None = Depends(require_admin),
    days: int = Query(default=7, ge=1, le=90),
):
    """Return BigQuery-backed LLM observability aggregates for the admin UI."""
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, partial(get_admin_metrics, days=days))
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Admin metrics query failed: {exc}", exc_info=True)
        raise HTTPException(
            status_code=502,
            detail="Could not query admin metrics from BigQuery.",
        ) from exc


@app.get("/admin/sessions", response_model=list[AdminSessionSummary])
async def admin_sessions_list(
    _: None = Depends(require_admin),
    limit: int = Query(default=50, ge=1, le=200),
    filter: Literal["thumbs_down"] | None = None,
):
    """Return BigQuery session summaries for the self-hosted review UI."""
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(
            None,
            partial(list_admin_sessions, limit=limit, filter_value=filter),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Admin sessions query failed: {exc}", exc_info=True)
        raise HTTPException(
            status_code=502,
            detail="Could not query admin sessions from BigQuery.",
        ) from exc


@app.get("/admin/sessions/{session_id}", response_model=AdminSessionDetail)
async def admin_session_detail(
    session_id: str,
    _: None = Depends(require_admin),
):
    """Return a full BigQuery transcript for the self-hosted review UI."""
    loop = asyncio.get_running_loop()
    try:
        detail = await loop.run_in_executor(None, get_admin_session, session_id)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            f"Admin session detail query failed: session_id={session_id} error={exc}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=502,
            detail="Could not query admin session from BigQuery.",
        ) from exc
    if detail is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return detail


class FirestoreDataResponse(BaseModel):
    session_id: str
    data: dict | None = None


class SessionSummary(BaseModel):
    session_id: str
    updated_at: str | None = None
    preview: str | None = None


@app.get("/sessions", response_model=list[SessionSummary])
async def sessions_list():
    """Return a summary list of all stored sessions."""
    loop = asyncio.get_running_loop()
    items = await loop.run_in_executor(None, list_sessions)
    return items


class HistoryResponse(BaseModel):
    session_id: str
    messages: list[dict]


@app.get("/history/{session_id}", response_model=HistoryResponse)
async def get_history(session_id: str):
    """Return the full conversation history for *session_id*."""
    loop = asyncio.get_running_loop()
    messages = await loop.run_in_executor(None, get_conversation_history, session_id)
    return HistoryResponse(session_id=session_id, messages=messages)


# --- Final analysis endpoint ---

# TODO: add AnalysisResponse model once final_analysis schema is finalized
#       (mirrors FINAL_ANALYSIS_SCHEMA in agent/finalizer_agent.py)


@app.get("/analyses/{session_id}")
async def get_analysis(session_id: str):
    """Return the finalized analysis for a session, or status if still pending.

    The frontend polls this endpoint every 5 s after receiving the
    "finalizing" SSE event.

    Returns:
      {"status": "not_found"}                          — finalization never triggered
      {"status": "pending"}                            — run_finalizer() still running
      {"status": "error"}                              — pipeline failed
      {"status": "complete", "analysis": {...}}        — done, full analysis included
    """
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, get_final_analysis, session_id)

    if result is None:
        return {"status": "not_found"}

    status = result.get("finalization_status", "not_found")

    if status == "complete":
        # Remove the internal status flag before returning to frontend
        result.pop("finalization_status", None)
        logger.info(f"Analysis ready: session_id={session_id}")
        return {"status": "complete", "analysis": result}

    logger.debug(f"Analysis poll: session_id={session_id} status={status}")
    return {"status": status}


@app.get("/firestore/data/{session_id}", response_model=FirestoreDataResponse)
async def firestore_data(session_id: str):
    """Return the latest SRS data stored in Firestore for *session_id*.

    The frontend polls this endpoint after each turn to refresh the right panel.
    Returns data=null if no document has been written yet.
    """
    try:
        loop = asyncio.get_running_loop()
        doc = await loop.run_in_executor(None, get_srs_fields, session_id)
    except Exception as exc:
        logger.error(
            f"Firestore read failed: event=firestore_unavailable_total session_id={session_id} {exc}",
            exc_info=True,
        )
        raise HTTPException(status_code=502, detail=f"Firestore unavailable: {type(exc).__name__}")
    return FirestoreDataResponse(session_id=session_id, data=doc)


# --- Bidirectional audio WebSocket endpoint ---


async def _run_turn_postprocessing(
    session_id: str,
    user_id: str,
    user_text: str,
    assistant_text: str,
    is_finalizing: bool,
    *,
    fallback_transcript: str | None = None,
    message_id: str | None = None,
    trace_id: str | None = None,
    span_id: str | None = None,
    turn_summary: dict | None = None,
) -> None:
    """Shared post-processing pipeline for a completed conversation turn.

    Called by both voice and text chat paths.  Executes these steps:

      1. Persist conversation turn to Firestore (fire-and-forget)
      2. Launch finalizer (if [FINALIZING] detected) — includes its own
         discovery extraction so the heavy Gemini call only happens once

    Discovery field extraction and SRS compilation are NOT done here — the
    frontend triggers those via ``POST /context/extract`` after each turn.
    This avoids duplicate Gemini calls (backend + frontend both extracting).

    Parameters
    ----------
    fallback_transcript:
        Used when the ADK session snapshot is unavailable.  Defaults to a
        simple ``User: / Consultant:`` formatted string.
    """
    loop = asyncio.get_running_loop()

    # 1. Persist conversation turn to Firestore
    if user_text or assistant_text:
        turn_summary = turn_summary or {}
        loop.run_in_executor(
            None,
            partial(
                append_conversation_turn,
                session_id,
                user_text or "(voice input)",
                assistant_text,
                message_id=message_id,
                trace_id=trace_id,
                span_id=span_id,
                **turn_summary,
            ),
        )

    # 2. If [FINALIZING] detected, launch the finalizer pipeline
    #    The finalizer needs discovery fields + conversation transcript,
    #    so we extract them here (only on finalization, not every turn).
    if is_finalizing:
        _record_session_outcome(session_id, "finalized")
        logger.info(f"[FINALIZING] detected: session={session_id} — launching finalizer")
        loop.run_in_executor(None, set_finalization_pending, session_id)

        # Build conversation transcript for the finalizer
        session_snap = await session_service.get_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=session_id,
        )
        conversation_text = (
            extract_conversation_text(session_snap)
            if session_snap
            else (fallback_transcript or f"User: {user_text}\nConsultant: {assistant_text}")
        )

        # Extract discovery fields for the finalizer
        try:
            _fin_saved = await loop.run_in_executor(None, get_discovery_state, session_id)
            _fin_sol_type: str | None = ((_fin_saved or {}).get("fields") or {}).get("solution_type", {}).get("value")
            discovery_fields = await extract_discovery_fields(
                conversation_text,
                session_id=session_id,
                solution_type=_fin_sol_type,
            )
            logger.debug(
                f"Discovery fields for finalizer: session={session_id} "
                f"completeness={discovery_fields.get('completeness')}%"
            )
            loop.run_in_executor(None, upsert_discovery_state, session_id, discovery_fields)
        except CostCircuitBreakerTripped as exc:
            logger.warning(f"Finalizer skipped by cost circuit: session={session_id} cost_usd={exc.cost_usd:.6f}")
            loop.run_in_executor(None, set_finalization_error, session_id)
            return
        except Exception as exc:
            logger.warning(f"extract_discovery_fields failed: session={session_id} {exc}")
            discovery_fields = {
                "completeness": 0,
                "fields": {},
                "missing_priority": [],
            }

        asyncio.create_task(
            run_finalizer(
                session_id=session_id,
                user_id=user_id,
                conversation_text=conversation_text,
                discovery_fields=discovery_fields,
            )
        )


def _is_native_audio_model(model_name: str) -> bool:
    """Check if the model supports native audio input/output."""
    return "native-audio" in model_name


def _build_run_config() -> RunConfig:
    """Build a RunConfig for bidi audio streaming.

    Adapts response modalities and speech config depending on whether the
    audio model is a native-audio model or a half-cascade model.
    """
    is_native = _is_native_audio_model(MODEL_AUDIO)

    if is_native:
        # Native audio: model speaks audio directly
        run_config = RunConfig(
            streaming_mode=StreamingMode.BIDI,
            response_modalities=["AUDIO"],
            speech_config=SpeechConfig(
                voice_config=VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Aoede",
                    )
                )
            ),
            output_audio_transcription=AudioTranscriptionConfig(),
            input_audio_transcription=AudioTranscriptionConfig(),
        )
    else:
        # Half-cascade: model outputs text, TTS converts to audio
        run_config = RunConfig(
            streaming_mode=StreamingMode.BIDI,
            response_modalities=["AUDIO"],
            speech_config=SpeechConfig(
                voice_config=VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Aoede",
                    )
                )
            ),
        )

    return run_config


@app.websocket("/ws/{user_id}/{session_id}")
async def websocket_audio(websocket: WebSocket, user_id: str, session_id: str):
    """Bidirectional audio streaming over WebSocket.

    Protocol:
      - Binary frames = raw PCM audio (16kHz, 16-bit, mono) from the client
      - Text frames   = JSON messages for text/audio/end-of-turn fallbacks
      - Server sends binary PCM audio and JSON text/transcription events back
    """
    await websocket.accept()
    _mark_session_seen(session_id)
    logger.info(f"[WS] Connected: user={user_id} session={session_id}")

    try:
        await run_audio_websocket(
            websocket,
            user_id=user_id,
            session_id=session_id,
            run_config=_build_run_config(),
            deps=AudioWebsocketDeps(
                app_name=APP_NAME,
                finalizing_marker=FINALIZING_MARKER,
                session_service=session_service,
                session_bridge=session_bridge,
                audio_runner=audio_runner,
                run_turn_postprocessing=_run_turn_postprocessing,
                logger=logger,
            ),
        )
    except Exception as exc:
        logger.error(f"[WS] Connection error: {exc}", exc_info=True)
    finally:
        logger.info(f"[WS] Connection closed: user={user_id} session={session_id}")
