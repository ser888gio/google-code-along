from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
import weakref
from functools import partial
from typing import Literal

import runtime
from admin_sessions import (
    get_admin_metrics,
    get_admin_session,
    list_admin_sessions,
    require_admin,
)
from agent.discovery_agent import extract_discovery_fields
from audio_websocket import AudioWebsocketDeps, run_audio_websocket
from bpmn import check_completeness, generate_bpmn_diagram
from chat_classification import solution_type_value
from chat_streaming import chat_stream_event_generator
from chat_turn import load_voice_priming, prepare_workflow_turn, run_turn_postprocessing
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
from field_schema import FIELD_LABELS
from firestore import (
    append_conversation_turn,
    get_conversation_history,
    get_direct_fields,
    get_discovery_state,
    get_final_analysis,
    get_srs_fields,
    list_sessions,
    update_feedback_comment,
    upsert_direct_fields,
    upsert_discovery_state,
    upsert_message_feedback,
    upsert_session_feedback,
    upsert_srs_fields,
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
from google.genai import types
from google.genai.types import (
    AudioTranscriptionConfig,
    SpeechConfig,
    VoiceConfig,
)
from logger import get_logger, setup_logging
from observability.metrics import record_feedback_vote, record_operation_duration
from observability.safety import (
    FRIENDLY_COST_ERROR,
    FRIENDLY_PROMPT_ERROR,
    CostCircuitBreakerTripped,
    UnsafePromptBlocked,
    assert_session_within_budget,
    check_user_prompt_or_raise,
)
from observability.tracing import current_trace_ids, setup_telemetry
from observability.turns import (
    current_turn,
    reset_turn,
    set_stream_timings,
    start_turn,
    summarize_turn,
)
from pydantic import BaseModel
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
    runtime.mark_session_seen(session_id)
    try:
        _run_safety_preflight(req.message, session_id)
    except (CostCircuitBreakerTripped, UnsafePromptBlocked) as exc:
        raise _safety_http_error(exc) from exc
    logger.debug(f"Chat request: session_id={session_id} user_id={req.user_id}")
    loop = asyncio.get_running_loop()

    # Ensure session exists
    session = await runtime.session_service.get_session(
        app_name=APP_NAME,
        user_id=req.user_id,
        session_id=session_id,
    )
    if session is None:
        session = await runtime.session_service.create_session(
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

    workflow_turn = await prepare_workflow_turn(
        session_id=session_id,
        message=req.message,
        incoming_deferred=req.deferred_fields,
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
    trace_id, span_id = current_trace_ids()
    turn_token = start_turn(session_id=session_id, message_id=message_id, phase="chat")
    turn_t0 = time.perf_counter()
    reply_parts: list[str] = []
    turn_summary: dict = {}
    try:
        async for event in runtime.runner.run_async(
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
    runtime.mark_session_seen(session_id)
    try:
        _run_safety_preflight(req.message, session_id)
    except CostCircuitBreakerTripped:
        return _safety_error_stream(session_id, FRIENDLY_COST_ERROR)
    except UnsafePromptBlocked:
        return _safety_error_stream(session_id, FRIENDLY_PROMPT_ERROR)
    logger.debug(f"Stream chat request: session_id={session_id} user_id={req.user_id}")
    loop = asyncio.get_running_loop()

    session = await runtime.session_service.get_session(
        app_name=APP_NAME,
        user_id=req.user_id,
        session_id=session_id,
    )
    if session is None:
        session = await runtime.session_service.create_session(
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

    workflow_turn = await prepare_workflow_turn(
        session_id=session_id,
        message=req.message,
        incoming_deferred=req.deferred_fields,
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
        chat_stream_event_generator(
            session_id=session_id,
            user_id=req.user_id,
            message=req.message,
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

    runtime.record_session_outcome(req.session_id, "abandoned")
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
        session_service=runtime.session_service,
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
        session_service=runtime.session_service,
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
        session_service=runtime.session_service,
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
    session = await runtime.session_service.get_session(
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
    session = await runtime.session_service.get_session(
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


# Per-session dedup lock for /context/extract.
# Prevents multiple parallel Gemini extraction calls for the same session
# (common in voice mode where turn_complete events arrive faster than
# the ~40s extraction call can finish).
# WeakValueDictionary so entries are evicted automatically once no request
# holds a reference to the lock — no unbounded growth across sessions.
_extract_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()


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
        session = await runtime.session_service.get_session(
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
        session = await runtime.session_service.get_session(
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
            _sol_type = solution_type_value(_saved_state)
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
            session_service=runtime.session_service,
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
    runtime.mark_session_seen(session_id)
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
                session_service=runtime.session_service,
                session_bridge=runtime.session_bridge,
                audio_runner=runtime.audio_runner,
                run_turn_postprocessing=run_turn_postprocessing,
                load_voice_priming=load_voice_priming,
                logger=logger,
            ),
        )
    except Exception as exc:
        logger.error(f"[WS] Connection error: {exc}", exc_info=True)
    finally:
        logger.info(f"[WS] Connection closed: user={user_id} session={session_id}")
