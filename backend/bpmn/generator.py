"""
BPMN diagram generation using Gemini via Vertex AI.

Two functions:
- check_completeness: scores how complete the conversation is (0–100).
- generate_bpmn_diagram: produces a Mermaid flowchart string.
"""

import json
import os

import vertexai
from vertexai.generative_models import GenerativeModel

from .prompts import BPMN_GENERATION_PROMPT, COMPLETENESS_PROMPT

_MODEL_NAME = "gemini-3-pro"


def _get_model() -> GenerativeModel:
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    # Region for Vertex AI must be a region, not a zone — strip the zone suffix
    region_raw = os.getenv("GOOGLE_CLOUD_REGION", "europe-central2")
    region = "-".join(region_raw.split("-")[:3])  # e.g. "europe-central2-a" → "europe-central2"
    vertexai.init(project=project, location=region)
    return GenerativeModel(_MODEL_NAME)


async def check_completeness(conversation_text: str) -> dict:
    """Return {"score": int, "missing": list[str]}.

    Score 0–100 reflecting how much RS information has been gathered.
    Falls back to {"score": 0, "missing": ["Unable to evaluate"]} on error.
    """
    model = _get_model()
    prompt = COMPLETENESS_PROMPT.format(conversation=conversation_text)

    try:
        response = model.generate_content(prompt)
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

    response = model.generate_content(prompt)
    mermaid = response.text.strip()

    # Strip markdown fences if the model wrapped the output anyway
    if mermaid.startswith("```"):
        lines = mermaid.splitlines()
        # Remove first and last fence lines
        inner = [l for l in lines if not l.strip().startswith("```")]
        mermaid = "\n".join(inner).strip()

    return mermaid
