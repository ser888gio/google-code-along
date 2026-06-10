"""Backend-owned workflow turn engine for the RS consultant chat.

Owns everything that happens around a single conversation turn, independent
of transport (REST, SSE, or voice WebSocket):

  - ``prepare_workflow_turn``  — classify the user's answer, advance the FSM,
    and build the hidden workflow context before the LLM turn starts
  - ``run_turn_postprocessing`` — persist the turn and launch the finalizer
    pipeline when [FINALIZING] is detected
  - ``build_workflow_context_snapshot`` / ``load_voice_priming`` — pure reads
    used to prime a voice session at connect time
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from functools import partial

import runtime
from agent.discovery_agent import (
    extract_discovery_fields,
    is_not_applicable_allowed,
    pick_next_active_field,
    sync_workflow_with_discovery_state,
)
from agent.finalizer_agent import run_finalizer
from answer_classifier import ClassifierResult, normalize_for_match
from chat_classification import (
    apply_proactive_updates,
    classify_and_update_active_field,
    solution_type_value,
)
from config import APP_NAME
from direct_field_context import build_augmented_user_message, clean_direct_fields
from field_schema import FIELD_LABELS, FIELD_SCHEMA
from firestore import (
    append_conversation_turn,
    get_deferred_fields,
    get_direct_fields,
    get_discovery_state,
    get_workflow_state,
    remove_deferred_fields,
    set_finalization_error,
    set_finalization_pending,
    upsert_deferred_fields,
    upsert_discovery_state,
    upsert_workflow_state,
)
from logger import get_logger
from observability.safety import CostCircuitBreakerTripped
from utils import extract_conversation_text
from workflow_state import AgentContext, FieldStatus, Phase, WorkflowEvent, WorkflowState

logger = get_logger(__name__)


def _conversation_event_line(event) -> str | None:
    if not event.content or not event.content.parts:
        return None

    text = "".join(p.text for p in event.content.parts if p.text).strip()
    if not text:
        return None

    label = "User" if event.content.role == "user" else "Consultant"
    return f"{label}: {text}"


def _build_conversation_tail(session, latest_user_message: str, limit: int = 12) -> str:
    """Build a compact transcript tail for classifiers/extractors."""
    events = getattr(session, "events", None) if session else None
    tail_lines = [line for event in (events or [])[-limit:] if (line := _conversation_event_line(event))]
    tail_lines.append(f"User: {latest_user_message}")
    return "\n".join(tail_lines)


def _answered_field_values(
    discovery_state: dict | None,
    direct_fields: dict[str, str],
) -> dict[str, str]:
    """Return answered field values for hidden workflow context."""
    values: dict[str, str] = {}
    for key, entry in ((discovery_state or {}).get("fields") or {}).items():
        if isinstance(entry, dict) and entry.get("filled") and entry.get("value"):
            values[key] = str(entry["value"])
    for key, value in direct_fields.items():
        if str(value or "").strip():
            values[key] = str(value).strip()
    return values


def _is_finalize_choice(message: str) -> bool:
    """Detect a wrap-up user choice to finalize with open questions."""
    text = normalize_for_match(message)
    return any(
        phrase in text
        for phrase in [
            "finalize",
            "finalise",
            "generate",
            "vygeneruj",
            "finalizuj",
            "dokoncit",
            "nechat",
            "pozdeji",
        ]
    )


async def _reopen_first_deferred_field(
    *,
    session_id: str,
    state: WorkflowState,
    deferred_fields: dict,
) -> None:
    """Move wrap-up back to discovery for the first deferred field."""
    if not deferred_fields:
        return

    field_key = next(iter(deferred_fields))
    deferred_fields.pop(field_key, None)
    state.transition(WorkflowEvent.REOPEN_DEFERRED, active_field=field_key)

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, remove_deferred_fields, session_id, [field_key])


async def prepare_workflow_turn(
    *,
    session_id: str,
    message: str,
    incoming_deferred: list[str] | None,
    session,
    direct_fields: dict[str, str],
) -> dict:
    """Advance backend-owned workflow state before the LLM turn starts."""
    loop = asyncio.get_running_loop()

    discovery_state = await loop.run_in_executor(None, get_discovery_state, session_id)
    deferred_fields = await loop.run_in_executor(None, get_deferred_fields, session_id)
    stored_workflow = await loop.run_in_executor(None, get_workflow_state, session_id)
    state = WorkflowState.from_dict(stored_workflow)
    state = sync_workflow_with_discovery_state(state, discovery_state, direct_fields, deferred_fields)

    new_deferred = {
        key: {"deferred_at": datetime.now(timezone.utc).isoformat()}
        for key in (incoming_deferred or [])
        if key in FIELD_SCHEMA
    }
    if new_deferred:
        deferred_fields.update(new_deferred)
        await loop.run_in_executor(None, upsert_deferred_fields, session_id, new_deferred)

    previous_active = state.active_field
    classification: ClassifierResult = {
        "classification": "not_answered",
        "value": None,
        "confidence": 0.0,
        "proactive_fields": {},
        "coverage_gaps": [],
    }

    solution_type = solution_type_value(discovery_state)

    tail_text = _build_conversation_tail(session, message)
    if state.phase == Phase.WRAP_UP:
        if _is_finalize_choice(message):
            state.transition(WorkflowEvent.FINALIZE_CHOSEN)
        else:
            await _reopen_first_deferred_field(
                session_id=session_id,
                state=state,
                deferred_fields=deferred_fields,
            )
    elif previous_active:
        classification, discovery_state = await classify_and_update_active_field(
            session_id=session_id,
            field_key=previous_active,
            message=message,
            tail_text=tail_text,
            solution_type=solution_type,
            state=state,
            discovery_state=discovery_state,
            direct_fields=direct_fields,
            deferred_fields=deferred_fields,
        )
        discovery_state = await apply_proactive_updates(
            session_id=session_id,
            classification=classification,
            active_field=previous_active,
            state=state,
            discovery_state=discovery_state,
        )

    if state.phase != Phase.READY_TO_FINALIZE:
        next_field = pick_next_active_field(state, discovery_state, direct_fields, deferred_fields)
        if next_field is None:
            state.transition(WorkflowEvent.FIELDS_EXHAUSTED)
        else:
            state.transition(WorkflowEvent.FIELD_FOUND, active_field=next_field)

    # Treat disallowed not-applicable statuses as deferred to avoid required-field skips.
    for key, status in list(state.field_status.items()):
        if status == FieldStatus.NOT_APPLICABLE and not is_not_applicable_allowed(key):
            state.field_status[key] = FieldStatus.DEFERRED

    await loop.run_in_executor(None, upsert_workflow_state, session_id, state.to_dict())

    answered_values = _answered_field_values(discovery_state, direct_fields)
    workflow_context = state.to_agent_context(
        classification_result=classification["classification"],
        answered_values=answered_values,
        deferred_field_keys=list(deferred_fields.keys()),
        previous_active=previous_active,
    )

    return {
        "workflow": state.to_dict(),
        "workflow_context": workflow_context,
        "direct_fields": direct_fields,
        "deferred_fields": list(deferred_fields.keys()),
        "classification": classification,
        "tail_text": tail_text,
        "solution_type": solution_type,
    }


def build_workflow_context_snapshot(
    session_id: str,
    direct_fields: dict[str, str],
) -> tuple[AgentContext, list[str]]:
    """Compute the current workflow-context block without advancing state.

    Unlike prepare_workflow_turn, this performs no classification and persists
    nothing — it is a pure read used to prime a voice session at connect time so
    the audio agent sees the same hidden context the text path injects per turn.
    """
    discovery_state = get_discovery_state(session_id)
    deferred_fields = get_deferred_fields(session_id)
    stored_workflow = get_workflow_state(session_id)
    state = WorkflowState.from_dict(stored_workflow)
    state = sync_workflow_with_discovery_state(state, discovery_state, direct_fields, deferred_fields)

    if state.phase != Phase.READY_TO_FINALIZE:
        next_field = pick_next_active_field(state, discovery_state, direct_fields, deferred_fields)
        if next_field is None:
            state.transition(WorkflowEvent.FIELDS_EXHAUSTED)
        else:
            state.transition(WorkflowEvent.FIELD_FOUND, active_field=next_field)

    answered_values = _answered_field_values(discovery_state, direct_fields)
    workflow_context = state.to_agent_context(
        classification_result="not_answered",
        answered_values=answered_values,
        deferred_field_keys=list(deferred_fields.keys()),
        previous_active=None,
    )
    return workflow_context, list(deferred_fields.keys())


def load_voice_priming(session_id: str) -> str | None:
    """Build the hidden workflow-context block to seed a voice session.

    Returns None for a session with no prior progress (nothing answered, no
    active field, nothing deferred) so brand-new voice sessions are unaffected.
    """
    direct_fields = get_direct_fields(session_id)
    workflow_context, _deferred = build_workflow_context_snapshot(session_id, direct_fields)

    has_direct = bool(clean_direct_fields(direct_fields))
    has_answers = bool(workflow_context.get("answered_fields"))
    has_deferred = bool(workflow_context.get("deferred_fields"))
    if not (has_direct or has_answers or has_deferred):
        return None

    return build_augmented_user_message(
        "",
        direct_fields,
        workflow_context["deferred_fields"],
        workflow_context=workflow_context,
        field_labels=FIELD_LABELS,
    )


async def run_turn_postprocessing(
    session_id: str,
    user_id: str,
    user_text: str,
    assistant_text: str,
    is_finalizing: bool,
    *,
    fallback_transcript: str | None = None,
    message_id: str | None = None,
    trace_id: str | None = None,
    span_id: str | None = None,
    turn_summary: dict | None = None,
) -> None:
    """Shared post-processing pipeline for a completed conversation turn.

    Called by both voice and text chat paths.  Executes these steps:

      1. Persist conversation turn to Firestore (fire-and-forget)
      2. Launch finalizer (if [FINALIZING] detected) — includes its own
         discovery extraction so the heavy Gemini call only happens once

    Discovery field extraction and SRS compilation are NOT done here — the
    frontend triggers those via ``POST /context/extract`` after each turn.
    This avoids duplicate Gemini calls (backend + frontend both extracting).

    Parameters
    ----------
    fallback_transcript:
        Used when the ADK session snapshot is unavailable.  Defaults to a
        simple ``User: / Consultant:`` formatted string.
    """
    loop = asyncio.get_running_loop()

    # 1. Persist conversation turn to Firestore
    if user_text or assistant_text:
        turn_summary = turn_summary or {}
        loop.run_in_executor(
            None,
            partial(
                append_conversation_turn,
                session_id,
                user_text or "(voice input)",
                assistant_text,
                message_id=message_id,
                trace_id=trace_id,
                span_id=span_id,
                **turn_summary,
            ),
        )

    # 2. If [FINALIZING] detected, launch the finalizer pipeline
    #    The finalizer needs discovery fields + conversation transcript,
    #    so we extract them here (only on finalization, not every turn).
    if is_finalizing:
        runtime.record_session_outcome(session_id, "finalized")
        logger.info(f"[FINALIZING] detected: session={session_id} — launching finalizer")
        loop.run_in_executor(None, set_finalization_pending, session_id)

        session_snap = await runtime.session_service.get_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=session_id,
        )
        conversation_text = (
            extract_conversation_text(session_snap)
            if session_snap
            else (fallback_transcript or f"User: {user_text}\nConsultant: {assistant_text}")
        )

        try:
            saved_state = await loop.run_in_executor(None, get_discovery_state, session_id)
            sol_type = solution_type_value(saved_state)
            discovery_fields = await extract_discovery_fields(
                conversation_text,
                session_id=session_id,
                solution_type=sol_type,
            )
            logger.debug(
                f"Discovery fields for finalizer: session={session_id} "
                f"completeness={discovery_fields.get('completeness')}%"
            )
            loop.run_in_executor(None, upsert_discovery_state, session_id, discovery_fields)
        except CostCircuitBreakerTripped as exc:
            logger.warning(f"Finalizer skipped by cost circuit: session={session_id} cost_usd={exc.cost_usd:.6f}")
            loop.run_in_executor(None, set_finalization_error, session_id)
            return
        except Exception as exc:
            logger.warning(f"extract_discovery_fields failed: session={session_id} {exc}")
            discovery_fields = {
                "completeness": 0,
                "fields": {},
                "missing_priority": [],
            }

        asyncio.create_task(
            run_finalizer(
                session_id=session_id,
                user_id=user_id,
                conversation_text=conversation_text,
                discovery_fields=discovery_fields,
            )
        )
