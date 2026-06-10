"""Apply answer-classifier results to discovery and workflow state.

This module owns the persistence side effects of classifying a user turn:
marking fields answered/deferred/missing, recomputing completeness, and
mirroring direct-input fields. It touches Firestore and WorkflowState only —
never the ADK runner or the HTTP layer.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from answer_classifier import (
    DIRECT_FIELD_KEYS,
    ClassifierResult,
    classify_user_turn,
    is_deferred_answer,
)
from answer_quality import rate_answer
from field_schema import FIELD_SCHEMA, REQUIRED_FIELDS
from firestore import (
    remove_deferred_fields,
    upsert_deferred_fields,
    upsert_direct_fields,
    upsert_discovery_state,
)
from workflow_state import FieldStatus, WorkflowState


def field_entry(value: str) -> dict:
    return {"filled": True, "value": value}


def solution_type_value(discovery_state: dict | None) -> str | None:
    if not discovery_state:
        return None
    fields = discovery_state.get("fields")
    if not isinstance(fields, dict):
        return None
    entry = fields.get("solution_type")
    if not isinstance(entry, dict):
        return None
    return entry.get("value")


def recompute_discovery_completeness(state: dict) -> None:
    fields = state.setdefault("fields", {})
    filled = sum(1 for key in REQUIRED_FIELDS if isinstance(fields.get(key), dict) and fields[key].get("filled"))
    state["completeness"] = round((filled / len(REQUIRED_FIELDS)) * 100)


def empty_discovery_state() -> dict:
    return {"completeness": 0, "fields": {}, "missing_priority": []}


async def _apply_answered(
    *,
    loop: asyncio.AbstractEventLoop,
    session_id: str,
    field_key: str,
    value: str,
    statuses: dict,
    miss_counts: dict,
    discovery_state: dict | None,
    direct_fields: dict[str, str],
    deferred_fields: dict,
) -> dict | None:
    statuses[field_key] = "answered"
    miss_counts[field_key] = 0
    if discovery_state is None:
        discovery_state = empty_discovery_state()
    discovery_state.setdefault("fields", {})[field_key] = field_entry(value)
    recompute_discovery_completeness(discovery_state)
    await loop.run_in_executor(None, upsert_discovery_state, session_id, discovery_state)
    if field_key in DIRECT_FIELD_KEYS:
        direct_fields[field_key] = value
        await loop.run_in_executor(None, upsert_direct_fields, session_id, {field_key: value})
    if field_key in deferred_fields:
        deferred_fields.pop(field_key, None)
        await loop.run_in_executor(None, remove_deferred_fields, session_id, [field_key])
    return discovery_state


async def _apply_deferred(
    *,
    loop: asyncio.AbstractEventLoop,
    session_id: str,
    field_key: str,
    statuses: dict,
    miss_counts: dict,
    deferred_fields: dict,
) -> None:
    statuses[field_key] = "deferred"
    miss_counts[field_key] = 0
    deferred_fields[field_key] = {"deferred_at": datetime.now(timezone.utc).isoformat()}
    await loop.run_in_executor(None, upsert_deferred_fields, session_id, {field_key: deferred_fields[field_key]})


async def _apply_classification_result(
    *,
    loop: asyncio.AbstractEventLoop,
    session_id: str,
    field_key: str,
    message: str,
    classification: ClassifierResult,
    statuses: dict,
    miss_counts: dict,
    clarification_counts: dict,
    discovery_state: dict | None,
    direct_fields: dict[str, str],
    deferred_fields: dict,
) -> dict | None:
    clf = classification["classification"]
    if clf == "answered":
        value = classification.get("value")
        if value:
            discovery_state = await _apply_answered(
                loop=loop,
                session_id=session_id,
                field_key=field_key,
                value=value,
                statuses=statuses,
                miss_counts=miss_counts,
                discovery_state=discovery_state,
                direct_fields=direct_fields,
                deferred_fields=deferred_fields,
            )
        else:
            statuses[field_key] = "missing"
    elif clf == "deferred":
        await _apply_deferred(
            loop=loop,
            session_id=session_id,
            field_key=field_key,
            statuses=statuses,
            miss_counts=miss_counts,
            deferred_fields=deferred_fields,
        )
    elif clf == "clarification_requested":
        statuses[field_key] = "clarification_requested"
        clarification_counts[field_key] = int(clarification_counts.get(field_key) or 0) + 1
    elif is_deferred_answer(message):
        await _apply_deferred(
            loop=loop,
            session_id=session_id,
            field_key=field_key,
            statuses=statuses,
            miss_counts=miss_counts,
            deferred_fields=deferred_fields,
        )
    else:
        statuses[field_key] = "missing"
        miss_counts[field_key] = int(miss_counts.get(field_key) or 0) + 1
    return discovery_state


async def classify_and_update_active_field(
    *,
    session_id: str,
    field_key: str,
    message: str,
    tail_text: str,
    solution_type: str | None,
    state: WorkflowState,
    discovery_state: dict | None,
    direct_fields: dict[str, str],
    deferred_fields: dict,
) -> tuple[ClassifierResult, dict | None]:
    """Run the classifier for the active field and persist the resulting status changes."""
    loop = asyncio.get_running_loop()

    classification: ClassifierResult = await classify_user_turn(
        field_key, message, tail_text, solution_type=solution_type
    )
    await rate_answer(
        field_key,
        str((state.last_question_by_field or {}).get(field_key, "")),
        message,
        classification["classification"],
    )

    latest_gaps = list(classification.get("coverage_gaps") or [])
    if latest_gaps:
        state.coverage_gaps[field_key] = latest_gaps
    else:
        state.coverage_gaps.pop(field_key, None)

    discovery_state = await _apply_classification_result(
        loop=loop,
        session_id=session_id,
        field_key=field_key,
        message=message,
        classification=classification,
        statuses=state.field_status,
        miss_counts=state.miss_counts,
        clarification_counts=state.clarification_counts,
        discovery_state=discovery_state,
        direct_fields=direct_fields,
        deferred_fields=deferred_fields,
    )

    return classification, discovery_state


async def apply_proactive_updates(
    *,
    session_id: str,
    classification: ClassifierResult,
    active_field: str,
    state: WorkflowState,
    discovery_state: dict | None,
) -> dict | None:
    """Persist any side-channel field values the classifier extracted proactively."""
    loop = asyncio.get_running_loop()

    proactive_updates: dict[str, str] = {}
    for key, entry in (classification.get("proactive_fields") or {}).items():
        if key not in FIELD_SCHEMA or key == active_field:
            continue
        value = str(entry.get("value") or "").strip()
        if value:
            state.field_status[key] = FieldStatus.ANSWERED
            proactive_updates[key] = value

    if not proactive_updates:
        return discovery_state

    if discovery_state is None:
        discovery_state = empty_discovery_state()
    fields = discovery_state.setdefault("fields", {})
    for key, value in proactive_updates.items():
        fields[key] = field_entry(value)
    recompute_discovery_completeness(discovery_state)
    await loop.run_in_executor(None, upsert_discovery_state, session_id, discovery_state)
    return discovery_state
