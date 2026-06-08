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
import hashlib
import json
import time

from config import GOOGLE_API_KEY, MODEL_DISCOVERY
from field_schema import (
    EMPTY_FIELDS,
    FIELD_SCHEMA,
    OPTIONAL_FIELDS,
    REQUIRED_FIELDS,
)
from google import genai
from google.adk.agents import Agent
from logger import get_logger
from observability.cost import compute_cost
from observability.metrics import (
    record_cache_hit_ratio,
    record_cost,
    record_operation_duration,
    record_tokens,
)
from observability.safety import CostCircuitBreakerTripped, add_session_cost
from observability.turns import record_model_call
from opentelemetry import trace
from opentelemetry.trace import SpanKind
from prompts.agent import DISCOVERY_SYSTEM_PROMPT
from prompts.context import DISCOVERY_EXTRACTION_PROMPT
from solution_configs import get_all_field_shapes
from utils import format_prompt_data_lines
from workflow_state import FieldStatus, WorkflowState

_genai_client = genai.Client(api_key=GOOGLE_API_KEY)

logger = get_logger(__name__)

discovery_agent = Agent(
    name="discovery_agent",
    description=(
        "Analyzes a conversation transcript and extracts all 22 IT use case "
        "form fields. "
        "Returns a JSON object with field values, completeness score (0-100), and the "
        "top 3 missing fields to prioritize next."
    ),
    model=MODEL_DISCOVERY,
    instruction=DISCOVERY_SYSTEM_PROMPT,
    tools=[],  # Pure text-in / JSON-out — no external tools needed
)


def _empty_discovery_result() -> dict:
    return {"completeness": 0, "fields": dict(EMPTY_FIELDS), "missing_priority": []}


def _build_discovery_prompt(conversation_text: str, solution_type: str | None) -> str:
    # Use .replace() not .format() because transcripts can contain literal braces.
    return DISCOVERY_EXTRACTION_PROMPT.replace(
        "{field_shapes}",
        get_all_field_shapes(solution_type),
    ).replace(
        "{conversation}",
        format_prompt_data_lines(conversation_text),
    )


def _strip_markdown_json_fence(raw: str) -> str:
    raw = raw.strip()
    if not raw.startswith("```"):
        return raw

    raw = raw.split("```")[1]
    if raw.startswith("json"):
        raw = raw[4:]
    return raw.strip()


def _session_id_hash(session_id: str | None) -> str:
    return hashlib.sha256(session_id.encode()).hexdigest()[:16] if session_id else "batch"


def _discovery_usage_counts(usage) -> dict[str, int]:
    return {
        "input_tokens": getattr(usage, "prompt_token_count", 0) or 0,
        "output_tokens": getattr(usage, "candidates_token_count", 0) or 0,
        "cache_read": getattr(usage, "cached_content_token_count", 0) or 0,
    }


def _record_discovery_usage(usage, session_id: str | None, span) -> None:
    if not usage:
        return

    counts = _discovery_usage_counts(usage)
    span.set_attribute("gen_ai.usage.input_tokens", counts["input_tokens"])
    span.set_attribute("gen_ai.usage.output_tokens", counts["output_tokens"])
    span.set_attribute("gen_ai.usage.cache_read.input_tokens", counts["cache_read"])
    cost_usd = compute_cost(MODEL_DISCOVERY, usage)
    span.set_attribute("cost_usd", cost_usd)
    record_tokens(
        counts["input_tokens"],
        model=MODEL_DISCOVERY,
        token_type="input",
        feature="discovery_extract",
    )
    record_tokens(
        counts["output_tokens"],
        model=MODEL_DISCOVERY,
        token_type="output",
        feature="discovery_extract",
    )
    if counts["cache_read"]:
        record_tokens(
            counts["cache_read"],
            model=MODEL_DISCOVERY,
            token_type="cache_read",
            feature="discovery_extract",
        )
    record_cache_hit_ratio(
        model=MODEL_DISCOVERY,
        input_tokens=counts["input_tokens"],
        cache_read_tokens=counts["cache_read"],
    )
    record_cost(
        cost_usd,
        model=MODEL_DISCOVERY,
        feature="discovery_extract",
        session_id_hash=_session_id_hash(session_id),
    )
    record_model_call(
        model=MODEL_DISCOVERY,
        feature="discovery_extract",
        input_tokens=counts["input_tokens"],
        output_tokens=counts["output_tokens"],
        cache_read_tokens=counts["cache_read"],
        cost_usd=cost_usd,
    )
    add_session_cost(session_id, cost_usd)


def _normalize_discovery_result(parsed: dict) -> dict:
    fields = parsed.get("fields", {})

    # Ensure all 22 keys are always present and nulls are consistent.
    for key in FIELD_SCHEMA:
        if key not in fields:
            fields[key] = {"filled": False, "value": None}
        elif not fields[key].get("filled", False):
            fields[key]["value"] = None

    return {
        "completeness": max(0, min(100, int(parsed.get("completeness", 0)))),
        "fields": fields,
        "missing_priority": parsed.get("missing_priority", [])[:3],
    }


