"""
Compiles a structured SRS JSON object from a session's conversation history.

Uses Gemini to map everything discussed in the conversation into the full
IEEE 830 SRS structure, ready to be rendered into a Word document.
"""

import json
import os

import vertexai
from vertexai.generative_models import GenerativeModel

from google.adk.sessions import InMemorySessionService, Session

_MODEL_NAME = "gemini-2.0-flash-001"

SRS_EXTRACTION_PROMPT = """\
You are an expert technical writer. Given the following conversation between a user and an \
AI business consultant, extract all discussed information and compile it into a complete \
Software Requirements Specification (SRS) following the IEEE 830 standard.

You MUST return ONLY valid JSON — no markdown fences, no commentary, no explanation.

Return a JSON object with exactly this structure:

{
  "introduction": {
    "purpose": {
      "product_name": "<project/product name>",
      "content": "<purpose and scope of this SRS document>"
    },
    "project_scope": "<short description of the software, its purpose, benefits, and goals>",
    "requester": "<name of the person who came up with the idea>",
    "product_owner": "<name of the product owner responsible for the project>",
    "sponsor": "<name of the person financing the project>",
    "delivery_responsibility": "<name of the IT delivery responsible person>"
  },
  "overall_description": {
    "product_perspective": "<context and origin of the product>",
    "product_features": "<high-level summary of major features>",
    "user_classes": "<user types/roles and their characteristics>",
    "operating_environment": "<hardware, OS, and software environment>",
    "design_constraints": "<policies, regulations, hardware limits, technology constraints>",
    "user_documentation": "<user manuals, online help, tutorials to be delivered>",
    "assumptions_and_dependencies": "<assumed factors and project dependencies>"
  },
  "system_features": [
    {
      "name": "<feature name>",
      "description_and_priority": "<description and High/Medium/Low priority>",
      "stimulus_response": "<user actions and system responses>",
      "functional_requirements": {
        "REQ-1": "<requirement text>",
        "REQ-2": "<requirement text>"
      }
    }
  ],
  "external_interface_requirements": {
    "user_interfaces": "<UI characteristics, GUI standards, screen layout>",
    "hardware_interfaces": "<hardware components and interfaces>",
    "software_interfaces": "<other software, APIs, databases, libraries>",
    "communications_interfaces": "<network protocols, communications requirements>"
  },
  "nonfunctional_requirements": {
    "performance": "<performance requirements under various conditions>",
    "safety": "<safety requirements, safeguards, certifications>",
    "security": "<security and privacy requirements, authentication>",
    "quality_attributes": "<availability, reliability, maintainability, usability, etc.>"
  },
  "other_requirements": "<database, legal, internationalization, or other requirements>",
  "appendices": {
    "glossary": "<terms, acronyms, and abbreviations>",
    "analysis_models": "<data flow diagrams, class diagrams, etc. — describe if discussed>",
    "issues_list": "<open requirements issues, TBDs, pending decisions>"
  }
}

Rules:
- Use only information explicitly stated or confirmed by the user in the conversation.
- Use "TBD" for fields where no information was provided.
- For "system_features", create one object per distinct feature discussed.
- REQ identifiers must be unique across all features (REQ-1, REQ-2, REQ-3, ...).
- Keep all text concise and professional — this is a formal specification document.

Conversation:
---
{conversation}
---
"""


def _get_model() -> GenerativeModel:
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    region_raw = os.getenv("GOOGLE_CLOUD_REGION", "europe-central2")
    region = "-".join(region_raw.split("-")[:3])
    vertexai.init(project=project, location=region)
    return GenerativeModel(_MODEL_NAME)


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
        response = model.generate_content(prompt)
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
