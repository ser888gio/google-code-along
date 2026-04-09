"""
DataFlow diagram generation using Gemini via Vertex AI.

Two functions:
- check_dfd_completeness: scores how ready the conversation is for a DFD (0–100).
- generate_dataflow_diagram: produces a Mermaid flowchart (LR) DFD string.
"""

import json
import time

import google.generativeai as genai

from config import GOOGLE_API_KEY, MODEL_DATAFLOW
from logger import get_logger
from prompts.dataflow import DATAFLOW_COMPLETENESS_PROMPT, DATAFLOW_GENERATION_PROMPT

genai.configure(api_key=GOOGLE_API_KEY)

logger = get_logger(__name__)


def _get_model() -> genai.GenerativeModel:
    return genai.GenerativeModel(MODEL_DATAFLOW)


async def check_dfd_completeness(conversation_text: str) -> dict:
    """Return {"score": int, "missing": list[str]}.

    Score 0–100 reflecting how ready the conversation is to produce a DFD.
    Falls back to {"score": 0, "missing": ["Unable to evaluate"]} on error.
    """
    model = _get_model()
    prompt = DATAFLOW_COMPLETENESS_PROMPT.format(conversation=conversation_text)

    try:
        logger.info(
            f"Model call started: model={MODEL_DATAFLOW} caller=check_dfd_completeness"
        )
        _t0 = time.perf_counter()
        response = model.generate_content(prompt)
        logger.info(
            f"Model call completed: model={MODEL_DATAFLOW} elapsed={time.perf_counter() - _t0:.2f}s"
        )
        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except Exception as exc:
        return {"score": 0, "missing": [f"Evaluation error: {exc}"]}


async def generate_dataflow_diagram(conversation_text: str) -> str:
    """Return a Mermaid flowchart LR string representing the system as a DFD."""
    model = _get_model()
    prompt = DATAFLOW_GENERATION_PROMPT.format(conversation=conversation_text)

    logger.info(
        f"Model call started: model={MODEL_DATAFLOW} caller=generate_dataflow_diagram"
    )
    _t0 = time.perf_counter()
    response = model.generate_content(prompt)
    logger.info(
        f"Model call completed: model={MODEL_DATAFLOW} elapsed={time.perf_counter() - _t0:.2f}s"
    )
    mermaid = response.text.strip()

    # Strip markdown fences if the model wrapped the output
    if mermaid.startswith("```"):
        lines = mermaid.splitlines()
        inner = [line for line in lines if not line.strip().startswith("```")]
        mermaid = "\n".join(inner).strip()

    return mermaid