# ---------------------------------------------------------------------------
# Standalone extraction helper (for use outside ADK context, e.g. REST endpoints)
# ---------------------------------------------------------------------------
# TODO: replace the existing extract_rs_context() in context/extractor.py
#       with this function once the 22-field schema is finalized.
#       The old 8-field extractor can be kept temporarily for frontend backwards compat.


async def extract_discovery_fields(
    conversation_text: str,
    session_id: str | None = None,
    solution_type: str | None = None,
) -> dict:
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
        return _empty_discovery_result()

    logger.debug("Extracting discovery fields from conversation transcript")
    tracer = trace.get_tracer("rs-generator")
    try:
        # Use .replace() not .format() — user transcript may contain literal braces
        # that would cause a KeyError if str.format() tried to interpret them.
        prompt = _build_discovery_prompt(conversation_text, solution_type)
        logger.info(f"Model call started: model={MODEL_DISCOVERY} caller=extract_discovery_fields")
        _t0 = time.perf_counter()
        with tracer.start_as_current_span("call_llm", kind=SpanKind.CLIENT) as span:
            span.set_attribute("gen_ai.operation.name", "generate_content")
            span.set_attribute("gen_ai.system", "gemini")
            span.set_attribute("gen_ai.request.model", MODEL_DISCOVERY)
            span.set_attribute("phase", "discovery_extract")
            response = await asyncio.to_thread(
                _genai_client.models.generate_content,
                model=MODEL_DISCOVERY,
                contents=prompt,
            )
            elapsed = time.perf_counter() - _t0
            _record_discovery_usage(getattr(response, "usage_metadata", None), session_id, span)
            record_operation_duration(
                elapsed,
                model=MODEL_DISCOVERY,
                operation="generate_content",
                status="ok",
            )
        logger.info(f"Model call completed: model={MODEL_DISCOVERY} elapsed={elapsed:.2f}s")
        result = _normalize_discovery_result(json.loads(_strip_markdown_json_fence(response.text or "")))
        logger.info(
            "Discovery extraction done: "
            f"completeness={result['completeness']}% "
            f"missing_priority={result['missing_priority']}"
        )
        return result

    except CostCircuitBreakerTripped:
        raise
    except Exception as exc:
        logger.warning(f"extract_discovery_fields failed: {exc}")
        return _empty_discovery_result()


NOT_APPLICABLE_FIELDS = {
    "cost_saving",
    "revenue_increase",
    "risk_avoidance",
    "comments",
    "attachments",
}


def sync_workflow_with_discovery_state(
    workflow_state: WorkflowState | None,
    discovery_state: dict | None,
    direct_fields: dict[str, str] | None = None,
    deferred_fields: dict | None = None,
) -> WorkflowState:
    """Mark workflow fields answered/deferred based on persisted form state."""
    state = workflow_state if isinstance(workflow_state, WorkflowState) else WorkflowState()
    statuses = state.field_status

    fields = (discovery_state or {}).get("fields") or {}
    for key, entry in fields.items():
        if key not in statuses or not isinstance(entry, dict):
            continue
        if entry.get("filled") and str(entry.get("value") or "").strip():
            statuses[key] = FieldStatus.ANSWERED

    for key, value in (direct_fields or {}).items():
        if key in statuses and str(value or "").strip():
            statuses[key] = FieldStatus.ANSWERED

    for key in deferred_fields or {}:
        if key in statuses and statuses[key] != FieldStatus.ANSWERED:
            statuses[key] = FieldStatus.DEFERRED

    return state


def is_not_applicable_allowed(field_key: str) -> bool:
    """Return whether a field can be treated as not applicable."""
    return field_key in NOT_APPLICABLE_FIELDS


def pick_next_active_field(
    workflow_state: WorkflowState | None,
    discovery_state: dict | None = None,
    direct_fields: dict[str, str] | None = None,
    deferred_fields: dict | None = None,
    *,
    include_optional: bool = True,
) -> str | None:
    """Pick the next missing field in deterministic schema order."""
    state = sync_workflow_with_discovery_state(
        workflow_state,
        discovery_state,
        direct_fields,
        deferred_fields,
    )
    statuses = state.field_status

    for key in REQUIRED_FIELDS:
        if statuses.get(key) in {FieldStatus.MISSING, FieldStatus.CLARIFICATION_REQUESTED}:
            return key

    if include_optional:
        for key in OPTIONAL_FIELDS:
            if statuses.get(key) in {FieldStatus.MISSING, FieldStatus.CLARIFICATION_REQUESTED}:
                return key

    return None
