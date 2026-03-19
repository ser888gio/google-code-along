import asyncio
import json
import uuid

from agent import rs_agent
from bpmn import check_completeness, generate_bpmn_diagram
from context import extract_rs_context
from dataflow import check_dfd_completeness, generate_dataflow_diagram
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from firestore import (
    append_conversation_turn,
    get_conversation_history,
    get_srs_fields,
    list_sessions,
    upsert_srs_fields,
)
from gcs import write_file
from generation import (
    compile_rs_from_session,
    compile_srs_json_from_session,
    markdown_to_pdf,
    srs_json_to_docx,
)
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel

load_dotenv()

app = FastAPI(title="RS Generator API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- ADK runner setup ---

session_service = InMemorySessionService()

APP_NAME = "rs_generator"

runner = Runner(
    app_name=APP_NAME,
    agent=rs_agent,
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
    gcs_path = write_file(
        path=destination,
        data=contents,
        content_type=file.content_type or "application/octet-stream",
    )
    return UploadResponse(gcs_path=gcs_path, filename=file.filename)


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Send a message to the RS consultant agent and get a response."""

    session_id = req.session_id or str(uuid.uuid4())

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

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, append_conversation_turn, session_id, req.message, reply)

    return ChatResponse(reply=reply, session_id=session_id)


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    """Stream the agent's response as Server-Sent Events."""

    session_id = req.session_id or str(uuid.uuid4())

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
                        # TODO: strip [FINALIZING] marker before yielding to client
                        #       so the user never sees the raw signal token.
                        #       Check: if "[FINALIZING]" in part.text, split it out.
                        yield f"data: {json.dumps({'text': part.text})}\n\n"

        full_reply = "".join(reply_parts)
        loop = asyncio.get_event_loop()
        loop.run_in_executor(
            None, append_conversation_turn, session_id, req.message, full_reply
        )

        # --- Finalization trigger ---
        # TODO: detect [FINALIZING] marker in full_reply and fire the finalizer pipeline:
        #
        #   if "[FINALIZING]" in full_reply:
        #       # 1. Signal frontend immediately — show "Finalizing your analysis..."
        #       yield f"data: {json.dumps({'event': 'finalizing'})}\n\n"
        #
        #       # 2. Collect current discovery fields for the finalizer
        #       #    TODO: call extract_discovery_fields(conversation_text) here
        #       #          or read them from the session state if discovery_agent stored them
        #
        #       # 3. Fire background task — does NOT block the SSE stream
        #       #    from agent.finalizer_agent import run_finalizer
        #       #    asyncio.create_task(run_finalizer(
        #       #        session_id=session_id,
        #       #        user_id=req.user_id,
        #       #        conversation_text=_extract_conversation_text(session),
        #       #        discovery_fields=discovery_fields,
        #       #    ))
        #
        #       # 4. When run_finalizer() completes it updates Firestore with
        #       #    finalization_status="complete". The frontend polls
        #       #    GET /analyses/{session_id} to detect completion.
        #       #    Alternatively: keep the SSE connection open and yield a
        #       #    "finalizing_complete" event when the background task finishes —
        #       #    but this requires holding the generator alive, which is complex.
        #       #    Recommended: Firestore polling from the frontend (simpler).

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
    from fastapi.responses import Response

    markdown = await compile_rs_from_session(
        session_service=session_service,
        app_name=APP_NAME,
        user_id=req.user_id,
        session_id=req.session_id,
    )
    if markdown is None:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=404,
            detail="No RS document found. Complete the conversation first.",
        )

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
    from fastapi import HTTPException
    from fastapi.responses import Response

    srs_json = await compile_srs_json_from_session(
        session_service=session_service,
        app_name=APP_NAME,
        user_id=req.user_id,
        session_id=req.session_id,
    )
    if srs_json is None:
        raise HTTPException(
            status_code=422,
            detail="Could not compile SRS from the conversation. Keep chatting to provide more details.",
        )

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

    if score < 90:
        return BpmnResponse(ready=False, score=score, missing=missing)

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

    if score < 70:
        return DataflowResponse(ready=False, score=score, missing=missing)

    mermaid = await generate_dataflow_diagram(conversation_text)
    return DataflowResponse(ready=True, mermaid=mermaid, score=score)


# --- Live RS context extraction ---


class ContextRequest(BaseModel):
    session_id: str
    user_id: str = "default_user"


class SectionData(BaseModel):
    filled: bool
    content: str | None


class ContextResponse(BaseModel):
    completeness: int
    sections: dict[str, SectionData]


@app.post("/context/extract", response_model=ContextResponse)
async def context_extract(req: ContextRequest):
    """Extract structured RS section data from the current conversation.

    Calls Gemini to map what has been discussed so far into the 8 RS sections.
    Always returns all 8 section keys. Returns completeness=0 with empty sections
    if the session is not found or Gemini fails.
    """
    session = await session_service.get_session(
        app_name=APP_NAME,
        user_id=req.user_id,
        session_id=req.session_id,
    )
    if session is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Session not found.")

    conversation_text = _extract_conversation_text(session)
    result = await extract_rs_context(conversation_text)

    # Fire-and-forget: persist full SRS to Firestore without blocking the response
    asyncio.create_task(
        _persist_srs_to_firestore(
            session_id=req.session_id,
            user_id=req.user_id,
        )
    )

    return result


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
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, upsert_srs_fields, session_id, srs_json)
    except Exception as exc:  # noqa: BLE001
        print(f"[Firestore] upsert failed for session {session_id}: {exc}")


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

    The frontend polls this endpoint after receiving the "finalizing" SSE event.
    Returns:
      - {"status": "pending"} while run_finalizer() is still running
      - {"status": "complete", "analysis": {...}} when done
      - {"status": "not_found"} if finalization was never triggered

    TODO: implement by reading finalization_status from Firestore:
          from firestore.writer import get_final_analysis
          result = get_final_analysis(session_id)
          if result is None:
              return {"status": "not_found"}
          if result.get("finalization_status") == "complete":
              return {"status": "complete", "analysis": result}
          return {"status": "pending"}

    TODO: alternatively, read directly from GCS analyses/{session_id}/final_analysis.json
          if it exists — that file is written last, so its existence = completion signal.
          This avoids the need for a finalization_status field in Firestore.
          Tradeoff: GCS read on every poll vs Firestore read (both are fast).
    """
    # TODO: implement
    return {"status": "not_found"}


@app.get("/firestore/data/{session_id}", response_model=FirestoreDataResponse)
async def firestore_data(session_id: str):
    """Return the latest SRS data stored in Firestore for *session_id*.

    The frontend polls this endpoint after each turn to refresh the right panel.
    Returns data=null if no document has been written yet.
    """
    loop = asyncio.get_event_loop()
    doc = await loop.run_in_executor(None, get_srs_fields, session_id)
    return FirestoreDataResponse(session_id=session_id, data=doc)
