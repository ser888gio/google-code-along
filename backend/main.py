from __future__ import annotations

import asyncio
import base64
import json
import os
import uuid
import weakref
from datetime import datetime, timezone

from agent import rs_agent, audio_agent
from agent.discovery_agent import (
    FIELD_LABELS,
    REQUIRED_FIELDS,
    FIELD_SCHEMA,
    extract_discovery_fields,
    initialize_workflow_state,
    is_not_applicable_allowed,
    pick_next_active_field,
    sync_workflow_with_discovery_state,
)
from agent.finalizer_agent import run_finalizer
from answer_classifier import (
    DIRECT_FIELD_KEYS,
    classify_user_turn,
    is_deferred_answer,
    normalize_for_match,
)
from answer_quality import rate_answer
from bpmn import check_completeness, generate_bpmn_diagram
from config import APP_NAME, FINALIZING_MARKER, GCS_PREFIX_SESSIONS, MODEL_AUDIO
from dataflow import check_dfd_completeness, generate_dataflow_diagram
from direct_field_context import build_augmented_user_message, merge_direct_fields
from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.requests import Request
from firestore import (
    append_conversation_turn,
    get_direct_fields,
    get_conversation_history,
    get_deferred_fields,
    get_discovery_state,
    get_final_analysis,
    get_srs_fields,
    get_workflow_state,
    list_sessions,
    remove_deferred_fields,
    set_finalization_pending,
    upsert_deferred_fields,
    upsert_direct_fields,
    upsert_discovery_state,
    upsert_workflow_state,
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
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from google.genai.errors import APIError as GenaiAPIError
from google.genai.types import (
    AudioTranscriptionConfig,
    Blob,
    Content,
    Part,
    SpeechConfig,
    VoiceConfig,
)
from logger import get_logger, setup_logging
from pydantic import BaseModel
from session_bridge import SessionBridge
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
logger.info(f"RS Generator API initializing (app_name={APP_NAME})")


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


def _build_conversation_tail(session, latest_user_message: str, limit: int = 12) -> str:
    """Build a compact transcript tail for classifiers/extractors."""
    tail_lines: list[str] = []
    if session and getattr(session, "events", None):
        for event in session.events[-limit:]:
            if not event.content or not event.content.parts:
                continue
            role = event.content.role or "unknown"
            text = "".join(p.text for p in event.content.parts if p.text).strip()
            if text:
                label = "User" if role == "user" else "Consultant"
                tail_lines.append(f"{label}: {text}")
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
        await loop.run_in_executor(
            None, upsert_deferred_fields, session_id, incoming_deferred
        )

    previous_active = workflow.get("active_field")
    classification = {
        "classification": "not_answered",
        "value": None,
        "confidence": 0.0,
        "proactive_fields": {},
    }

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
        classification = await classify_user_turn(
            previous_active, req.message, tail_text
        )
        await rate_answer(
            previous_active,
            str(
                (workflow.get("last_question_by_field") or {}).get(previous_active, "")
            ),
            req.message,
            classification["classification"],
        )

        statuses = workflow["field_status"]
        miss_counts = workflow.setdefault("miss_counts", {})
        clarification_counts = workflow.setdefault("clarification_counts", {})

        if classification["classification"] == "answered":
            value = classification.get("value")
            if value:
                statuses[previous_active] = "answered"
                miss_counts[previous_active] = 0
                if discovery_state is None:
                    discovery_state = {
                        "completeness": 0,
                        "fields": {},
                        "missing_priority": [],
                    }
                discovery_state.setdefault("fields", {})[previous_active] = (
                    _field_entry(value)
                )
                _recompute_discovery_completeness(discovery_state)
                await loop.run_in_executor(
                    None, upsert_discovery_state, session_id, discovery_state
                )
                if previous_active in DIRECT_FIELD_KEYS:
                    direct_fields[previous_active] = value
                    await loop.run_in_executor(
                        None, upsert_direct_fields, session_id, {previous_active: value}
                    )
                if previous_active in deferred_fields:
                    deferred_fields.pop(previous_active, None)
                    await loop.run_in_executor(
                        None, remove_deferred_fields, session_id, [previous_active]
                    )
            else:
                statuses[previous_active] = "missing"
        elif classification["classification"] == "deferred":
            statuses[previous_active] = "deferred"
            miss_counts[previous_active] = 0
            deferred_fields[previous_active] = {
                "deferred_at": datetime.now(timezone.utc).isoformat()
            }
            await loop.run_in_executor(
                None,
                upsert_deferred_fields,
                session_id,
                {previous_active: deferred_fields[previous_active]},
            )
        elif classification["classification"] == "clarification_requested":
            statuses[previous_active] = "clarification_requested"
            clarification_counts[previous_active] = (
                int(clarification_counts.get(previous_active) or 0) + 1
            )
        else:
            if is_deferred_answer(req.message):
                statuses[previous_active] = "deferred"
                deferred_fields[previous_active] = {
                    "deferred_at": datetime.now(timezone.utc).isoformat()
                }
                await loop.run_in_executor(
                    None,
                    upsert_deferred_fields,
                    session_id,
                    {previous_active: deferred_fields[previous_active]},
                )
            else:
                statuses[previous_active] = "missing"
                miss_counts[previous_active] = (
                    int(miss_counts.get(previous_active) or 0) + 1
                )

        proactive_updates: dict[str, str] = {}
        for key, entry in (classification.get("proactive_fields") or {}).items():
            if key not in FIELD_SCHEMA or key == previous_active:
                continue
            value = str(entry.get("value") or "").strip()
            if value:
                workflow["field_status"][key] = "answered"
                proactive_updates[key] = value
        if proactive_updates:
            if discovery_state is None:
                discovery_state = {
                    "completeness": 0,
                    "fields": {},
                    "missing_priority": [],
                }
            fields = discovery_state.setdefault("fields", {})
            for key, value in proactive_updates.items():
                fields[key] = _field_entry(value)
            _recompute_discovery_completeness(discovery_state)
            await loop.run_in_executor(
                None, upsert_discovery_state, session_id, discovery_state
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
    workflow_context = {
        "phase": workflow.get("phase"),
        "active_field": workflow.get("active_field"),
        "clarification_requested": classification["classification"]
        == "clarification_requested",
        "miss_count": int(
            (workflow.get("miss_counts") or {}).get(workflow.get("active_field")) or 0
        ),
        "answered_fields": answered_values,
        "deferred_fields": list(deferred_fields.keys()),
        "ready_to_finalize": workflow.get("phase") == "ready_to_finalize",
    }

    return {
        "workflow": workflow,
        "workflow_context": workflow_context,
        "direct_fields": direct_fields,
        "deferred_fields": list(deferred_fields.keys()),
        "classification": classification,
        "tail_text": tail_text,
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
            detail=f"File exceeds maximum allowed size of {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
        )
    logger.info(
        f"Upload received: file={safe_filename} size={len(contents)}B session_id={safe_session_id}"
    )
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

    stored_direct_fields = await loop.run_in_executor(
        None, get_direct_fields, session_id
    )
    direct_fields = merge_direct_fields(stored_direct_fields, req.direct_fields)
    if req.direct_fields:
        await loop.run_in_executor(
            None, upsert_direct_fields, session_id, req.direct_fields
        )

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
    reply_parts: list[str] = []
    async for event in runner.run_async(
        user_id=req.user_id,
        session_id=session_id,
        new_message=user_content,
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    reply_parts.append(part.text)

    reply = "".join(reply_parts)
    logger.info(f"Agent reply ready: session_id={session_id} reply_chars={len(reply)}")

    loop.run_in_executor(None, append_conversation_turn, session_id, req.message, reply)

    return ChatResponse(reply=reply, session_id=session_id)


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    """Stream the agent's response as Server-Sent Events."""

    session_id = req.session_id or str(uuid.uuid4())
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

    stored_direct_fields = await loop.run_in_executor(
        None, get_direct_fields, session_id
    )
    direct_fields = merge_direct_fields(stored_direct_fields, req.direct_fields)
    if req.direct_fields:
        await loop.run_in_executor(
            None, upsert_direct_fields, session_id, req.direct_fields
        )

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

    async def event_generator():
        # First, send the session_id so the client can track it
        yield f'data: {{"session_id": "{session_id}"}}\n\n'
        active_field = workflow_turn["workflow"].get("active_field")
        if active_field:
            yield f"data: {json.dumps({'active_field': active_field})}\n\n"

        # ── Pre-stream quick extract ──────────────────────────────────────
        # Before the agent starts responding, run a fast Gemini Flash extract
        # on the conversation-so-far + the new user message. Diff against the
        # previously persisted discovery state and emit a `field_update` SSE
        # event for each newly-filled (or changed) field. This lets the right
        # panel fill in progressively *before* the agent's reply starts
        # streaming — the user sees immediate feedback that their input was
        # heard. Hard-capped at 4s so the agent never stalls if Gemini is
        # slow or down.
        try:
            prev_state = await loop.run_in_executor(
                None, get_discovery_state, session_id
            )
            prev_fields = (prev_state or {}).get("fields") or {}

            tail_text = workflow_turn["tail_text"]

            new_state = await asyncio.wait_for(
                extract_discovery_fields(tail_text),
                timeout=4.0,
            )
            new_fields = new_state.get("fields") or {}

            emitted = 0
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
                    payload = json.dumps(
                        {"field_update": {"key": key, "value": new_value}}
                    )
                    yield f"data: {payload}\n\n"
                    emitted += 1
            logger.info(
                f"Pre-stream field_update: session={session_id} emitted={emitted}"
            )
        except asyncio.TimeoutError:
            logger.warning(
                f"Pre-stream extract timed out (>4s): session={session_id} — skipping field_update events"
            )
        except Exception as exc:
            logger.warning(f"Pre-stream extract failed: session={session_id} {exc}")

        reply_parts: list[str] = []
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
                            # Strip [FINALIZING] marker before sending to the client
                            # so the user never sees the raw signal token.
                            clean = part.text.replace(FINALIZING_MARKER, "").strip()
                            if clean:
                                yield f"data: {json.dumps({'text': clean})}\n\n"
        except Exception as exc:
            logger.error(
                f"Streaming error for session_id={session_id}: {exc}",
                exc_info=True,
            )
            yield f"data: {json.dumps({'error': 'An internal error occurred. Please try again.'})}\n\n"

        full_reply = "".join(reply_parts)
        logger.info(
            f"Stream complete: session_id={session_id} reply_chars={len(full_reply)}"
        )

        is_finalizing = FINALIZING_MARKER in full_reply

        # Signal frontend before [DONE] so it can show FinalizingOverlay
        if is_finalizing:
            logger.info(
                f"[FINALIZING] detected for session_id={session_id} — launching finalizer pipeline"
            )
            yield f"data: {json.dumps({'event': 'finalizing'})}\n\n"

        # Shared pipeline: Firestore persist, discovery extraction, SRS,
        # finalization — runs as a background task so [DONE] is sent promptly.
        asyncio.create_task(
            _run_turn_postprocessing(
                session_id=session_id,
                user_id=req.user_id,
                user_text=req.message,
                assistant_text=full_reply,
                is_finalizing=is_finalizing,
                fallback_transcript=full_reply,
            )
        )

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )


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
    markdown = await compile_rs_from_session(
        session_service=session_service,
        app_name=APP_NAME,
        user_id=req.user_id,
        session_id=req.session_id,
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

    markdown = await compile_rs_from_session(
        session_service=session_service,
        app_name=APP_NAME,
        user_id=req.user_id,
        session_id=req.session_id,
    )
    if markdown is None:
        logger.warning(
            f"PDF export requested but no RS document found: session_id={req.session_id}"
        )
        raise HTTPException(
            status_code=404,
            detail="No RS document found. Complete the conversation first.",
        )

    logger.info(f"Generating PDF export: session_id={req.session_id}")
    pdf_bytes = markdown_to_pdf(markdown)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": "attachment; filename=requirement_specification.pdf"
        },
    )


@app.post("/document/docx")
async def download_docx(req: SessionRef):
    """Generate and download the SRS as a populated Word (.docx) document.

    Uses Gemini to compile the full SRS structure from the conversation,
    then writes it into a Word document using the SRS template structure.
    Returns 404 if the session is not found, 422 if compilation fails.
    """

    srs_json = await compile_srs_json_from_session(
        session_service=session_service,
        app_name=APP_NAME,
        user_id=req.user_id,
        session_id=req.session_id,
    )
    if srs_json is None:
        logger.warning(
            f"DOCX export failed — SRS could not be compiled: session_id={req.session_id}"
        )
        raise HTTPException(
            status_code=422,
            detail="Could not compile SRS from the conversation. Keep chatting to provide more details.",
        )

    logger.info(f"Generating DOCX export: session_id={req.session_id}")
    docx_bytes = srs_json_to_docx(srs_json)

    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": "attachment; filename=requirement_specification.docx"
        },
    )


