"""
Structured SRS context extraction using Gemini via Vertex AI.

Reads the current conversation and maps what has been discussed into
subsection-level fields of the IEEE 830 SRS structure, returning a
completeness score and per-subsection { filled, content } data.
"""

import json
import os

import vertexai
from vertexai.generative_models import GenerativeModel

from .prompts import RS_EXTRACTION_PROMPT

_MODEL_NAME = "gemini-2.0-flash-001"

# All 26 SRS subsection keys in document order.
EMPTY_SECTIONS: dict = {
    "1_1_purpose":                   {"filled": False, "content": None},
    "1_2_project_scope":             {"filled": False, "content": None},
    "1_3_requester":                 {"filled": False, "content": None},
    "1_4_product_owner":             {"filled": False, "content": None},
    "1_5_sponsor":                   {"filled": False, "content": None},
    "1_6_delivery_responsibility":   {"filled": False, "content": None},
    "2_1_product_perspective":       {"filled": False, "content": None},
    "2_2_product_features":          {"filled": False, "content": None},
    "2_3_user_classes":              {"filled": False, "content": None},
    "2_4_operating_environment":     {"filled": False, "content": None},
    "2_5_design_constraints":        {"filled": False, "content": None},
    "2_6_user_documentation":        {"filled": False, "content": None},
    "2_7_assumptions_dependencies":  {"filled": False, "content": None},
    "3_system_features":             {"filled": False, "content": None},
    "4_1_user_interfaces":           {"filled": False, "content": None},
    "4_2_hardware_interfaces":       {"filled": False, "content": None},
    "4_3_software_interfaces":       {"filled": False, "content": None},
    "4_4_communications_interfaces": {"filled": False, "content": None},
    "5_1_performance":               {"filled": False, "content": None},
    "5_2_safety":                    {"filled": False, "content": None},
    "5_3_security":                  {"filled": False, "content": None},
    "5_4_quality_attributes":        {"filled": False, "content": None},
    "6_other_requirements":          {"filled": False, "content": None},
    "appendix_a_glossary":           {"filled": False, "content": None},
    "appendix_b_models":             {"filled": False, "content": None},
    "appendix_c_issues":             {"filled": False, "content": None},
}


def _get_model() -> GenerativeModel:
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    region_raw = os.getenv("GOOGLE_CLOUD_REGION", "europe-central2")
    # Strip zone suffix: "europe-central2-a" → "europe-central2"
    region = "-".join(region_raw.split("-")[:3])
    vertexai.init(project=project, location=region)
    return GenerativeModel(_MODEL_NAME)


async def extract_rs_context(conversation_text: str) -> dict:
    """Extract SRS subsection data from the conversation.

    Returns:
        {
            "completeness": int (0-100),
            "sections": {
                "<subsection_key>": {"filled": bool, "content": str | None},
                ...  (always all 26 keys)
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
