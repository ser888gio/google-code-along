import asyncio
import base64
import json
import traceback
import uuid

from agent import rs_agent, audio_agent
from agent.discovery_agent import extract_discovery_fields
from agent.finalizer_agent import run_finalizer
from bpmn import check_completeness, generate_bpmn_diagram
from config import APP_NAME, FINALIZING_MARKER, MODEL_AUDIO
from dataflow import check_dfd_completeness, generate_dataflow_diagram
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
from fastapi.responses import Response, StreamingResponse
from firestore import (
    append_conversation_turn,
    get_conversation_history,
    get_discovery_state,
    get_final_analysis,
    get_srs_fields,
    list_sessions,
    set_finalization_pending,
    upsert_discovery_state,
    upsert_srs_fields,
)
from gcs import write_file
from generation import (
    compile_rs_from_session,
    compile_srs_json_from_session,
    markdown_to_pdf,
    srs_json_to_docx,
)
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from google.genai.errors import APIError as GenaiAPIError
from google.genai.types import (
    ActivityEnd,
    ActivityStart,
    AudioTranscriptionConfig,
    AutomaticActivityDetection,
    Blob,
    Content,
    LiveConnectConfig,
    Modality,
    Part,
    RealtimeInputConfig,
    SpeechConfig,
    VoiceConfig,
)
from logger import get_logger, setup_logging
from pydantic import BaseModel

setup_logging()
logger = get_logger(__name__)

app = FastAPI(title="RS Generator API")
logger.info(f"RS Generator API initializing (app_name={APP_NAME})")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- ADK runner setup ---

session_service = InMemorySessionService()

runner = Runner(
    app_name=APP_NAME,
    agent=rs_agent,
    session_service=session_service,
)

# Audio runner for bidi voice streaming (uses native-audio model)
audio_runner = Runner(
    app_name=APP_NAME,
    agent=audio_agent,
    session_service=session_service,
)


# --- Request / response models ---


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    user_id: str = "default_user"


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


@app.post("/upload", response_model=UploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    session_id: str = Form(...),
):
    """Upload a file to GCS under sessions/{session_id}/{filename}."""
    destination = f"sessions/{session_id}/{file.filename}"
    contents = await file.read()
    logger.info(
        f"Upload received: file={file.filename} size={len(contents)}B session_id={session_id}"
    )
    gcs_path = write_file(
        path=destination,
        data=contents,
        content_type=file.content_type or "application/octet-stream",
    )
    logger.debug(f"File uploaded to GCS: {gcs_path}")
    return UploadResponse(gcs_path=gcs_path, filename=file.filename)


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Send a message to the RS consultant agent and get a response."""

    session_id = req.session_id or str(uuid.uuid4())
    logger.debug(f"Chat request: session_id={session_id} user_id={req.user_id}")

    # Ensure session exists
    session = await session_service.get_session(
        app_name="rs_generator",
        user_id=req.user_id,
        session_id=session_id,
    )
    if session is None:
        session = await session_service.create_session(
            app_name="rs_generator",
            user_id=req.user_id,
            session_id=session_id,
        )
        logger.info(f"New session created: {session_id}")
    else:
        logger.debug(f"Resumed existing session: {session_id}")

    user_content = types.Content(
        role="user",
        parts=[types.Part.from_text(text=req.message)],
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

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, append_conversation_turn, session_id, req.message, reply)

    return ChatResponse(reply=reply, session_id=session_id)


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    """Stream the agent's response as Server-Sent Events."""

    session_id = req.session_id or str(uuid.uuid4())
    logger.debug(f"Stream chat request: session_id={session_id} user_id={req.user_id}")

    session = await session_service.get_session(
        app_name="rs_generator",
        user_id=req.user_id,
        session_id=session_id,
    )
    if session is None:
        session = await session_service.create_session(
            app_name="rs_generator",
            user_id=req.user_id,
            session_id=session_id,
        )
        logger.info(f"New session created: {session_id}")
    else:
        logger.debug(f"Resumed existing session: {session_id}")

    user_content = types.Content(
        role="user",
        parts=[types.Part.from_text(text=req.message)],
    )

    async def event_generator():
        # First, send the session_id so the client can track it
        yield f'data: {{"session_id": "{session_id}"}}\n\n'

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
                        # Strip [FINALIZING] marker before sending to the client
                        # so the user never sees the raw signal token.
                        clean = part.text.replace(FINALIZING_MARKER, "").strip()
                        if clean:
                            yield f"data: {json.dumps({'text': clean})}\n\n"

        full_reply = "".join(reply_parts)
        logger.info(
            f"Stream complete: session_id={session_id} reply_chars={len(full_reply)}"
        )

        # Persist conversation turn to Firestore (fire-and-forget)
        loop = asyncio.get_event_loop()
        loop.run_in_executor(
            None, append_conversation_turn, session_id, req.message, full_reply
        )

        # --- Finalization trigger ---
        if FINALIZING_MARKER in full_reply:
            logger.info(
                f"[FINALIZING] detected for session_id={session_id} — launching finalizer pipeline"
            )
            # 1. Signal frontend immediately — it shows FinalizingOverlay + switches to Analysis tab
            yield f"data: {json.dumps({'event': 'finalizing'})}\n\n"

            # 2. Mark Firestore as pending so frontend polls know state
            loop.run_in_executor(None, set_finalization_pending, session_id)

            # 3. Build full conversation transcript from the ADK session events
            session_snap = await session_service.get_session(
                app_name=APP_NAME,
                user_id=req.user_id,
                session_id=session_id,
            )
            conversation_text = (
                _extract_conversation_text(session_snap) if session_snap else full_reply
            )

            # 4. Extract current 22-field state for the finalizer (async, may take a few seconds)
            try:
                discovery_fields = await extract_discovery_fields(conversation_text)
                logger.debug(
                    f"Discovery fields extracted: session_id={session_id} completeness={discovery_fields.get('completeness')}%"
                )
                # Persist the latest discovery state so history restore reflects it
                loop.run_in_executor(
                    None, upsert_discovery_state, session_id, discovery_fields
                )
            except Exception as exc:
                logger.warning(
                    f"extract_discovery_fields failed for session_id={session_id}: {exc}"
                )
                discovery_fields = {
                    "completeness": 0,
                    "fields": {},
                    "missing_priority": [],
                }

            # 5. Launch finalizer in background — does NOT block the SSE stream
            #    run_finalizer() writes to GCS + Firestore when done.
            #    Frontend polls GET /analyses/{session_id} to detect completion.
            asyncio.create_task(
                run_finalizer(
                    session_id=session_id,
                    user_id=req.user_id,
                    conversation_text=conversation_text,
                    discovery_fields=discovery_fields,
                )
            )
            logger.debug(f"Finalizer background task created: session_id={session_id}")

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