@app.post("/document/rs-template/docx")
async def download_rs_template_docx(req: SessionRef):
    """Generate a Word doc from the 22 RSLiveTemplate fields, save to GCS, and return for download."""
    loop = asyncio.get_running_loop()
    state = await loop.run_in_executor(None, get_discovery_state, req.session_id)

    fields: dict = {}
    if state:
        fields = state.get("fields", {})

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
        return BpmnResponse(ready=False, score=score, missing=missing)

    logger.info(f"Generating BPMN diagram: session_id={req.session_id}")
    mermaid = await generate_bpmn_diagram(conversation_text)
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
    logger.info(
        f"Dataflow completeness check: session_id={req.session_id} score={score}%"
    )

    if score < 70:
        logger.debug(f"Dataflow not ready (score < 70): missing={missing}")
        return DataflowResponse(ready=False, score=score, missing=missing)

    logger.info(f"Generating Dataflow diagram: session_id={req.session_id}")
    mermaid = await generate_dataflow_diagram(conversation_text)
    return DataflowResponse(ready=True, mermaid=mermaid, score=score)


# --- Live RS context extraction ---


class ContextRequest(BaseModel):
    session_id: str
    user_id: str = "default_user"


class FieldData(BaseModel):
    filled: bool
    value: str | None


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
        raise HTTPException(
            status_code=500, detail=f"Session lookup failed: {type(exc).__name__}"
        )

    if session is None:
        # ADK session gone — return last persisted discovery state if available
        try:
            loop = asyncio.get_running_loop()
            saved = await loop.run_in_executor(None, get_discovery_state, sid)
        except Exception as exc:
            logger.error(
                f"Firestore fallback failed for session_id={sid}: {exc}", exc_info=True
            )
            raise HTTPException(
                status_code=502, detail=f"Firestore unavailable: {type(exc).__name__}"
            )
        if saved:
            logger.info(
                f"ADK session missing, returning saved discovery state: session_id={sid} completeness={saved.get('completeness')}%"
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
                logger.warning(
                    f"Firestore get_discovery_state (coalesced) failed: session_id={sid} {exc}"
                )
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
        result = await extract_discovery_fields(conversation_text)
        logger.info(
            f"Discovery fields extracted: session_id={sid} completeness={result.get('completeness')}%"
        )

        # Fire-and-forget: persist discovery state + full SRS to Firestore
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, upsert_discovery_state, sid, result)
        except Exception as exc:
            logger.warning(
                f"Firestore upsert_discovery_state failed: session_id={sid} {exc}"
            )

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
            logger.warning(
                f"Firestore get_discovery_state failed: session_id={sid} {exc}"
            )
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
        logger.debug(
            f"Discovery state retrieved: session_id={session_id} completeness={saved.get('completeness')}%"
        )
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
    logger.info(
        f"Direct fields patched: session_id={session_id} keys={list(body.fields.keys())}"
    )
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
        logger.warning(
            f"Firestore SRS upsert failed: session_id={session_id} error={exc}"
        )


