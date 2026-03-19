"""
DataFlow diagram generation using Gemini via Vertex AI.

Two functions:
- check_dfd_completeness: scores how ready the conversation is for a DFD (0–100).
- generate_dataflow_diagram: produces a Mermaid flowchart (LR) DFD string.
"""

import json
import os

import vertexai
from vertexai.generative_models import GenerativeModel

from .prompts import DATAFLOW_COMPLETENESS_PROMPT, DATAFLOW_GENERATION_PROMPT

_MODEL_NAME = "gemini-3-pro"


def _get_model() -> GenerativeModel:
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    region_raw = os.getenv("GOOGLE_CLOUD_REGION", "europe-central2")
    region = "-".join(region_raw.split("-")[:3])
    vertexai.init(project=project, location=region)
    return GenerativeModel(_MODEL_NAME)


async def check_dfd_completeness(conversation_text: str) -> dict:
    """Return {"score": int, "missing": list[str]}.

    Score 0–100 reflecting how ready the conversation is to produce a DFD.
    Falls back to {"score": 0, "missing": ["Unable to evaluate"]} on error.
    """
    model = _get_model()
    prompt = DATAFLOW_COMPLETENESS_PROMPT.format(conversation=conversation_text)

    try:
        response = model.generate_content(prompt)
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

    response = model.generate_content(prompt)
    mermaid = response.text.strip()

    # Strip markdown fences if the model wrapped the output
    if mermaid.startswith("```"):
        lines = mermaid.splitlines()
        inner = [line for line in lines if not line.strip().startswith("```")]
        mermaid = "\n".join(inner).strip()

    return mermaid
