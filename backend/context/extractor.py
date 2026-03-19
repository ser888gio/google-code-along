"""
Structured discovery context extraction using Gemini via Vertex AI.

Reads the current conversation and maps what has been discussed into
the 8 fields of the Discovery Session agenda, returning a
completeness score and per-field { filled, content } data.
"""

import json
import os

import vertexai
from vertexai.generative_models import GenerativeModel

from .prompts import RS_EXTRACTION_PROMPT

_MODEL_NAME = "gemini-2.0-flash-001"

# All 8 discovery session fields.
EMPTY_SECTIONS: dict = {
    "1_context":             {"filled": False, "content": None},
    "1_business_problem":    {"filled": False, "content": None},
    "2_target_state":        {"filled": False, "content": None},
    "2_success":             {"filled": False, "content": None},
    "3_scope_in_out":        {"filled": False, "content": None},
    "3_boundaries":          {"filled": False, "content": None},
    "4_data_systems":        {"filled": False, "content": None},
    "4_integrations_access": {"filled": False, "content": None},
}


def _get_model() -> GenerativeModel:
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    region_raw = os.getenv("GOOGLE_CLOUD_REGION", "europe-central2")
    # Strip zone suffix: "europe-central2-a" → "europe-central2"
    region = "-".join(region_raw.split("-")[:3])
    vertexai.init(project=project, location=region)
    return GenerativeModel(_MODEL_NAME)


async def extract_rs_context(conversation_text: str) -> dict:
    """Extract discovery session data from the conversation.

    Returns:
        {
            "completeness": int (0-100),
            "sections": {
                "<field_key>": {"filled": bool, "content": str | None},
                ...  (always all 8 keys)
            }
        }

    Never raises — returns empty sections on any failure.
    """
    if not conversation_text.strip():
        return {"completeness": 0, "sections": dict(EMPTY_SECTIONS)}

    try:
        model = _get_model()
        prompt = RS_EXTRACTION_PROMPT.format(conversation=conversation_text)
        response = model.generate_content(prompt)
        raw = response.text.strip()

        # Strip markdown fences the model may add despite instructions
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        parsed = json.loads(raw)
        sections = parsed.get("sections", {})

        # Ensure all keys are present and enforce null for unfilled entries
        for key, default in EMPTY_SECTIONS.items():
            if key not in sections:
                sections[key] = dict(default)
            else:
                entry = sections[key]
                if not entry.get("filled", False):
                    entry["content"] = None

        return {
            "completeness": max(0, min(100, int(parsed.get("completeness", 0)))),
            "sections": sections,
        }

    except Exception:
        return {"completeness": 0, "sections": dict(EMPTY_SECTIONS)}