# --- Firestore data retrieval ---


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

    The frontend polls this endpoint every 5 s after receiving the "finalizing" SSE event.

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
            f"Firestore read failed for session_id={session_id}: {exc}", exc_info=True
        )
        raise HTTPException(
            status_code=502, detail=f"Firestore unavailable: {type(exc).__name__}"
        )
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
        loop.run_in_executor(
            None,
            append_conversation_turn,
            session_id,
            user_text or "(voice input)",
            assistant_text,
        )

    # 2. If [FINALIZING] detected, launch the finalizer pipeline
    #    The finalizer needs discovery fields + conversation transcript,
    #    so we extract them here (only on finalization, not every turn).
    if is_finalizing:
        logger.info(
            f"[FINALIZING] detected: session={session_id} — launching finalizer"
        )
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
            else (
                fallback_transcript
                or f"User: {user_text}\nConsultant: {assistant_text}"
            )
        )

        # Extract discovery fields for the finalizer
        try:
            discovery_fields = await extract_discovery_fields(conversation_text)
            logger.debug(
                f"Discovery fields for finalizer: session={session_id} "
                f"completeness={discovery_fields.get('completeness')}%"
            )
            loop.run_in_executor(
                None, upsert_discovery_state, session_id, discovery_fields
            )
        except Exception as exc:
            logger.warning(
                f"extract_discovery_fields failed: session={session_id} {exc}"
            )
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
      - Text frames   = JSON messages:
          {"type": "text",  "text": "..."}           — text input
          {"type": "audio", "data": "<base64 PCM>"}  — audio as base64 (fallback)
      - Server sends back:
          Binary frames = PCM audio (24kHz, 16-bit, mono) for playback
          Text frames   = JSON: {"type":"text", "text":"..."} for transcriptions / text
    """
    await websocket.accept()
    logger.info(f"[WS] Connected: user={user_id} session={session_id}")

    # Ensure session exists (share session store with REST endpoints)
    session = await session_service.get_session(
        app_name=APP_NAME,
        user_id=user_id,
        session_id=session_id,
    )
    if session is None:
        session = await session_service.create_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=session_id,
        )

    live_request_queue = LiveRequestQueue()
    run_config = _build_run_config()

    async def upstream_task():
        """Read from WebSocket and push into the LiveRequestQueue."""
        try:
            while True:
                try:
                    # Try binary first (raw PCM audio)
                    data = await websocket.receive()

                    if data.get("type") == "websocket.disconnect":
                        break

                    if "bytes" in data and data["bytes"]:
                        # Raw PCM audio bytes from the mic
                        audio_bytes = data["bytes"]
                        audio_blob = Blob(
                            mime_type="audio/pcm;rate=16000",
                            data=audio_bytes,
                        )
                        live_request_queue.send_realtime(audio_blob)

                    elif "text" in data and data["text"]:
                        msg = json.loads(data["text"])
                        msg_type = msg.get("type", "text")

                        if msg_type == "audio":
                            # Base64-encoded PCM audio (fallback path)
                            audio_bytes = base64.b64decode(msg["data"])
                            audio_blob = Blob(
                                mime_type="audio/pcm;rate=16000",
                                data=audio_bytes,
                            )
                            live_request_queue.send_realtime(audio_blob)

                        elif msg_type == "text":
                            # Text message
                            text = msg.get("text", "")
                            if text.strip():
                                content = Content(
                                    role="user",
                                    parts=[Part.from_text(text=text)],
                                )
                                live_request_queue.send_content(content)

                        elif msg_type == "end_of_turn":
                            # Client signals end of voice turn
                            live_request_queue.send_realtime(
                                Blob(
                                    mime_type="audio/pcm;rate=16000",
                                    data=b"",
                                )
                            )

                except WebSocketDisconnect:
                    break
                except json.JSONDecodeError as e:
                    logger.warning(f"[WS] Invalid JSON from client: {e}")
                    continue

        except Exception as e:
            logger.error(f"[WS] Upstream error: {e}", exc_info=True)
        finally:
            live_request_queue.close()
            logger.debug(f"[WS] Upstream closed: user={user_id} session={session_id}")

    async def downstream_task():
        """Read events from runner.run_live() and send to WebSocket.

        Accumulates user and assistant transcription text across a turn,
        then runs the same post-processing pipeline as text chat:
        Firestore persistence, discovery-field extraction, SRS compilation,
        and [FINALIZING] detection.

        Transcription events from the ADK arrive on dedicated fields:
          - event.input_transcription.text  → user speech-to-text
          - event.output_transcription.text → assistant speech-to-text
        These are separate from audio blob events (event.content.parts[].inline_data).
        Partial events (event.partial=True) carry incremental chunks;
        final events (event.partial=False) carry the full accumulated text.

        Only final (complete) transcriptions are sent to the frontend so each
        role gets exactly one large chat bubble rather than many tiny fragments.
        """
        # Accumulate final transcription text per turn for Firestore persistence
        user_transcript_final: str = ""
        assistant_transcript_final: str = ""

        try:
            async for event in audio_runner.run_live(
                session=session,
                live_request_queue=live_request_queue,
                run_config=run_config,
            ):
                # ── 1. Audio blob — send as binary frame ──────────────────
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if (
                            part.inline_data
                            and part.inline_data.mime_type
                            and "audio" in part.inline_data.mime_type
                            and part.inline_data.data
                        ):
                            await websocket.send_bytes(part.inline_data.data)

                        # Rare: text content in audio mode (non-transcription)
                        elif part.text:
                            logger.debug(
                                f"[WS] Text content event (role={getattr(event.content, 'role', '?')}): "
                                f"{part.text[:80]}"
                            )

                # ── 2. User input transcription ───────────────────────────
                if event.input_transcription and event.input_transcription.text:
                    if not event.partial:
                        # Final accumulated user transcription — send as one complete bubble
                        user_transcript_final = event.input_transcription.text
                        clean = user_transcript_final.strip()
                        if clean:
                            await websocket.send_text(
                                json.dumps(
                                    {
                                        "type": "user_transcript",
                                        "text": clean,
                                    }
                                )
                            )
                        logger.debug(
                            f"[WS] User transcription final ({len(clean)} chars): "
                            f"{clean[:100]}"
                        )

                # ── 3. Assistant output transcription ─────────────────────
                if event.output_transcription and event.output_transcription.text:
                    if not event.partial:
                        # Final accumulated assistant transcription — send as one complete bubble
                        assistant_transcript_final = event.output_transcription.text
                        clean = assistant_transcript_final.replace(
                            FINALIZING_MARKER, ""
                        ).strip()
                        if clean:
                            await websocket.send_text(
                                json.dumps(
                                    {
                                        "type": "text",
                                        "text": clean,
                                    }
                                )
                            )
                        logger.debug(
                            f"[WS] Assistant transcription final ({len(assistant_transcript_final)} chars): "
                            f"{assistant_transcript_final[:100]}"
                        )

                # ── 4. Turn complete: inject into orchestrator session, THEN notify frontend ──
                if event.is_final_response():
                    user_text = user_transcript_final.strip()
                    assistant_text = assistant_transcript_final.strip()

                    logger.info(
                        f"[WS] Turn complete: session={session_id} "
                        f"user_chars={len(user_text)} assistant_chars={len(assistant_text)}"
                    )

                    # Check for [FINALIZING] marker (needed for turn_complete msg)
                    is_finalizing = FINALIZING_MARKER in assistant_text

                    # CRITICAL: Inject voice transcript into orchestrator's ADK
                    # session BEFORE sending turn_complete to the frontend.
                    # The frontend fires POST /context/extract on turn_complete,
                    # which reads extract_conversation_text() from the session.
                    # If we defer injection to a background task, the extraction
                    # runs on a stale session snapshot that lacks the voice data.
                    try:
                        await session_bridge.inject_voice_turn(
                            user_id=user_id,
                            session_id=session_id,
                            user_text=user_text,
                            assistant_text=assistant_text,
                        )
                        # Verify injection: fetch session from storage and check events
                        _verify = await session_service.get_session(
                            app_name=APP_NAME,
                            user_id=user_id,
                            session_id=session_id,
                        )
                        if _verify:
                            _content_evts = [
                                e
                                for e in (_verify.events or [])
                                if e.content
                                and e.content.parts
                                and any(p.text for p in e.content.parts if p.text)
                            ]
                            logger.info(
                                f"[WS] Post-injection verify: session={session_id} "
                                f"total_events={len(_verify.events or [])} "
                                f"content_text_events={len(_content_evts)}"
                            )
                        else:
                            logger.warning(
                                f"[WS] Post-injection: session NOT FOUND in storage! "
                                f"session={session_id}"
                            )
                    except Exception as exc:
                        logger.error(
                            f"[WS] SessionBridge injection failed: session={session_id} {exc}"
                        )

                    # Now send turn_complete — the session has the voice data
                    await websocket.send_text(
                        json.dumps(
                            {
                                "type": "turn_complete",
                                "finalizing": is_finalizing,
                            }
                        )
                    )

                    # Remaining post-processing (Firestore persist, finalization)
                    # runs as a background task so the event loop stays free for
                    # the next audio turn. SessionBridge is already done above.
                    asyncio.create_task(
                        _run_turn_postprocessing(
                            session_id=session_id,
                            user_id=user_id,
                            user_text=user_text,
                            assistant_text=assistant_text,
                            is_finalizing=is_finalizing,
                        )
                    )

                    # Reset accumulators for next turn
                    user_transcript_final = ""
                    assistant_transcript_final = ""

        except WebSocketDisconnect:
            logger.debug("[WS] Client disconnected during downstream")
        except GenaiAPIError as e:
            # Code 1000 = normal WebSocket close (user toggled voice off or navigated away)
            if "1000" in str(e):
                logger.info(
                    f"[WS] Gemini Live session closed normally: session={session_id}"
                )
            else:
                logger.error(f"[WS] Gemini Live API error: {e}", exc_info=True)
                try:
                    await websocket.send_text(
                        json.dumps(
                            {
                                "type": "error",
                                "message": "A voice API error occurred. Please try again.",
                            }
                        )
                    )
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"[WS] Downstream error: {e}", exc_info=True)
            try:
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "error",
                            "message": "An internal error occurred. Please reconnect.",
                        }
                    )
                )
            except Exception:
                pass
        finally:
            logger.debug(f"[WS] Downstream closed: user={user_id} session={session_id}")

    try:
        # Run upstream (WS → queue) and downstream (live → WS) concurrently
        await asyncio.gather(
            upstream_task(),
            downstream_task(),
        )
    except Exception as e:
        logger.error(f"[WS] Connection error: {e}", exc_info=True)
    finally:
        logger.info(f"[WS] Connection closed: user={user_id} session={session_id}")
