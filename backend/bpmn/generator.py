"""
BPMN diagram generation using Gemini via Vertex AI.

Two functions:
- check_completeness: scores how complete the conversation is (0–100).
- generate_bpmn_diagram: produces a Mermaid flowchart string.
"""

import json
import time

from config import GOOGLE_API_KEY, MODEL_BPMN
from google import genai
from logger import get_logger
from prompts.bpmn import BPMN_GENERATION_PROMPT, COMPLETENESS_PROMPT

_genai_client = genai.Client(api_key=GOOGLE_API_KEY)

logger = get_logger(__name__)


async def check_completeness(conversation_text: str) -> dict:
    """Return {"score": int, "missing": list[str]}.

    Score 0–100 reflecting how much RS information has been gathered.
    Falls back to {"score": 0, "missing": ["Unable to evaluate"]} on error.
    """
    # Use .replace() not .format() — user transcript may contain literal braces.
    prompt = COMPLETENESS_PROMPT.replace("{conversation}", conversation_text)

    try:
        logger.info(f"Model call started: model={MODEL_BPMN} caller=check_completeness")
        _t0 = time.perf_counter()
        response = _genai_client.models.generate_content(
            model=MODEL_BPMN, contents=prompt
        )
        logger.info(
            f"Model call completed: model={MODEL_BPMN} elapsed={time.perf_counter() - _t0:.2f}s"
        )
        raw = (response.text or "").strip()
        # Strip accidental markdown fences
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except Exception as exc:
        return {"score": 0, "missing": [f"Evaluation error: {exc}"]}


async def generate_bpmn_diagram(conversation_text: str) -> str:
    """Return a Mermaid flowchart string representing the To-Be BPMN process."""
    # Use .replace() not .format() — user transcript may contain literal braces.
    prompt = BPMN_GENERATION_PROMPT.replace("{conversation}", conversation_text)

    logger.info(f"Model call started: model={MODEL_BPMN} caller=generate_bpmn_diagram")
    _t0 = time.perf_counter()
    response = _genai_client.models.generate_content(model=MODEL_BPMN, contents=prompt)
    logger.info(
        f"Model call completed: model={MODEL_BPMN} elapsed={time.perf_counter() - _t0:.2f}s"
    )
    mermaid = (response.text or "").strip()

    # Strip markdown fences if the model wrapped the output anyway
    if mermaid.startswith("```"):
        lines = mermaid.splitlines()
        # Remove first and last fence lines
        inner = [line for line in lines if not line.strip().startswith("```")]
        mermaid = "\n".join(inner).strip()

    return mermaid
