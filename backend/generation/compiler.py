"""
Extracts the Requirement Specification document from a chat session.

The agent is instructed to output [GENERATE_RS] followed by the full RS in
Markdown when the user confirms generation. This module finds that marker in
the session history and returns the document text.

If no marker is found, it returns None — the caller can then ask the agent
to generate the document explicitly.
"""

from config import RS_MARKER
from google.adk.sessions import InMemorySessionService, Session


async def compile_rs_from_session(
    session_service: InMemorySessionService,
    app_name: str,
    user_id: str,
    session_id: str,
) -> str | None:
    """Extract the RS markdown from the session's conversation history.

    Scans agent messages in reverse order (most recent first) looking for
    the [GENERATE_RS] marker. Returns everything after the marker as the
    RS document. Returns None if no document has been generated yet.
    """
    session: Session | None = await session_service.get_session(
        app_name=app_name,
        user_id=user_id,
        session_id=session_id,
    )
    if session is None:
        return None

    # Walk events in reverse to find the most recent RS generation
    for event in reversed(session.events or []):
        if not event.content or not event.content.parts:
            continue
        if event.content.role != "model":
            continue

        full_text = "".join(part.text for part in event.content.parts if part.text)

        if RS_MARKER in full_text:
            # Return everything after the marker
            _, _, rs_body = full_text.partition(RS_MARKER)
            return rs_body.strip()

    return None
    return None
