import json
import os
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from google.cloud import storage

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agent import rs_agent
from generation import compile_rs_from_session, markdown_to_pdf
from bpmn import check_completeness, generate_bpmn_diagram
from context import extract_rs_context

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
    bucket_name = os.getenv("GCS_BUCKET_NAME", "hackathon-skoda")
    destination = f"sessions/{session_id}/{file.filename}"

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(destination)

    contents = await file.read()
    blob.upload_from_string(contents, content_type=file.content_type or "application/octet-stream")

    return UploadResponse(
        gcs_path=f"gs://{bucket_name}/{destination}",
        filename=file.filename,
    )


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

    return ChatResponse(
        reply="".join(reply_parts),
        session_id=session_id,
    )


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
        yield f"data: {{\"session_id\": \"{session_id}\"}}\n\n"

        async for event in runner.run_async(
            user_id=req.user_id,
            session_id=session_id,
            new_message=user_content,
        ):
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        yield f"data: {json.dumps({'text': part.text})}\n\n"

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
    return result
