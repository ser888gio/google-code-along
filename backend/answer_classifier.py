"""Active-field answer classification for the one-field discovery workflow."""

from __future__ import annotations

import asyncio
import json
import re
import time
import unicodedata
from typing import Literal, NotRequired, TypedDict, cast

from config import GOOGLE_API_KEY, MODEL_DISCOVERY
from direct_field_context import WRAP_UP_CHOICES
from field_schema import (
    DEFERRED_ANSWER_PATTERNS,
    DIRECT_FIELD_KEYS,
    DIRECT_FIELD_TERMS,
    FIELD_LABELS,
    FIELD_SCHEMA,
)
from logger import get_logger
from prompts.context import ACTIVE_FIELD_CLASSIFIER_PROMPT, WRAP_UP_DECISION_PROMPT
from solution_configs import get_field_rubric_block
from utils import format_prompt_data_lines

logger = get_logger(__name__)

Classification = Literal[
    "answered",
    "deferred",
    "clarification_requested",
    "not_answered",
]

WrapUpDecision = Literal["finalize", "fill_in", "unclear"]


class ClassifierResult(TypedDict):
    classification: Classification
    value: str | None
    confidence: float
    proactive_fields: dict[str, dict]
    coverage_gaps: list[str]
    finish_requested: NotRequired[bool]


def normalize_for_match(value: str) -> str:
    """Lowercase, remove diacritics, and compact whitespace for matching."""
    normalized = unicodedata.normalize("NFD", value.lower())
    normalized = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", normalized).strip()


_WRAP_UP_CHOICE_DECISIONS: dict[str, WrapUpDecision] = {
    normalize_for_match(text): decision
    for by_language in WRAP_UP_CHOICES.values()
    for pair in by_language.values()
    for text, decision in zip(pair, ("finalize", "fill_in"), strict=True)
}


def is_deferred_answer(text: str) -> bool:
    """Return whether text means the user chose to defer the field."""
    normalized = normalize_for_match(text)
    return any(re.search(pattern, normalized) for pattern in DEFERRED_ANSWER_PATTERNS)


def clean_direct_answer_value(text: str) -> str:
    """Clean short direct-field replies before storing them."""
    return (
        re.sub(
            r"^(je to|it's|it is|jmenuje se|bude to)\s+",
            "",
            text.strip(),
            flags=re.IGNORECASE,
        )
        .rstrip(".")
        .strip()
    )


def is_plausible_direct_answer(text: str) -> bool:
    """Mirror the frontend direct-field heuristic."""
    value = clean_direct_answer_value(text)
    return bool(value) and len(value) <= 80 and "\n" not in value and "?" not in value


def mentions_other_direct_field(active_field: str, text: str) -> bool:
    """Return whether a reply appears to include another direct field by name."""
    normalized = normalize_for_match(text)
    for field_key, terms in DIRECT_FIELD_TERMS.items():
        if field_key == active_field:
            continue
        if any(term in normalized for term in terms):
            return True
    return False


def _empty_result(classification: Classification = "not_answered") -> ClassifierResult:
    return {
        "classification": classification,
        "value": None,
        "confidence": 0.0,
        "proactive_fields": {},
        "coverage_gaps": [],
    }


async def classify_user_turn(
    active_field: str | None,
    message: str,
    conversation_tail: str = "",
    solution_type: str | None = None,
) -> ClassifierResult:
    """Classify the latest user reply against the active field.

    Short direct-field answers take a deterministic fast path. Everything else
    goes to a small structured Gemini Flash call, so deferrals, clarification
    questions and requests to finish early are judged in any phrasing.
    """
    text = message.strip()
    if not text or not active_field or active_field not in FIELD_SCHEMA:
        return _empty_result()

    if (
        active_field in DIRECT_FIELD_KEYS
        and is_plausible_direct_answer(text)
        and not mentions_other_direct_field(active_field, text)
    ):
        return {
            "classification": "answered",
            "value": clean_direct_answer_value(text),
            "confidence": 0.9,
            "proactive_fields": {},
            "coverage_gaps": [],
        }

    return await _classify_with_llm(active_field, text, conversation_tail, solution_type)


