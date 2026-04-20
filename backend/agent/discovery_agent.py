"""
Discovery Agent — Form Field Tracker.

Responsibility: analyze the conversation transcript after every user message and
return a structured JSON object showing which of the 22 required IT use case fields
have been collected, their current values, and what still needs to be asked.

Used by the orchestrator as an AgentTool:
  - Called after every user turn
  - Returns completeness score (0-100), all 22 field values, and a prioritized list
    of the most important missing fields so the orchestrator knows what to ask next

Why a dedicated agent (not just a function):
  - ADK AgentTool lets the orchestrator invoke it naturally within the conversation loop
  - Field definitions and extraction logic stay encapsulated here, easy to update
  - Can be tested and improved independently

Model: Gemini Flash — extraction only, no deep reasoning needed, needs to be fast
"""

import asyncio
import json
import time

from google import genai

from config import GOOGLE_API_KEY, MODEL_DISCOVERY
from google.adk.agents import Agent
from logger import get_logger
from prompts.agent import DISCOVERY_SYSTEM_PROMPT
from prompts.context import DISCOVERY_EXTRACTION_PROMPT

_genai_client = genai.Client(api_key=GOOGLE_API_KEY)

logger = get_logger(__name__)

discovery_agent = Agent(
    name="discovery_agent",
    description=(
        "Analyzes a conversation transcript and extracts all 22 IT use case form fields. "
        "Returns a JSON object with field values, completeness score (0-100), and the "
        "top 3 missing fields to prioritize next."
    ),
    model=MODEL_DISCOVERY,
    instruction=DISCOVERY_SYSTEM_PROMPT,
    tools=[],  # Pure text-in / JSON-out — no external tools needed
)


# ---------------------------------------------------------------------------
# Standalone extraction helper (for use outside ADK context, e.g. REST endpoints)
# ---------------------------------------------------------------------------
# TODO: replace the existing extract_rs_context() in context/extractor.py
#       with this function once the 22-field schema is finalized.
#       The old 8-field extractor can be kept temporarily for frontend backwards compat.


async def extract_discovery_fields(conversation_text: str) -> dict:
    """Extract all 22 form fields from a conversation transcript.

    Calls Gemini Flash directly (not via ADK runner) so it can be used as
    a fire-and-forget task from main.py after every chat turn.

    Returns:
        {
            "completeness": int (0-100),
            "fields": {
                "<field_key>": {"filled": bool, "value": str | null},
                ...  (always all 22 keys)
            },
            "missing_priority": [str, ...]  (up to 3 highest-priority missing fields)
        }

    Never raises — returns empty state on any failure.
    """

    if not conversation_text.strip():
        return {"completeness": 0, "fields": dict(EMPTY_FIELDS), "missing_priority": []}

    logger.debug("Extracting discovery fields from conversation transcript")
    try:
        prompt = DISCOVERY_EXTRACTION_PROMPT.replace(
            "{conversation}", conversation_text
        )
        logger.info(
            f"Model call started: model={MODEL_DISCOVERY} caller=extract_discovery_fields"
        )
        _t0 = time.perf_counter()
        response = await asyncio.to_thread(
            _genai_client.models.generate_content,
            model=MODEL_DISCOVERY,
            contents=prompt,
        )
        logger.info(
            f"Model call completed: model={MODEL_DISCOVERY} elapsed={time.perf_counter() - _t0:.2f}s"
        )
        raw = (response.text or "").strip()

        # Strip markdown fences the model sometimes adds despite instructions
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        parsed = json.loads(raw)
        fields = parsed.get("fields", {})

        # Ensure all 22 keys are always present and nulls are consistent
        for key in FIELD_SCHEMA:
            if key not in fields:
                fields[key] = {"filled": False, "value": None}
            else:
                if not fields[key].get("filled", False):
                    fields[key]["value"] = None

        result = {
            "completeness": max(0, min(100, int(parsed.get("completeness", 0)))),
            "fields": fields,
            "missing_priority": parsed.get("missing_priority", [])[:3],
        }
        logger.info(
            f"Discovery extraction done: completeness={result['completeness']}% missing_priority={result['missing_priority']}"
        )
        return result

    except Exception as exc:
        logger.warning(f"extract_discovery_fields failed: {exc}")
        return {"completeness": 0, "fields": dict(EMPTY_FIELDS), "missing_priority": []}


# ---------------------------------------------------------------------------
# Field schema — single source of truth for all 22 fields
# ---------------------------------------------------------------------------

FIELD_SCHEMA: dict[str, dict] = {
    # Section 1 — Identity & Current State
    "use_case_title": {"label": "Use Case Title (EN)", "required": True, "section": 1},
    "department": {"label": "Customer Department", "required": True, "section": 1},
    "requestor": {"label": "Requestor", "required": True, "section": 1},
    "product_owner": {"label": "Product Owner", "required": True, "section": 1},
    "process_as_is": {
        "label": "Process Description / As-Is",
        "required": True,
        "section": 1,
    },
    "process_context": {"label": "Process Context", "required": True, "section": 1},
    "trigger": {"label": "Trigger", "required": True, "section": 1},
    # Section 2 — Target State
    "purpose_to_be": {"label": "Purpose / To-Be", "required": True, "section": 2},
    # Section 3 — Value & ROI
    "saved_time_hours_per_year": {
        "label": "Saved Time (hours/year)",
        "required": False,
        "section": 3,
    },  # approximate OK
    "cost_saving": {
        "label": "Cost Saving",
        "required": False,
        "section": 3,
    },  # approximate OK
    "revenue_increase": {
        "label": "Revenue Increase",
        "required": False,
        "section": 3,
    },  # approximate OK
    "impacted_users": {"label": "Impacted Users", "required": True, "section": 3},
    "add_value": {"label": "Added Value", "required": True, "section": 3},
    # Section 4 — Priority & Risk
    "time_criticality": {"label": "Time Criticality", "required": True, "section": 4},
    "strategic_impact": {"label": "Strategic Impact", "required": True, "section": 4},
    "risk_avoidance": {
        "label": "Risk Avoidance",
        "required": False,
        "section": 4,
    },  # approximate OK
    # Section 5 — Technical Context
    "systems_and_tools": {
        "label": "Systems & Tools Involved",
        "required": True,
        "section": 5,
    },
    "document_types": {
        "label": "Types of Documents Involved",
        "required": True,
        "section": 5,
    },
    "data_security_classification": {
        "label": "Data Security Classification",
        "required": True,
        "section": 5,
    },
    "solution_type": {"label": "Solution Type", "required": True, "section": 5},
    # Free-form (optional — not counted toward completeness score)
    "comments": {"label": "Comments", "required": False, "section": 6},
    "attachments": {
        "label": "Attachments (GCS paths)",
        "required": False,
        "section": 6,
    },
}

# Pre-built empty state — used as fallback and as the initial state in the frontend
# TODO: frontend RsLiveTemplate should switch from its current hardcoded 8-section
#       structure to rendering this FIELD_SCHEMA dynamically grouped by section number
EMPTY_FIELDS: dict = {key: {"filled": False, "value": None} for key in FIELD_SCHEMA}

# Fields that count toward the completeness score (required=True, not optional)
# TODO: confirm with team whether ROI fields (cost_saving, saved_time, revenue_increase)
#       should be required or optional for the completeness gate (currently optional)
REQUIRED_FIELDS = [k for k, v in FIELD_SCHEMA.items() if v["required"]]
