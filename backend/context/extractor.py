"""
Structured RS context extraction using Gemini via Vertex AI.

Reads the current conversation from a session and maps what has been
discussed so far into the 8 RS document sections, returning a completeness
score and per-section { filled, content } data.
"""

import json
import os

import vertexai
from vertexai.generative_models import GenerativeModel

from .prompts import RS_EXTRACTION_PROMPT

_MODEL_NAME = "gemini-3-pro"

# Single source of truth for all 8 RS section keys.
# Used as the default/fallback so the frontend always receives all keys.
EMPTY_SECTIONS: dict = {
    "executive_summary":           {"filled": False, "content": None},
    "current_state":               {"filled": False, "content": None},
    "desired_future_state":        {"filled": False, "content": None},
    "scope":                       {"filled": False, "content": None},
    "functional_requirements":     {"filled": False, "content": None},
    "non_functional_requirements": {"filled": False, "content": None},
    "assumptions_and_constraints": {"filled": False, "content": None},
    "open_questions":              {"filled": False, "content": None},
}


def _get_model() -> GenerativeModel:
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    region_raw = os.getenv("GOOGLE_CLOUD_REGION", "europe-central2")
    # Strip zone suffix: "europe-central2-a" → "europe-central2"
    region = "-".join(region_raw.split("-")[:3])
    vertexai.init(project=project, location=region)
    return GenerativeModel(_MODEL_NAME)


async def extract_rs_context(conversation_text: str) -> dict:
    """Extract structured RS section data from the conversation.

    Returns:
        {
            "completeness": int (0-100),
            "sections": {
                "<section_key>": {"filled": bool, "content": str | None},
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

        # Ensure all 8 keys are present — fill any missing with defaults
        for key, default in EMPTY_SECTIONS.items():
            if key not in sections:
                sections[key] = dict(default)
            else:
                # Enforce null (not "") for unfilled content
                entry = sections[key]
                if not entry.get("filled", False):
                    entry["content"] = None

        return {
            "completeness": max(0, min(100, int(parsed.get("completeness", 0)))),
            "sections": sections,
        }

    except Exception:
        return {"completeness": 0, "sections": dict(EMPTY_SECTIONS)}
