import json
import os
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agent import rs_agent

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