async def _generate_json(prompt: str, caller: str) -> dict:
    """Run one Gemini Flash call and parse its JSON answer (optionally fenced)."""
    from google import genai

    client = genai.Client(api_key=GOOGLE_API_KEY)
    logger.info(f"Model call started: model={MODEL_DISCOVERY} caller={caller}")
    start = time.perf_counter()
    response = await asyncio.to_thread(
        client.models.generate_content,
        model=MODEL_DISCOVERY,
        contents=prompt,
    )
    logger.info(f"Model call completed: model={MODEL_DISCOVERY} elapsed={time.perf_counter() - start:.2f}s")
    raw = (response.text or "").strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


async def classify_wrap_up_reply(message: str, conversation_tail: str = "") -> WrapUpDecision | None:
    """Decide whether a wrap-up reply means finalize now, fill in details first, or neither.

    Returns None when the model is unavailable, so the caller can fall back.
    """
    text = message.strip()
    if not text:
        return "unclear"
    if decision := _WRAP_UP_CHOICE_DECISIONS.get(normalize_for_match(text)):
        return decision

    try:
        prompt = WRAP_UP_DECISION_PROMPT.replace(
            "{conversation_tail}", format_prompt_data_lines(conversation_tail)
        ).replace("{user_message}", format_prompt_data_lines(text, default_label="Latest user line"))
        parsed = await _generate_json(prompt, "classify_wrap_up_reply")
    except Exception as exc:
        logger.warning(f"classify_wrap_up_reply failed: {exc}")
        return None

    decision = parsed.get("decision")
    if decision not in {"finalize", "fill_in", "unclear"}:
        return "unclear"
    return cast(WrapUpDecision, decision)


async def _classify_with_llm(
    active_field: str,
    message: str,
    conversation_tail: str,
    solution_type: str | None = None,
) -> ClassifierResult:
    """Use Gemini Flash for ambiguous classification and proactive extraction."""
    try:
        rubric_block = get_field_rubric_block(active_field, solution_type) or "(no rubric defined)"
        prompt = (
            ACTIVE_FIELD_CLASSIFIER_PROMPT.replace("{active_field}", active_field)
            .replace("{active_field_label}", FIELD_LABELS.get(active_field, active_field))
            .replace("{active_field_rubric}", rubric_block)
            .replace("{field_labels_json}", json.dumps(FIELD_LABELS, ensure_ascii=False))
            .replace(
                "{conversation_tail}",
                format_prompt_data_lines(conversation_tail),
            )
            .replace(
                "{user_message}",
                format_prompt_data_lines(message, default_label="Latest user line"),
            )
        )
        parsed = await _generate_json(prompt, "classify_user_turn")
    except Exception as exc:
        logger.warning(f"classify_user_turn fallback failed: {exc}")
        return _empty_result()

    active = parsed.get("active_field_result") or {}
    classification = active.get("classification")
    if classification not in {
        "answered",
        "deferred",
        "clarification_requested",
        "not_answered",
    }:
        classification = "not_answered"

    proactive: dict[str, dict] = {}
    for key, entry in (parsed.get("proactive_fields") or {}).items():
        if key not in FIELD_SCHEMA or not isinstance(entry, dict):
            continue
        if entry.get("filled") and str(entry.get("value") or "").strip():
            proactive[key] = {
                "filled": True,
                "value": str(entry["value"]).strip(),
                "confidence": float(entry.get("confidence") or 0.0),
            }

    value = active.get("value")
    raw_gaps = active.get("coverage_gaps") or []
    coverage_gaps: list[str] = [str(gap).strip() for gap in raw_gaps if isinstance(gap, str) and str(gap).strip()]
    return {
        "classification": cast(Classification, classification),
        "value": str(value).strip() if value is not None and str(value).strip() else None,
        "confidence": float(active.get("confidence") or 0.0),
        "proactive_fields": proactive,
        "coverage_gaps": coverage_gaps,
        "finish_requested": parsed.get("finish_requested") is True,
    }
