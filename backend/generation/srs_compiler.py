"""
Compiles a structured Discovery Session JSON object from a session's conversation history.

Uses Gemini to map everything discussed in the conversation into the
Discovery Session structure, ready to be rendered into a Word document.
"""

import json
import time

from config import MODEL_SRS_COMPILER, init_vertex_ai
from google.adk.sessions import InMemorySessionService, Session
from logger import get_logger
from prompts.srs import SRS_EXTRACTION_PROMPT
from vertexai.generative_models import GenerativeModel

logger = get_logger(__name__)


def _get_model() -> GenerativeModel:
    init_vertex_ai()
    return GenerativeModel(MODEL_SRS_COMPILER)


def _extract_conversation_text(session: Session) -> str:
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


async def compile_srs_json_from_session(
    session_service: InMemorySessionService,
    app_name: str,
    user_id: str,
    session_id: str,
) -> dict | None:
    """Extract a full structured SRS JSON dict from the session conversation.

    Returns None if the session is not found or extraction fails.
    """
    session: Session | None = await session_service.get_session(
        app_name=app_name,
        user_id=user_id,
        session_id=session_id,
    )
    if session is None:
        return None

    conversation_text = _extract_conversation_text(session)
    if not conversation_text.strip():
        return None

    try:
        model = _get_model()
        prompt = SRS_EXTRACTION_PROMPT.format(conversation=conversation_text)
        logger.info(
            f"Model call started: model={MODEL_SRS_COMPILER} caller=compile_srs_json_from_session"
        )
        _t0 = time.perf_counter()
        response = model.generate_content(prompt)
        logger.info(
            f"Model call completed: model={MODEL_SRS_COMPILER} elapsed={time.perf_counter() - _t0:.2f}s"
        )
        raw = response.text.strip()

        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        return json.loads(raw)
    except Exception:
        return None