# --- BPMN diagram generation ---


def _extract_conversation_text(session) -> str:
    """Flatten a session's events into a plain text transcript."""
    lines: list[str] = []
    for event in session.events or []:
        if not event.content or not event.content.parts:
            continue
        role = event.content.role or "unknown"
        text = "".join(p.text for p in event.content.parts if p.text).strip()
        if text:
            label = "User" if role == "user" else "Consultant"
            lines.append(f"{label}: {text}")
    return "\n".join(lines)


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
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Session not found.")

    conversation_text = _extract_conversation_text(session)

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
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Session not found.")

    conversation_text = _extract_conversation_text(session)

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

    Fallback order when the ADK session is missing (e.g. after a backend restart
    or when loading a historical session that was never replayed in ADK):
      1. Try the ADK InMemorySessionService — extract fresh from live events.
      2. If not found, return the last saved discovery state from Firestore.
      3. If nothing saved yet, return empty state (completeness=0).
    """
    session = await session_service.get_session(
        app_name=APP_NAME,
        user_id=req.user_id,
        session_id=req.session_id,
    )

    if session is None:
        # ADK session gone — return last persisted discovery state if available
        loop = asyncio.get_event_loop()
        saved = await loop.run_in_executor(None, get_discovery_state, req.session_id)
        if saved:
            logger.info(
                f"ADK session missing, returning saved discovery state: session_id={req.session_id} completeness={saved.get('completeness')}%"
            )
            return {"completeness": saved["completeness"], "fields": saved["fields"]}
        logger.info(
            f"No ADK session and no saved state for session_id={req.session_id}"
        )
        return {"completeness": 0, "fields": {}}

    conversation_text = _extract_conversation_text(session)
    logger.debug(f"Extracting discovery fields: session_id={req.session_id}")
    result = await extract_discovery_fields(conversation_text)
    logger.info(
        f"Discovery fields extracted: session_id={req.session_id} completeness={result.get('completeness')}%"
    )

    # Fire-and-forget: persist discovery state + full SRS to Firestore
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, upsert_discovery_state, req.session_id, result)
    asyncio.create_task(
        _persist_srs_to_firestore(
            session_id=req.session_id,
            user_id=req.user_id,
        )
    )

    return {"completeness": result["completeness"], "fields": result["fields"]}


@app.get("/discovery/{session_id}", response_model=ContextResponse)
async def discovery_state(session_id: str):
    """Return the last saved 22-field discovery state for *session_id*.

    Used by the frontend when loading a historical session to restore the
    Preview panel without re-running Gemini extraction.
    Returns completeness=0 with empty fields if nothing has been saved yet.
    """
    loop = asyncio.get_event_loop()
    saved = await loop.run_in_executor(None, get_discovery_state, session_id)
    if saved:
        logger.debug(
            f"Discovery state retrieved: session_id={session_id} completeness={saved.get('completeness')}%"
        )
        return {"completeness": saved["completeness"], "fields": saved["fields"]}
    logger.debug(f"No saved discovery state for session_id={session_id}")
    return {"completeness": 0, "fields": {}}


async def _persist_srs_to_firestore(
    session_id: str,
    user_id: str,
    conversation_text: str | None = None,
) -> None:
    """Compile the full SRS JSON and upsert it into Firestore.

    Pass conversation_text for voice sessions where ADK session events contain
    audio blobs rather than text (compile_srs_json_from_session would otherwise
    return None).  For text sessions leave it None to use the ADK session events.

    Runs in the background — failures are logged and never surface to the user.
    """
    try:
        srs_json = await compile_srs_json_from_session(
            session_service=session_service,
            app_name=APP_NAME,
            user_id=user_id,
            session_id=session_id,
            conversation_text=conversation_text,
        )
        if srs_json:
            loop = asyncio.get_event_loop()
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
    loop = asyncio.get_event_loop()
    items = await loop.run_in_executor(None, list_sessions)
    return items


class HistoryResponse(BaseModel):
    session_id: str
    messages: list[dict]


@app.get("/history/{session_id}", response_model=HistoryResponse)
async def get_history(session_id: str):
    """Return the full conversation history for *session_id*."""
    loop = asyncio.get_event_loop()
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
    loop = asyncio.get_event_loop()
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
    loop = asyncio.get_event_loop()
    doc = await loop.run_in_executor(None, get_srs_fields, session_id)
    return FirestoreDataResponse(session_id=session_id, data=doc)


# --- Bidirectional audio WebSocket endpoint ---


def _is_native_audio_model(model_name: str) -> bool:
    """Check if the model supports native audio input/output."""
    return "native-audio" in model_name


def _build_run_config() -> RunConfig:
    """Build a RunConfig for bidi audio streaming in push-to-talk mode.

    VAD (automatic activity detection) is disabled so the model waits for
    explicit ActivityStart / ActivityEnd signals rather than auto-detecting
    end-of-speech mid-sentence.

    Adapts response modalities and speech config depending on whether the
    audio model is a native-audio model or a half-cascade model.
    """
    is_native = _is_native_audio_model(MODEL_AUDIO)

    # Disable VAD for push-to-talk — model responds only when ActivityEnd is sent
    realtime_input_cfg = RealtimeInputConfig(
        automatic_activity_detection=AutomaticActivityDetection(disabled=True),
    )

    if is_native:
        # Native audio: model speaks audio directly
        run_config = RunConfig(
            streaming_mode=StreamingMode.BIDI,
            response_modalities=[Modality.AUDIO],
            speech_config=SpeechConfig(
                voice_config=VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Aoede",
                    )
                )
            ),
            output_audio_transcription=AudioTranscriptionConfig(),
            input_audio_transcription=AudioTranscriptionConfig(),
            realtime_input_config=realtime_input_cfg,
        )
    else:
        # Half-cascade: model outputs text, TTS converts to audio
        run_config = RunConfig(
            streaming_mode=StreamingMode.BIDI,
            response_modalities=[Modality.AUDIO],
            speech_config=SpeechConfig(
                voice_config=VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Aoede",
                    )
                )
            ),
            realtime_input_config=realtime_input_cfg,
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

    # Build a running plain-text transcript for this voice session.
    # Seed it with any prior turns persisted to Firestore (covers text turns from
    # the same session_id so the voice agent has full context).
    loop = asyncio.get_event_loop()
    prior_history = await loop.run_in_executor(None, get_conversation_history, session_id)
    transcript_lines: list[str] = []
    for m in prior_history:
        if m.get("text"):
            label = "User" if m.get("role") == "user" else "Consultant"
            transcript_lines.append(f"{label}: {m['text']}")

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

                        elif msg_type == "activity_start":
                            # Push-to-talk: user pressed the mic button
                            live_request_queue.send_realtime(ActivityStart())

                        elif msg_type == "end_of_turn":
                            # Push-to-talk: user released the mic button
                            live_request_queue.send_realtime(ActivityEnd())

                except WebSocketDisconnect:
                    break
                except json.JSONDecodeError as e:
                    logger.warning(f"[WS] Invalid JSON from client: {e}")
                    continue

        except Exception as e:
            logger.error(f"[WS] Upstream error: {e}")
            traceback.print_exc()
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

                # ── 4. Turn complete: run the full post-processing pipeline ──
                if event.is_final_response():
                    user_text = user_transcript_final.strip()
                    assistant_text = assistant_transcript_final.strip()

                    logger.info(
                        f"[WS] Turn complete: session={session_id} "
                        f"user_chars={len(user_text)} assistant_chars={len(assistant_text)}"
                    )

                    # 4a. Persist conversation turn to Firestore
                    if user_text or assistant_text:
                        loop = asyncio.get_event_loop()
                        loop.run_in_executor(
                            None,
                            append_conversation_turn,
                            session_id,
                            user_text or "(voice input)",
                            assistant_text,
                        )

                    # 4b. Check for [FINALIZING] marker
                    is_finalizing = FINALIZING_MARKER in assistant_text

                    # 4c. Build conversation transcript for extraction.
                    # Append this turn to the running transcript (ADK session events
                    # hold audio blobs for voice, so _extract_conversation_text would
                    # return empty — use the accumulated text transcript instead).
                    if user_text:
                        transcript_lines.append(f"User: {user_text}")
                    if assistant_text:
                        transcript_lines.append(f"Consultant: {assistant_text}")
                    conversation_text = "\n".join(transcript_lines)

                    # 4d. Extract discovery fields + persist
                    try:
                        discovery_fields = await extract_discovery_fields(
                            conversation_text
                        )
                        logger.debug(
                            f"[WS] Discovery fields extracted: session={session_id} "
                            f"completeness={discovery_fields.get('completeness')}%"
                        )
                        loop = asyncio.get_event_loop()
                        loop.run_in_executor(
                            None, upsert_discovery_state, session_id, discovery_fields
                        )
                    except Exception as exc:
                        logger.warning(
                            f"[WS] extract_discovery_fields failed: session={session_id} {exc}"
                        )
                        discovery_fields = {
                            "completeness": 0,
                            "fields": {},
                            "missing_priority": [],
                        }

                    # 4e. Compile and persist SRS to Firestore (background)
                    asyncio.create_task(
                        _persist_srs_to_firestore(session_id, user_id, conversation_text)
                    )

                    # 4f. If [FINALIZING] detected, launch the finalizer pipeline
                    if is_finalizing:
                        logger.info(
                            f"[WS][FINALIZING] detected: session={session_id} — launching finalizer"
                        )
                        loop = asyncio.get_event_loop()
                        loop.run_in_executor(None, set_finalization_pending, session_id)
                        asyncio.create_task(
                            run_finalizer(
                                session_id=session_id,
                                user_id=user_id,
                                conversation_text=conversation_text,
                                discovery_fields=discovery_fields,
                            )
                        )

                    # 4g. Send turn_complete with metadata to the frontend
                    await websocket.send_text(
                        json.dumps(
                            {
                                "type": "turn_complete",
                                "finalizing": is_finalizing,
                            }
                        )
                    )

                    # Reset per-turn accumulators (transcript_lines grows across turns)
                    user_transcript_final = ""
                    assistant_transcript_final = ""

        except WebSocketDisconnect:
            logger.debug(f"[WS] Client disconnected during downstream")
        except GenaiAPIError as e:
            # Code 1000 = normal WebSocket close (user toggled voice off or navigated away)
            if "1000" in str(e):
                logger.info(
                    f"[WS] Gemini Live session closed normally: session={session_id}"
                )
            else:
                logger.error(f"[WS] Gemini Live API error: {e}")
                traceback.print_exc()
                try:
                    await websocket.send_text(
                        json.dumps({"type": "error", "message": str(e)})
                    )
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"[WS] Downstream error: {e}")
            traceback.print_exc()
            try:
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "error",
                            "message": str(e),
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
        logger.error(f"[WS] Connection error: {e}")
        traceback.print_exc()
    finally:
        logger.info(f"[WS] Connection closed: user={user_id} session={session_id}")
