"""Active-field answer classification for the one-field discovery workflow."""

from __future__ import annotations

import asyncio
import json
import re
import time
import unicodedata
from typing import Literal, TypedDict

from agent.discovery_agent import FIELD_LABELS, FIELD_SCHEMA
from config import GOOGLE_API_KEY, MODEL_DISCOVERY
from logger import get_logger
from prompts.context import ACTIVE_FIELD_CLASSIFIER_PROMPT

logger = get_logger(__name__)

Classification = Literal[
    "answered",
    "deferred",
    "clarification_requested",
    "not_answered",
]


class ClassifierResult(TypedDict):
    classification: Classification
    value: str | None
    confidence: float
    proactive_fields: dict[str, dict]


DIRECT_FIELD_KEYS = {
    "use_case_title",
    "department",
    "requestor",
    "product_owner",
    "saved_time_hours_per_year",
    "cost_saving",
    "revenue_increase",
    "comments",
    "attachments",
}

_DIRECT_FIELD_TERMS = {
    "use_case_title": ["use case title", "nazev", "title"],
    "department": ["department", "oddeleni", "utvar", "business unit"],
    "requestor": ["requestor", "zadatel", "zadavatel"],
    "product_owner": [
        "product owner",
        "produktovy vlastnik",
        "vlastnik produktu",
        "owner",
    ],
    "saved_time_hours_per_year": ["saved time", "uspora casu", "hours"],
    "cost_saving": ["cost saving", "naklady", "uspora nakladu"],
    "revenue_increase": ["revenue", "vynos", "trzby"],
    "comments": ["comment", "poznamka"],
    "attachments": ["attachment", "priloha"],
}

_DEFERRED_PATTERNS = [
    r"\bnevim\b",
    r"\bnetusim\b",
    r"\bneznam\b",
    r"\bzjistim\b.*\bpozdeji\b",
    r"\bdoplnim(?:e)?\b.*\bpozdeji\b",
    r"\bpreskocit\b",
    r"\bted\b.*\bnevim\b",
    r"\bzatim\b.*\bneni\b.*\bjasne\b",
    r"\bto\b.*\bzatim\b.*\bjedno\b",
    r"\bnemame\b.*\burceno\b",
    r"\bunknown\b",
    r"\bdon'?t\s+know\b",
    r"\bnot\s+sure\b",
    r"\btbd\b",
    r"\bn/a\b",
]


def normalize_for_match(value: str) -> str:
    """Lowercase, remove diacritics, and compact whitespace for matching."""
    normalized = unicodedata.normalize("NFD", value.lower())
    normalized = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", normalized).strip()


def is_deferred_answer(text: str) -> bool:
    """Return whether text means the user chose to defer the field."""
    normalized = normalize_for_match(text)
    return any(re.search(pattern, normalized) for pattern in _DEFERRED_PATTERNS)


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
    for field_key, terms in _DIRECT_FIELD_TERMS.items():
        if field_key == active_field:
            continue
        if any(term in normalized for term in terms):
            return True
    return False


def is_short_clarification_question(text: str) -> bool:
    """Fast path for common clarification questions."""
    value = text.strip()
    if not value.endswith("?") or len(value) > 180:
        return False
    normalized = normalize_for_match(value)
    fieldish_terms = [
        "hr",
        "sap",
        "excel",
        "sharepoint",
        "power",
        "department",
        "oddeleni",
        "requestor",
        "owner",
    ]
    return not any(term in normalized for term in fieldish_terms)


def _empty_result(classification: Classification = "not_answered") -> ClassifierResult:
    return {
        "classification": classification,
        "value": None,
        "confidence": 0.0,
        "proactive_fields": {},
    }


async def classify_user_turn(
    active_field: str | None,
    message: str,
    conversation_tail: str = "",
) -> ClassifierResult:
    """Classify the latest user reply against the active field.

    Deterministic fast paths avoid latency for obvious deferrals and direct-field
    answers. Ambiguous replies fall back to a small structured Gemini Flash call.
    """
    text = message.strip()
    if not text or not active_field or active_field not in FIELD_SCHEMA:
        return _empty_result()

    if is_deferred_answer(text):
        return {
            "classification": "deferred",
            "value": None,
            "confidence": 1.0,
            "proactive_fields": {},
        }

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
        }

    if is_short_clarification_question(text):
        return {
            "classification": "clarification_requested",
            "value": None,
            "confidence": 0.85,
            "proactive_fields": {},
        }

    return await _classify_with_llm(active_field, text, conversation_tail)


async def _classify_with_llm(
    active_field: str,
    message: str,
    conversation_tail: str,
) -> ClassifierResult:
    """Use Gemini Flash for ambiguous classification and proactive extraction."""
    try:
        from google import genai

        client = genai.Client(api_key=GOOGLE_API_KEY)
        prompt = (
            ACTIVE_FIELD_CLASSIFIER_PROMPT.replace("{active_field}", active_field)
            .replace(
                "{active_field_label}", FIELD_LABELS.get(active_field, active_field)
            )
            .replace(
                "{field_labels_json}", json.dumps(FIELD_LABELS, ensure_ascii=False)
            )
            .replace("{conversation_tail}", conversation_tail)
            .replace("{user_message}", message)
        )
        logger.info(
            f"Model call started: model={MODEL_DISCOVERY} caller=classify_user_turn"
        )
        start = time.perf_counter()
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=MODEL_DISCOVERY,
            contents=prompt,
        )
        logger.info(
            f"Model call completed: model={MODEL_DISCOVERY} elapsed={time.perf_counter() - start:.2f}s"
        )
        raw = (response.text or "").strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw.strip())
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
    return {
        "classification": classification,
        "value": str(value).strip()
        if value is not None and str(value).strip()
        else None,
        "confidence": float(active.get("confidence") or 0.0),
        "proactive_fields": proactive,
    }
