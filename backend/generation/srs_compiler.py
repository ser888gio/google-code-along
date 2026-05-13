"""
Compiles a structured Discovery Session JSON object from a session's
conversation history.

Uses Gemini to map everything discussed in the conversation into the
Discovery Session structure, ready to be rendered into a Word document.
"""

import json
import logging

from config import GOOGLE_API_KEY, MODEL_SRS_COMPILER
from google import genai
from google.adk.sessions import InMemorySessionService, Session
from utils import extract_conversation_text

logger = logging.getLogger(__name__)

SRS_EXTRACTION_PROMPT = """\
You are an expert technical writer. Given the following conversation between
a user and an Discovery Agent, extract all discussed information and compile
it into a structured Discovery Session output document.

You MUST return ONLY valid JSON - no markdown fences, no commentary, no explanation.

Return a JSON object with exactly this structure:

{
  "context_and_business_problem": {
    "context": "<How it works today - high-level current process and where "
               "it hurts. What triggered the request (audit, legislation, "
               "deadline, efficiency goal).>",
    "business_problem": "<Who is affected - users, teams, approximate "
                        "number of people or business units. Core pain "
                        "points and frustrations.>"
  },
  "target_state_and_success": {
    "target_state": "<What exactly should be different? The desired future "
                    "state compared to today.>",
    "success": "<3-5 measurable or observable success criteria. Priority "
               "classification: must-have / should-have / nice-to-have.>"
  },
  "scope_and_boundaries": {
    "scope_in_out": "<In-scope: features, processes, reports, automations. "
                    "Out-of-scope: what we are consciously not doing now.>",
    "boundaries": "<Dependencies on other teams, ongoing projects, "
                  "SME availability.>"
  },
  "data_systems_integrations_access": {
    "data_systems": "<What data is needed, where does it come from, who "
                    "owns it? Data sensitivity (personal data, financial "
                    "sensitivity, contracts).>",
    "integrations_access": "<Integration needs - SAP, data marts, "
                           "SharePoint, email, documents, and other "
                           "systems that must connect.>"
  }
}

Rules:
- Use only information explicitly stated or confirmed by the user in the conversation.
- Use "TBD" for fields where no information was provided.
- Keep all text concise and professional - this is a formal specification document.

Conversation:
---
{conversation}
---
"""


_genai_client = genai.Client(api_key=GOOGLE_API_KEY)


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

    conversation_text = extract_conversation_text(session)
    if not conversation_text.strip():
        return None

    try:
        # Use .replace() not .format(): user transcript may contain braces
        # that would cause a KeyError if str.format() tried to interpret them.
        prompt = SRS_EXTRACTION_PROMPT.replace("{conversation}", conversation_text)
        response = _genai_client.models.generate_content(model=MODEL_SRS_COMPILER, contents=prompt)
        raw = (response.text or "").strip()

        # Strip markdown fences if present.
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        return json.loads(raw)
    except Exception:
        logger.error("SRS compilation failed", exc_info=True)
        return None
