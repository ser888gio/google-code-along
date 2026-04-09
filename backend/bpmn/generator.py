"""
BPMN diagram generation using Gemini via Vertex AI.

Two functions:
- check_completeness: scores how complete the conversation is (0–100).
- generate_bpmn_diagram: produces a Mermaid flowchart string.
"""

import json
import time

from config import MODEL_BPMN, init_vertex_ai
from logger import get_logger
from prompts.bpmn import BPMN_GENERATION_PROMPT, COMPLETENESS_PROMPT
from vertexai.generative_models import GenerativeModel

logger = get_logger(__name__)


def _get_model() -> GenerativeModel:
    init_vertex_ai()
    return GenerativeModel(MODEL_BPMN)


async def check_completeness(conversation_text: str) -> dict:
    """Return {"score": int, "missing": list[str]}.

    Score 0–100 reflecting how much RS information has been gathered.
    Falls back to {"score": 0, "missing": ["Unable to evaluate"]} on error.
    """
    model = _get_model()
    prompt = COMPLETENESS_PROMPT.format(conversation=conversation_text)

    try:
        logger.info(f"Model call started: model={MODEL_BPMN} caller=check_completeness")
        _t0 = time.perf_counter()
        response = model.generate_content(prompt)
        logger.info(
            f"Model call completed: model={MODEL_BPMN} elapsed={time.perf_counter() - _t0:.2f}s"
        )
        raw = response.text.strip()
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
    model = _get_model()
    prompt = BPMN_GENERATION_PROMPT.format(conversation=conversation_text)

    logger.info(f"Model call started: model={MODEL_BPMN} caller=generate_bpmn_diagram")
    _t0 = time.perf_counter()
    response = model.generate_content(prompt)
    logger.info(
        f"Model call completed: model={MODEL_BPMN} elapsed={time.perf_counter() - _t0:.2f}s"
    )
    mermaid = response.text.strip()

    # Strip markdown fences if the model wrapped the output anyway
    if mermaid.startswith("```"):
        lines = mermaid.splitlines()
        # Remove first and last fence lines
        inner = [l for l in lines if not l.strip().startswith("```")]
        mermaid = "\n".join(inner).strip()

    return mermaid
