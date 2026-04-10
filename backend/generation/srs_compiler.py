"""
Compiles a structured Discovery Session JSON object from a session's conversation history.

Uses Gemini to map everything discussed in the conversation into the
Discovery Session structure, ready to be rendered into a Word document.
"""

import json
import os

from google import genai

from google.adk.sessions import InMemorySessionService, Session

_MODEL_NAME = "gemini-2.0-flash-001"

SRS_EXTRACTION_PROMPT = """\
You are an expert technical writer. Given the following conversation between a user and an \
AI business consultant, extract all discussed information and compile it into a structured \
Discovery Session output document.

You MUST return ONLY valid JSON — no markdown fences, no commentary, no explanation.

Return a JSON object with exactly this structure:

{
  "context_and_business_problem": {
    "context": "<How it works today — high-level current process and where it hurts. What triggered the request (audit, legislation, deadline, efficiency goal).>",
    "business_problem": "<Who is affected — users, teams, approximate number of people or business units. Core pain points and frustrations.>"
  },
  "target_state_and_success": {
    "target_state": "<What exactly should be different? The desired future state compared to today.>",
    "success": "<3–5 measurable or observable success criteria. Priority classification: must-have / should-have / nice-to-have.>"
  },
  "scope_and_boundaries": {
    "scope_in_out": "<In-scope: features, processes, reports, automations. Out-of-scope: what we are consciously not doing now.>",
    "boundaries": "<Dependencies on other teams, ongoing projects, SME availability.>"
  },
  "data_systems_integrations_access": {
    "data_systems": "<What data is needed, where does it come from, who owns it? Data sensitivity (personal data, financial sensitivity, contracts).>",
    "integrations_access": "<Integration needs — SAP, data marts, SharePoint, email, documents, and other systems that must connect.>"
  }
}

Rules:
- Use only information explicitly stated or confirmed by the user in the conversation.
- Use "TBD" for fields where no information was provided.
- Keep all text concise and professional — this is a formal specification document.

Conversation:
---
{conversation}
---
"""


def _get_client() -> genai.Client:
    return genai.Client(api_key=os.getenv("GOOGLE_API_KEY", ""))


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
        client = _get_client()
        prompt = SRS_EXTRACTION_PROMPT.format(conversation=conversation_text)
        response = client.models.generate_content(model=_MODEL_NAME, contents=prompt)
        raw = (response.text or "").strip()

        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        return json.loads(raw)
    except Exception:
        return None
