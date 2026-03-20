"""
Structured discovery context extraction using Gemini via Vertex AI.

Reads the current conversation and maps what has been discussed into
the 8 fields of the Discovery Session agenda, returning a
completeness score and per-field { filled, content } data.
"""

import json
import time

from config import MODEL_CONTEXT, init_vertex_ai
from logger import get_logger
from prompts.context import RS_EXTRACTION_PROMPT
from vertexai.generative_models import GenerativeModel

logger = get_logger(__name__)

# All 8 discovery session fields.
EMPTY_SECTIONS: dict = {
    "1_context": {"filled": False, "content": None},
    "1_business_problem": {"filled": False, "content": None},
    "2_target_state": {"filled": False, "content": None},
    "2_success": {"filled": False, "content": None},
    "3_scope_in_out": {"filled": False, "content": None},
    "3_boundaries": {"filled": False, "content": None},
    "4_data_systems": {"filled": False, "content": None},
    "4_integrations_access": {"filled": False, "content": None},
}


def _get_model() -> GenerativeModel:
    init_vertex_ai()
    return GenerativeModel(MODEL_CONTEXT)


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

    logger.debug("Extracting RS context from conversation transcript")
    try:
        model = _get_model()
        prompt = RS_EXTRACTION_PROMPT.format(conversation=conversation_text)
        logger.info(
            f"Model call started: model={MODEL_CONTEXT} caller=extract_rs_context"
        )
        _t0 = time.perf_counter()
        response = model.generate_content(prompt)
        logger.info(
            f"Model call completed: model={MODEL_CONTEXT} elapsed={time.perf_counter() - _t0:.2f}s"
        )
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

        completeness = max(0, min(100, int(parsed.get("completeness", 0))))
        filled = sum(1 for s in sections.values() if s.get("filled"))
        logger.info(
            f"RS context extracted: completeness={completeness}% filled_sections={filled}/{len(sections)}"
        )
        return {"completeness": completeness, "sections": sections}

    except Exception as exc:
        logger.warning(f"extract_rs_context failed: {exc}")
        return {"completeness": 0, "sections": dict(EMPTY_SECTIONS)}
