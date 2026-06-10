from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from functools import partial

import runtime
from api import admin, diagrams, discovery, documents, feedback, sessions
from audio_websocket import AudioWebsocketDeps, run_audio_websocket
from chat_streaming import chat_stream_event_generator
from chat_turn import load_voice_priming, prepare_workflow_turn, run_turn_postprocessing
from config import (
    APP_NAME,
    FINALIZING_MARKER,
    MODEL_AUDIO,
    validate_config,
)
from direct_field_context import build_augmented_user_message, merge_direct_fields
from fastapi import (
    FastAPI,
    HTTPException,
    WebSocket,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from field_schema import FIELD_LABELS
from firestore import (
    append_conversation_turn,
    get_direct_fields,
    upsert_direct_fields,
)
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.genai import types
from google.genai.types import (
    AudioTranscriptionConfig,
    SpeechConfig,
    VoiceConfig,
)
from logger import get_logger, setup_logging
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


# --- Endpoints ---


@app.get("/health")
def health():
    return {"status": "ok"}


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


# --- Domain routers ---

app.include_router(admin.router)
app.include_router(diagrams.router)
app.include_router(discovery.router)
app.include_router(documents.router)
app.include_router(feedback.router)
app.include_router(sessions.router)
