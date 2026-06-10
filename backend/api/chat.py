"""Chat endpoints — POST /chat, POST /chat/stream, WS /ws/{user_id}/{session_id}."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from functools import partial

import runtime
from audio_websocket import AudioWebsocketDeps, run_audio_websocket
from chat_streaming import chat_stream_event_generator
from chat_turn import load_voice_priming, prepare_workflow_turn, run_turn_postprocessing
from config import (
    APP_NAME,
    FINALIZING_MARKER,
    MODEL_AUDIO,
)
from direct_field_context import build_augmented_user_message, merge_direct_fields
from fastapi import APIRouter, HTTPException, Query, WebSocket
from fastapi.responses import StreamingResponse
from field_schema import FIELD_LABELS
from firestore import (
    accept_rs_fields,
    append_conversation_turn,
    get_accepted_rs_fields,
)
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.genai import types
from google.genai.types import (
    AudioTranscriptionConfig,
    SpeechConfig,
    VoiceConfig,
)
from logger import get_logger
from observability.safety import (
    FRIENDLY_COST_ERROR,
    FRIENDLY_PROMPT_ERROR,
    CostCircuitBreakerTripped,
    UnsafePromptBlocked,
    assert_session_within_budget,
    check_user_prompt_or_raise,
)
from observability.tracing import current_trace_ids
from observability.turns import (
    current_turn,
    reset_turn,
    set_stream_timings,
    start_turn,
    summarize_turn,
)
from pydantic import BaseModel

logger = get_logger(__name__)

router = APIRouter(tags=["chat"])


# --- Models ---


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


# --- Safety helpers ---


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


async def _resolve_session(user_id: str, session_id: str):
    """Return existing session or create a new one."""
    session = await runtime.session_service.get_session(
        app_name=APP_NAME,
        user_id=user_id,
        session_id=session_id,
    )
    if session is None:
        session = await runtime.session_service.create_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=session_id,
        )
        logger.info(f"New session created: {session_id}")
    else:
        logger.debug(f"Resumed existing session: {session_id}")
    return session


async def _prepare_turn(req: ChatRequest, session_id: str):
    """Load direct fields, merge, persist, and build the workflow turn."""
    loop = asyncio.get_running_loop()
    session = await _resolve_session(req.user_id, session_id)
    stored_direct_fields = await loop.run_in_executor(None, get_accepted_rs_fields, session_id)
    direct_fields = merge_direct_fields(stored_direct_fields, req.direct_fields)
    if req.direct_fields:
        await loop.run_in_executor(None, accept_rs_fields, session_id, req.direct_fields, "user_manual")
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
    return workflow_turn, user_content


# --- Endpoints ---


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Send a message to the RS consultant agent and get a response."""
    session_id = req.session_id or str(uuid.uuid4())
    runtime.mark_session_seen(session_id)
    try:
        _run_safety_preflight(req.message, session_id)
    except (CostCircuitBreakerTripped, UnsafePromptBlocked) as exc:
        raise _safety_http_error(exc) from exc
    logger.debug(f"Chat request: session_id={session_id} user_id={req.user_id}")

    workflow_turn, user_content = await _prepare_turn(req, session_id)

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

    loop = asyncio.get_running_loop()
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


@router.post("/chat/stream")
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

    workflow_turn, user_content = await _prepare_turn(req, session_id)

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


# --- WebSocket audio ---


def _is_native_audio_model(model_name: str) -> bool:
    return "native-audio" in model_name


# Maps the frontend UI locale to a BCP-47 speech language code. Czech-first
# product: unknown or missing locales fall back to Czech.
_VOICE_LANGUAGE_CODES = {"cs": "cs-CZ", "en": "en-US"}
_DEFAULT_VOICE_LANG = "cs"

_VOICE_LANGUAGE_HINTS = {
    "cs": "The user's interface language is Czech; expect the user to speak Czech and respond in Czech.",
    "en": "The user's interface language is English; expect the user to speak English and respond in English.",
}


def _resolve_voice_lang(lang: str | None) -> str:
    return lang if lang in _VOICE_LANGUAGE_CODES else _DEFAULT_VOICE_LANG


def _voice_priming_with_language(session_id: str, lang: str) -> str | None:
    """Append the locale hint to the workflow priming block.

    The hint is the only language steer that works on native-audio Live models
    (they ignore SpeechConfig.language_code), so it is sent even for brand-new
    sessions where the workflow priming itself is empty.
    """
    priming = load_voice_priming(session_id)
    hint = _VOICE_LANGUAGE_HINTS[lang]
    if priming:
        return f"{priming}\n\n{hint}"
    return hint


def _build_run_config(lang: str) -> RunConfig:
    """Build a RunConfig for bidi audio streaming.

    Adapts response modalities and speech config depending on whether the
    audio model is a native-audio model or a half-cascade model. The language
    code is pinned on both branches; native-audio models ignore it and rely on
    the priming hint instead.
    """
    speech_config = SpeechConfig(
        voice_config=VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Aoede")),
        language_code=_VOICE_LANGUAGE_CODES[lang],
    )
    if _is_native_audio_model(MODEL_AUDIO):
        return RunConfig(
            streaming_mode=StreamingMode.BIDI,
            response_modalities=["AUDIO"],
            speech_config=speech_config,
            output_audio_transcription=AudioTranscriptionConfig(),
            input_audio_transcription=AudioTranscriptionConfig(),
        )
    return RunConfig(
        streaming_mode=StreamingMode.BIDI,
        response_modalities=["AUDIO"],
        speech_config=speech_config,
    )


@router.websocket("/ws/{user_id}/{session_id}")
async def websocket_audio(
    websocket: WebSocket,
    user_id: str,
    session_id: str,
    lang: str | None = Query(default=None),
):
    """Bidirectional audio streaming over WebSocket.

    Protocol:
      - Binary frames = raw PCM audio (16kHz, 16-bit, mono) from the client
      - Text frames   = JSON messages for text/audio/end-of-turn fallbacks
      - Server sends binary PCM audio and JSON text/transcription events back

    ``lang`` is the frontend UI locale (``cs``/``en``); it pins the speech
    recognition/synthesis language. Missing or unknown values fall back to Czech.
    """
    await websocket.accept()
    runtime.mark_session_seen(session_id)
    voice_lang = _resolve_voice_lang(lang)
    logger.info(f"[WS] Connected: user={user_id} session={session_id} lang={voice_lang}")

    try:
        await run_audio_websocket(
            websocket,
            user_id=user_id,
            session_id=session_id,
            run_config=_build_run_config(voice_lang),
            deps=AudioWebsocketDeps(
                app_name=APP_NAME,
                finalizing_marker=FINALIZING_MARKER,
                session_service=runtime.session_service,
                session_bridge=runtime.session_bridge,
                audio_runner=runtime.audio_runner,
                run_turn_postprocessing=run_turn_postprocessing,
                load_voice_priming=partial(_voice_priming_with_language, lang=voice_lang),
                logger=logger,
            ),
        )
    except Exception as exc:
        logger.error(f"[WS] Connection error: {exc}", exc_info=True)
    finally:
        logger.info(f"[WS] Connection closed: user={user_id} session={session_id}")
