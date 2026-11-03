"""Production implementations of the machine services (Gemini, deterministic validation, directory, Firestore)."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Mapping, Sequence
from functools import cache
from pathlib import Path
from typing import Any

from answer_classifier import normalize_for_match
from config import (
    GOOGLE_API_KEY,
    MODEL_INTENT_CLASSIFIER,
    MODEL_SECTION_GENERATOR,
    SECTION_DIRECTORY_PATH,
    SECTION_GENERATION_TIMEOUT_S,
)
from field_schema import FIELD_SCHEMA
from firestore.writer import _client
from logger import get_logger
from observability.cost import compute_cost
from observability.metrics import record_cost, record_tokens
from observability.safety import add_session_cost, assert_session_within_budget
from privacy import hash_text
from prompts.section_agent import (
    DEPENDENT_REVIEW_PROMPT,
    INTENT_CLASSIFIER_PROMPT,
    MODE_GUIDE,
    MODE_NORMAL,
    SECTION_GENERATOR_PROMPT,
)
from utils import format_prompt_data_lines

from spec_machine.intents import ModelClassifier
from spec_machine.model import (
    DontKnow,
    ExportRequest,
    GenerateOutput,
    GenerateRequest,
    MachineServices,
    MarkTbd,
    ProposalOutput,
    QuestionOutput,
    ReviewRequest,
    SectionConfig,
    SectionEvent,
    SectionValidationError,
    Skip,
    Submit,
)
from spec_machine.store import FirestoreSectionStore

logger = get_logger(__name__)

_MAX_SHORT_LEN = 120
_MAX_TEXT_LEN = 4000
_DIGIT_RE = re.compile(r"\d")


# --- directory (deterministic "I don't know" lookup for simple fields) ---


@cache
def _load_directory(path: str) -> dict[str, list[str]]:
    if not path:
        return {}
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(f"Section directory could not be loaded: error={type(exc).__name__}")
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        str(key): [str(item).strip() for item in values if str(item).strip()]
        for key, values in raw.items()
        if isinstance(values, list)
    }


def directory_entries(config: SectionConfig, directory: Mapping[str, Sequence[str]]) -> list[str]:
    """Entries keyed by field id win over entries keyed by input format (e.g. "name")."""
    return list(directory.get(config.id) or directory.get(config.input_format) or [])


def search_directory(entries: Sequence[str], query: str | None, limit: int = 5) -> list[str]:
    if not query or not query.strip():
        return list(entries[:limit])
    needle = normalize_for_match(query)
    tokens = needle.split()
    scored: list[tuple[int, int, str]] = []
    for index, entry in enumerate(entries):
        haystack = normalize_for_match(entry)
        score = 100 if needle in haystack else sum(1 for token in tokens if token in haystack)
        if score:
            scored.append((-score, index, entry))
    return [entry for _, _, entry in sorted(scored)[:limit]]


# --- validation (deterministic; never calls the LLM) ---


def validate_value(config: SectionConfig, candidate: str, directory: Mapping[str, Sequence[str]]) -> str:
    value = candidate.strip()
    if not value:
        raise SectionValidationError("Please enter a value.")
    if config.kind == "ai" or config.input_format == "text":
        if len(value) > _MAX_TEXT_LEN:
            raise SectionValidationError("This is too long. Please shorten it.")
        return value
    if config.input_format == "number":
        if not _DIGIT_RE.search(value) or len(value) > _MAX_SHORT_LEN:
            raise SectionValidationError("Please give a number. An approximate figure is fine.")
        return value
    value = value.rstrip(".").strip()
    if len(value) > _MAX_SHORT_LEN or "\n" in value or "?" in value:
        raise SectionValidationError("Please give just the name or code.")
    normalized = normalize_for_match(value)
    for entry in directory_entries(config, directory):
        if normalize_for_match(entry) == normalized:
            return entry
    return value


# --- Gemini ---


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    parsed = json.loads(text.strip())
    if not isinstance(parsed, dict):
        raise ValueError("model reply is not a JSON object")
    return parsed


def parse_generate_output(parsed: Mapping[str, Any]) -> GenerateOutput:
    kind = parsed.get("type")
    if kind == "proposal" and str(parsed.get("proposal") or "").strip():
        rationale = str(parsed.get("rationale") or "").strip() or None
        return ProposalOutput(str(parsed["proposal"]).strip(), rationale)
    if kind == "question" and str(parsed.get("message") or "").strip():
        return QuestionOutput(str(parsed["message"]).strip())
    raise ValueError(f"unexpected generator output type: {kind!r}")


def _values_block(values: Mapping[str, str]) -> str:
    if not values:
        return "(none)"
    lines = [f"{FIELD_SCHEMA[key]['label'] if key in FIELD_SCHEMA else key}: {value}" for key, value in values.items()]
    return format_prompt_data_lines("\n".join(lines), default_label="Confirmed")


def _field_meta(config: SectionConfig) -> tuple[str, str, str]:
    field_def = FIELD_SCHEMA.get(config.id)
    if field_def is None:
        return "(not specified)", "(none)", "(none)"
    rubric = "\n".join(f"- {item}" for item in field_def.get("rubric", [])) or "(none)"
    return field_def.get("expected_shape", "(not specified)"), rubric, field_def.get("example_good", "(none)")


def build_generate_prompt(request: GenerateRequest) -> str:
    expected_shape, rubric, example_good = _field_meta(request.config)
    feedback = "\n".join(f"- {item}" for item in request.feedback) or "(none)"
    replacements = {
        "{field_label}": request.config.label or request.config.id,
        "{expected_shape}": expected_shape,
        "{rubric}": rubric,
        "{example_good}": example_good,
        "{mode_instruction}": MODE_GUIDE if request.mode == "guide" else MODE_NORMAL,
        "{current_value}": request.value or "(empty)",
        "{previous_proposal}": request.proposal or request.draft or "(empty)",
        "{feedback}": format_prompt_data_lines(feedback, default_label="Reason") if request.feedback else feedback,
        "{other_values}": _values_block(request.other_values),
        "{user_input}": (
            format_prompt_data_lines(request.user_input, default_label="User") if request.user_input else "(none)"
        ),
    }
    prompt = SECTION_GENERATOR_PROMPT
    for placeholder, value in replacements.items():
        prompt = prompt.replace(placeholder, value)
    return prompt


def _record_usage(usage: Any, session_id: str, feature: str, model: str) -> None:
    if not usage:
        return
    input_tokens = getattr(usage, "prompt_token_count", 0) or 0
    output_tokens = getattr(usage, "candidates_token_count", 0) or 0
    record_tokens(input_tokens, model=model, token_type="input", feature=feature)
    record_tokens(output_tokens, model=model, token_type="output", feature=feature)
    cost_usd = compute_cost(model, usage)
    record_cost(cost_usd, model=model, feature=feature, session_id_hash=hash_text(session_id)[:16])
    add_session_cost(session_id, cost_usd)


async def _call_gemini_json(
    prompt: str, *, session_id: str, feature: str, model: str = MODEL_SECTION_GENERATOR
) -> dict[str, Any]:
    from google import genai
    from google.genai import types

    assert_session_within_budget(session_id)
    client = genai.Client(api_key=GOOGLE_API_KEY)
    # Cancelling the awaiting task (the machine does this when `generating` is exited) aborts the HTTP call.
    response = await client.aio.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    _record_usage(response.usage_metadata, session_id, feature, model)
    return _parse_json_object(response.text or "")


_CONFIDENT = 0.8


def intent_classifier(session_id: str) -> ModelClassifier:
    """Small-model fallback for ambiguous simple-field replies. Low confidence -> read-back confirmation."""

    async def classify(text: str, config: SectionConfig) -> SectionEvent | None:
        expected_shape, _, _ = _field_meta(config)
        prompt = (
            INTENT_CLASSIFIER_PROMPT.replace("{field_label}", config.label or config.id)
            .replace("{expected_shape}", expected_shape)
            .replace("{user_message}", format_prompt_data_lines(text, default_label="User"))
        )
        try:
            parsed = await _call_gemini_json(
                prompt, session_id=session_id, feature="section_intent", model=MODEL_INTENT_CLASSIFIER
            )
        except Exception as exc:  # noqa: BLE001 — fall back to the keyword result
            logger.warning(f"Section intent classifier failed: error={type(exc).__name__}")
            return None
        intent = parsed.get("intent")
        value = str(parsed.get("value") or "").strip()
        owner = str(parsed.get("owner") or "").strip()
        try:
            confidence = float(parsed.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        if intent == "submit" and value:
            return Submit(value, low_confidence=confidence < _CONFIDENT)
        if intent == "dont_know":
            return DontKnow()
        if intent == "skip":
            return Skip()
        if intent == "tbd":
            return MarkTbd(owner=owner or None, note=text)
        return None

    return classify


# --- wiring ---


def build_services(session_id: str) -> MachineServices:
    store = FirestoreSectionStore(_client(), session_id)

    async def generate(request: GenerateRequest, abort: asyncio.Event) -> GenerateOutput:
        if abort.is_set():
            raise asyncio.CancelledError
        parsed = await _call_gemini_json(
            build_generate_prompt(request), session_id=session_id, feature="section_generate"
        )
        return parse_generate_output(parsed)

    async def validate(config: SectionConfig, candidate: str) -> str:
        return validate_value(config, candidate, _load_directory(SECTION_DIRECTORY_PATH))

    async def lookup(config: SectionConfig, query: str | None) -> list[str]:
        return search_directory(directory_entries(config, _load_directory(SECTION_DIRECTORY_PATH)), query)

    async def review_dependent(request: ReviewRequest) -> ProposalOutput | None:
        expected_shape, _, _ = _field_meta(request.dependent)
        changed = FIELD_SCHEMA.get(request.changed_section_id)
        prompt = (
            DEPENDENT_REVIEW_PROMPT.replace(
                "{changed_label}", changed["label"] if changed else request.changed_section_id
            )
            .replace("{field_label}", request.dependent.label or request.dependent.id)
            .replace("{expected_shape}", expected_shape)
            .replace("{tbd_note}", (request.dependent_tbd or {}).get("note", "(none)"))
            .replace("{other_values}", _values_block(request.other_values))
        )
        parsed = await _call_gemini_json(prompt, session_id=session_id, feature="section_review_dependent")
        proposal = str(parsed.get("proposal") or "").strip()
        if parsed.get("answerable") is not True or not proposal:
            return None
        return ProposalOutput(proposal, str(parsed.get("rationale") or "").strip() or None)

    async def export_spec(request: ExportRequest) -> None:
        payload = {
            "values": dict(request.values),
            "open_items": [
                {"field": item.section_id, "label": item.label, **(item.tbd or {})} for item in request.open_items
            ],
        }
        await asyncio.to_thread(store.save_export, payload)

    return MachineServices(
        generate=generate,
        validate=validate,
        lookup=lookup,
        persist=lambda request: asyncio.to_thread(store.commit, request),
        persist_meta=lambda request: asyncio.to_thread(store.save_meta, request),
        record_event=lambda record: asyncio.to_thread(store.record_event, record),
        load_document=lambda: asyncio.to_thread(store.load_document),
        load_section=lambda section_id: asyncio.to_thread(store.load_section, section_id),
        save_cursor=lambda cursor: asyncio.to_thread(store.save_cursor, cursor),
        review_dependent=review_dependent,
        export_spec=export_spec,
        generation_timeout_s=SECTION_GENERATION_TIMEOUT_S,
    )
