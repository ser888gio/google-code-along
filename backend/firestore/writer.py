"""
Firestore persistence for the discovery session data collected during a session.

Each session is stored as a single Firestore document at:
  Collection : srs_sessions
  Document ID: <session_id>

The document structure mirrors the Discovery Session schema so the frontend
can display every field in real-time.  `upsert_srs_fields` uses
`set(..., merge=True)` so repeated calls overwrite only the fields that
have a value — previously filled fields are never erased.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, TypedDict, Unpack, cast

from config import (
    FIRESTORE_COLLECTION,
    FIRESTORE_DATABASE,
    GCP_PROJECT,
    require_config_value,
)
from field_schema import FIELD_SCHEMA, REQUIRED_FIELDS
from google.cloud import firestore
from google.cloud.firestore_v1.base_document import DocumentSnapshot
from privacy import hash_text, redact_text

logger = logging.getLogger(__name__)


def _snap(ref: Any) -> DocumentSnapshot:
    """Synchronous DocumentReference.get() always returns a DocumentSnapshot.

    The stubs over-broaden the return type to a sync/async union; this helper
    narrows it back to the sync type so call sites can use .exists/.to_dict()
    without scattered casts.
    """
    return cast(DocumentSnapshot, ref.get())


_COLLECTION = FIRESTORE_COLLECTION
_FEEDBACK_COLLECTION = "feedback"
_VALID_FEEDBACK_VOTES = {"up", "down"}
_VALID_SESSION_RATINGS = {1, 2, 3, 4, 5}
_VALID_ACCEPTED_SOURCES = {
    "user_manual",
    "user_direct_chat",
    "user_accept_suggestion",
    "user_upload",
    "system_import",
}

_firestore_client: firestore.Client | None = None


def _client() -> firestore.Client:
    global _firestore_client
    if _firestore_client is None:
        require_config_value("GCP_PROJECT", GCP_PROJECT, "using Firestore")
        require_config_value("FIRESTORE_COLLECTION", _COLLECTION, "using Firestore")
        require_config_value("FIRESTORE_DATABASE", FIRESTORE_DATABASE, "using Firestore")
        _firestore_client = firestore.Client(project=GCP_PROJECT, database=FIRESTORE_DATABASE)
    return _firestore_client


def _srs_to_doc(session_id: str, srs: dict[str, Any]) -> dict[str, Any]:
    """Flatten the nested SRS JSON dict into a Firestore-compatible document."""
    block1 = srs.get("context_and_business_problem", {})
    block2 = srs.get("target_state_and_success", {})
    block3 = srs.get("scope_and_boundaries", {})
    block4 = srs.get("data_systems_integrations_access", {})

    doc: dict[str, Any] = {
        "session_id": session_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    def _set(key: str, value: Any) -> None:
        """Only include the key if the value is non-empty."""
        if value is not None and str(value).strip():
            doc[key] = value

    # Block 1 — Context & Business Problem
    _set("s1_context", block1.get("context"))
    _set("s1_business_problem", block1.get("business_problem"))

    # Block 2 — Target State & Success
    _set("s2_target_state", block2.get("target_state"))
    _set("s2_success", block2.get("success"))

    # Block 3 — Scope & Boundaries
    _set("s3_scope_in_out", block3.get("scope_in_out"))
    _set("s3_boundaries", block3.get("boundaries"))

    # Block 4 — Data, Systems, Integrations & Access
    _set("s4_data_systems", block4.get("data_systems"))
    _set("s4_integrations_access", block4.get("integrations_access"))

    return doc


def upsert_srs_fields(session_id: str, srs: dict[str, Any]) -> None:
    """Write or merge the SRS data for *session_id* into Firestore.

    Uses `set(..., merge=True)` so only non-empty fields are written and
    previously stored data is never erased by a partial update.
    """
    doc = _srs_to_doc(session_id, srs)
    client = _client()
    ref = client.collection(_COLLECTION).document(session_id)
    ref.set(doc, merge=True)


def get_srs_fields(session_id: str) -> dict[str, Any] | None:
    """Return the stored SRS document for *session_id*, or None if not found."""
    client = _client()
    ref = client.collection(_COLLECTION).document(session_id)
    snap = _snap(ref)
    if not snap.exists:
        return None
    return snap.to_dict()


class MessageTelemetry(TypedDict, total=False):
    trace_id: str | None
    span_id: str | None
    model: str | None
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    cost_usd: float | None
    ttft_ms: int | None
    itl_ms: int | None
    latency_ms: int | None
    tool_calls: list[dict[str, Any]] | None
    phase: str | None
    finish_reason: str | None


def _message_doc(
    *,
    message_id: str,
    role: str,
    text: str,
    created_at: datetime,
    **telemetry: Unpack[MessageTelemetry],
) -> dict[str, Any]:
    """Build the Phase 4 message schema with redacted compatibility fields."""
    text_redacted = redact_text(text)
    doc: dict[str, Any] = {
        "message_id": message_id,
        "trace_id": telemetry.get("trace_id"),
        "span_id": telemetry.get("span_id"),
        "role": role,
        "text_redacted": text_redacted,
        "text_original_hash": hash_text(text),
        "model": telemetry.get("model"),
        "input_tokens": int(telemetry.get("input_tokens") or 0),
        "output_tokens": int(telemetry.get("output_tokens") or 0),
        "cache_read_tokens": int(telemetry.get("cache_read_tokens") or 0),
        "cost_usd": float(telemetry.get("cost_usd") or 0.0),
        "ttft_ms": telemetry.get("ttft_ms"),
        "itl_ms": telemetry.get("itl_ms"),
        "latency_ms": telemetry.get("latency_ms"),
        "tool_calls": telemetry.get("tool_calls") or [],
        "phase": telemetry.get("phase"),
        "finish_reason": telemetry.get("finish_reason"),
        "created_at": created_at,
        # Backwards-compatible fields consumed by the current history UI.
        "text": text_redacted,
        "ts": created_at.isoformat(),
    }
    return {key: value for key, value in doc.items() if value is not None}


def append_conversation_turn(
    session_id: str,
    user_text: str,
    assistant_text: str,
    *,
    message_id: str | None = None,
    **telemetry: Unpack[MessageTelemetry],
) -> None:
    """Append one user+assistant turn to the messages array for *session_id*.

    Phase 4 stores a replayable, BigQuery-exportable message schema and never
    persists raw text. The legacy ``text`` field remains as redacted text for
    existing readers.
    """
    created_at = datetime.now(timezone.utc)
    assistant_message_id = message_id or str(uuid.uuid4())
    user_message_id = f"{assistant_message_id}:user"
    client = _client()
    ref = client.collection(_COLLECTION).document(session_id)
    ref.set(
        {
            "session_id": session_id,
            "updated_at": created_at.isoformat(),
            "messages": firestore.ArrayUnion(
                [
                    _message_doc(
                        message_id=user_message_id,
                        role="user",
                        text=user_text,
                        created_at=created_at,
                        trace_id=telemetry.get("trace_id"),
                        span_id=telemetry.get("span_id"),
                        phase=telemetry.get("phase"),
                    ),
                    _message_doc(
                        message_id=assistant_message_id,
                        role="assistant",
                        text=assistant_text,
                        created_at=created_at,
                        **telemetry,
                    ),
                ]
            ),
        },
        merge=True,
    )


def get_conversation_history(session_id: str) -> list[dict[str, Any]]:
    """Return the messages list for *session_id*, or [] if not found."""
    client = _client()
    ref = client.collection(_COLLECTION).document(session_id)
    snap = _snap(ref)
    if not snap.exists:
        return []
    return (snap.to_dict() or {}).get("messages", [])


def _find_assistant_message(
    messages: list[dict[str, Any]],
    message_id: str,
) -> dict[str, Any] | None:
    for message in messages:
        if message.get("message_id") == message_id and message.get("role") == "assistant":
            return message
    return None


def upsert_message_feedback(
    *,
    session_id: str,
    message_id: str,
    vote: str,
    comment: str | None = None,
) -> dict[str, Any] | None:
    """Persist thumbs feedback for a saved assistant message.

    Returns None when the session/message pair does not exist.
    """
    if vote not in _VALID_FEEDBACK_VOTES:
        raise ValueError("vote must be 'up' or 'down'")

    client = _client()
    session_ref = client.collection(_COLLECTION).document(session_id)
    session_snap = _snap(session_ref)
    if not session_snap.exists:
        return None

    messages = (session_snap.to_dict() or {}).get("messages", [])
    message = _find_assistant_message(messages, message_id)
    if message is None:
        return None

    now = datetime.now(timezone.utc).isoformat()
    feedback_ref = client.collection(_FEEDBACK_COLLECTION).document(message_id)
    existing_snap = _snap(feedback_ref)
    existing = (existing_snap.to_dict() or {}) if existing_snap.exists else {}

    doc: dict[str, Any] = {
        "feedback_id": message_id,
        "session_id": session_id,
        "message_id": message_id,
        "trace_id": message.get("trace_id"),
        "span_id": message.get("span_id"),
        "vote": vote,
        "phase": message.get("phase") or "chat",
        "model": message.get("model"),
        "created_at": existing.get("created_at") or now,
        "updated_at": now,
    }
    if comment is not None:
        doc["comment_redacted"] = redact_text(comment.strip())
        doc["comment_original_hash"] = hash_text(comment)

    feedback_ref.set(
        {key: value for key, value in doc.items() if value is not None},
        merge=True,
    )
    return doc


def update_feedback_comment(
    *,
    session_id: str,
    message_id: str,
    comment: str | None,
) -> dict[str, Any] | None:
    """Update the optional comment for an existing feedback document."""
    client = _client()
    feedback_ref = client.collection(_FEEDBACK_COLLECTION).document(message_id)
    snap = _snap(feedback_ref)
    if not snap.exists:
        return None

    existing = snap.to_dict() or {}
    if existing.get("session_id") != session_id:
        return None

    now = datetime.now(timezone.utc).isoformat()
    update = {
        "comment_redacted": redact_text((comment or "").strip()),
        "comment_original_hash": hash_text(comment),
        "updated_at": now,
    }
    feedback_ref.set(update, merge=True)
    return {**existing, **update}


def upsert_session_feedback(
    *,
    session_id: str,
    rating: int,
    comment: str | None = None,
) -> dict[str, Any] | None:
    """Persist the end-of-chat rating for a session and mark it ended."""
    if rating not in _VALID_SESSION_RATINGS:
        raise ValueError("rating must be an integer from 1 to 5")

    client = _client()
    session_ref = client.collection(_COLLECTION).document(session_id)
    session_snap = _snap(session_ref)
    if not session_snap.exists:
        return None

    now = datetime.now(timezone.utc).isoformat()
    feedback_id = f"session:{session_id}"
    feedback_ref = client.collection(_FEEDBACK_COLLECTION).document(feedback_id)
    existing_snap = _snap(feedback_ref)
    existing = (existing_snap.to_dict() or {}) if existing_snap.exists else {}

    doc: dict[str, Any] = {
        "feedback_id": feedback_id,
        "feedback_type": "session",
        "session_id": session_id,
        "rating": rating,
        "phase": "session",
        "created_at": existing.get("created_at") or now,
        "updated_at": now,
        "ended_at": now,
    }
    if comment is not None:
        doc["comment_redacted"] = redact_text(comment.strip())
        doc["comment_original_hash"] = hash_text(comment)

    feedback_ref.set(
        {key: value for key, value in doc.items() if value is not None},
        merge=True,
    )
    session_ref.set(
        {
            "session_status": "ended",
            "ended_at": now,
            "updated_at": now,
        },
        merge=True,
    )
    return doc


def _json_object(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _normalize_suggestion(value: object) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _valid_field_values(fields: dict[str, str]) -> dict[str, str]:
    return {
        key: str(value).strip()
        for key, value in fields.items()
        if key in FIELD_SCHEMA and value is not None and str(value).strip()
    }


def _rs_field_state_from_doc(data: dict[str, Any]) -> dict[str, Any]:
    parsed = _json_object(data.get("rs_field_state_json"))
    return parsed if isinstance(parsed, dict) else {}


def _write_rs_field_state(session_id: str, state: dict[str, Any]) -> None:
    client = _client()
    ref = client.collection(_COLLECTION).document(session_id)
    ref.set(
        {
            "session_id": session_id,
            "updated_at": _now_iso(),
            "rs_field_state_json": json.dumps(state, ensure_ascii=False),
        },
        merge=True,
    )


def get_rs_field_state(session_id: str) -> dict[str, Any]:
    """Return the persisted accepted RS field state for *session_id*."""
    client = _client()
    ref = client.collection(_COLLECTION).document(session_id)
    snap = _snap(ref)
    if not snap.exists:
        return {}
    return _rs_field_state_from_doc(snap.to_dict() or {})


def get_accepted_rs_fields(session_id: str) -> dict[str, str]:
    """Return accepted RS values only, keyed by field."""
    accepted: dict[str, str] = {}
    for key, entry in get_rs_field_state(session_id).items():
        if key not in FIELD_SCHEMA or not isinstance(entry, dict):
            continue
        accepted_entry = entry.get("accepted")
        if not isinstance(accepted_entry, dict):
            continue
        value = str(accepted_entry.get("value") or "").strip()
        if value:
            accepted[key] = value
    return accepted


def accept_rs_fields(session_id: str, fields: dict[str, str], source: str) -> dict[str, Any]:
    """Persist accepted user decisions for RS fields."""
    if source not in _VALID_ACCEPTED_SOURCES:
        raise ValueError(f"Invalid accepted field source: {source}")

    values = _valid_field_values(fields)
    state = get_rs_field_state(session_id)
    now = _now_iso()
    for key, value in values.items():
        entry = state.setdefault(key, {})
        if not isinstance(entry, dict):
            entry = {}
            state[key] = entry
        entry["accepted"] = {
            "value": value,
            "source": source,
            "accepted_at": now,
        }
    _write_rs_field_state(session_id, state)
    return state


def dismiss_rs_field_suggestions(session_id: str, fields: dict[str, str]) -> dict[str, Any]:
    """Persist dismissed AI suggestion values for RS fields."""
    values = _valid_field_values(fields)
    state = get_rs_field_state(session_id)
    for key, value in values.items():
        entry = state.setdefault(key, {})
        if not isinstance(entry, dict):
            entry = {}
            state[key] = entry
        dismissed = entry.setdefault("dismissed_suggestions", [])
        if not isinstance(dismissed, list):
            dismissed = []
            entry["dismissed_suggestions"] = dismissed
        normalized_existing = {_normalize_suggestion(item) for item in dismissed}
        if _normalize_suggestion(value) not in normalized_existing:
            dismissed.append(value)
    _write_rs_field_state(session_id, state)
    return state


def clear_accepted_rs_fields(session_id: str, field_keys: list[str]) -> dict[str, Any]:
    """Clear accepted values while preserving dismissed suggestion history."""
    state = get_rs_field_state(session_id)
    for key in field_keys:
        if key not in FIELD_SCHEMA:
            continue
        entry = state.setdefault(key, {})
        if isinstance(entry, dict):
            entry.pop("accepted", None)
    _write_rs_field_state(session_id, state)
    return state


def _accepted_completeness(rs_field_state: dict[str, Any]) -> int:
    filled_required = 0
    for key in REQUIRED_FIELDS:
        entry = rs_field_state.get(key)
        accepted = entry.get("accepted") if isinstance(entry, dict) else None
        if isinstance(accepted, dict) and str(accepted.get("value") or "").strip():
            filled_required += 1
    return round((filled_required / len(REQUIRED_FIELDS)) * 100)


def _discovery_completeness(discovery_state: dict[str, Any] | None) -> int:
    if not discovery_state:
        return 0
    try:
        return max(0, min(100, int(discovery_state.get("completeness", 0))))
    except (TypeError, ValueError):
        return 0


def compose_rs_field_view(
    discovery_state: dict[str, Any] | None,
    rs_field_state: dict[str, Any] | None,
) -> dict[str, Any]:
    """Combine AI discovery suggestions with user-accepted field state."""
    user_state = rs_field_state or {}
    discovery_fields = (discovery_state or {}).get("fields") or {}
    fields: dict[str, Any] = {}

    for key in FIELD_SCHEMA:
        user_entry = user_state.get(key)
        if not isinstance(user_entry, dict):
            user_entry = {}

        accepted = user_entry.get("accepted")
        accepted_value = ""
        accepted_payload = None
        if isinstance(accepted, dict):
            accepted_value = str(accepted.get("value") or "").strip()
            if accepted_value:
                accepted_payload = {
                    "value": accepted_value,
                    "source": accepted.get("source") or "user_manual",
                    "accepted_at": accepted.get("accepted_at"),
                }

        dismissed = user_entry.get("dismissed_suggestions")
        dismissed_values = dismissed if isinstance(dismissed, list) else []
        dismissed_normalized = {_normalize_suggestion(item) for item in dismissed_values}

        suggestion_payload = None
        discovery_entry = discovery_fields.get(key)
        if isinstance(discovery_entry, dict) and discovery_entry.get("filled"):
            suggestion_value = str(discovery_entry.get("value") or "").strip()
            if (
                suggestion_value
                and _normalize_suggestion(suggestion_value) not in dismissed_normalized
                and _normalize_suggestion(suggestion_value) != _normalize_suggestion(accepted_value)
            ):
                suggestion_payload = {"value": suggestion_value, "source": "ai"}

        if accepted_payload and suggestion_payload:
            status = "accepted_with_suggestion"
        elif accepted_payload:
            status = "accepted"
        elif suggestion_payload:
            status = "suggested"
        else:
            status = "empty"

        fields[key] = {
            "status": status,
            "accepted": accepted_payload,
            "suggestion": suggestion_payload,
            "dismissed_suggestions": list(dismissed_values),
            # Backwards-compatible view fields for callers during the refactor.
            "filled": bool(accepted_payload),
            "value": accepted_payload["value"] if accepted_payload else None,
            "source": accepted_payload["source"] if accepted_payload else None,
        }

    accepted_completeness = _accepted_completeness(user_state)
    return {
        "completeness": accepted_completeness,
        "accepted_completeness": accepted_completeness,
        "discovery_completeness": _discovery_completeness(discovery_state),
        "fields": fields,
    }


def _preview_from_rs_field_state(data: dict[str, Any]) -> str | None:
    state = _rs_field_state_from_doc(data)
    title_entry = state.get("use_case_title")
    accepted = title_entry.get("accepted") if isinstance(title_entry, dict) else None
    if isinstance(accepted, dict):
        value = str(accepted.get("value") or "").strip()
        if value:
            return value
    return None


def _preview_from_discovery_state(data: dict[str, Any]) -> str | None:
    discovery = _json_object(data.get("discovery_state_json"))
    fields = discovery.get("fields", {})
    if not isinstance(fields, dict):
        return None

    title_entry = fields.get("use_case_title", {})
    if isinstance(title_entry, dict) and title_entry.get("filled"):
        return title_entry.get("value") or None
    return None


def _preview_from_first_user_message(data: dict[str, Any]) -> str | None:
    messages = data.get("messages", [])
    if not isinstance(messages, list):
        return None
    return next(
        (message.get("text") for message in messages if isinstance(message, dict) and message.get("role") == "user"),
        None,
    )


def _session_preview(data: dict[str, Any]) -> str | None:
    # Prefer the project name, then extracted state, then the first user message.
    return (
        _preview_from_rs_field_state(data)
        or _preview_from_discovery_state(data)
        or _preview_from_first_user_message(data)
    )


def list_sessions() -> list[dict[str, Any]]:
    """Return a summary of all sessions ordered by updated_at descending."""
    client = _client()
    results = []
    for doc in client.collection(_COLLECTION).stream():
        data = doc.to_dict() or {}
        results.append(
            {
                "session_id": data.get("session_id") or doc.id,
                "updated_at": data.get("updated_at"),
                "preview": _session_preview(data),
            }
        )
    results.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
    return results


# ---------------------------------------------------------------------------
# Final analysis persistence (written by the Finalizer Agent pipeline)
# ---------------------------------------------------------------------------


def set_finalization_pending(session_id: str) -> None:
    """Mark the session as finalization in-progress.

    Called by main.py immediately when [FINALIZING] is detected so the
    frontend can show a spinner while run_finalizer() runs in the background.
    """
    client = _client()
    ref = client.collection(_COLLECTION).document(session_id)
    ref.set(
        {
            "session_id": session_id,
            "finalization_status": "pending",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        merge=True,
    )


def upsert_final_analysis(session_id: str, analysis: dict) -> None:
    """Persist the completed final analysis to Firestore.

    Stores:
    - finalization_status: "complete"
    - finalized_at: ISO timestamp
    - final_analysis_json: full JSON blob (used by GET /analyses/{session_id})

    Uses merge=True so prior conversation/SRS fields are never erased.
    """
    client = _client()
    ref = client.collection(_COLLECTION).document(session_id)
    ref.set(
        {
            "session_id": session_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "finalization_status": "complete",
            "finalized_at": datetime.now(timezone.utc).isoformat(),
            # Full JSON stored as a string so sub-field types do not
            # need a Firestore schema.
            "final_analysis_json": json.dumps(analysis, ensure_ascii=False),
        },
        merge=True,
    )


def get_final_analysis(session_id: str) -> dict | None:
    """Return the finalization status and data for a session.

    Returns:
        None                                   — document doesn't exist
        {"finalization_status": "pending"}     — still running
        {"finalization_status": "error"}       — pipeline failed
        full analysis dict with "finalization_status": "complete"
    """
    client = _client()
    ref = client.collection(_COLLECTION).document(session_id)
    snap = _snap(ref)
    if not snap.exists:
        return None
    data = snap.to_dict() or {}
    status = data.get("finalization_status")
    if not status:
        return None
    if status != "complete":
        return {"finalization_status": status}
    json_str = data.get("final_analysis_json")
    if json_str:
        try:
            result = json.loads(json_str)
            result["finalization_status"] = "complete"
            return result
        except Exception as exc:
            logger.warning(f"[Firestore] Failed to parse final_analysis_json: {exc}")
    return data


def upsert_discovery_state(session_id: str, discovery: dict) -> None:
    """Persist the latest 22-field discovery extraction for *session_id*.

    Stored as a JSON string so the nested field schema doesn't need a
    Firestore schema change.  Uses merge=True so conversation/SRS data
    already on the document is never erased.
    """
    client = _client()
    ref = client.collection(_COLLECTION).document(session_id)
    ref.set(
        {
            "session_id": session_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "discovery_state_json": json.dumps(discovery, ensure_ascii=False),
        },
        merge=True,
    )


# ---------------------------------------------------------------------------
# Direct-input fields — set by the user in the UI, never overwritten by AI
# ---------------------------------------------------------------------------


def upsert_direct_fields(session_id: str, fields: dict[str, str]) -> None:
    """Persist user-entered direct field values for *session_id*.

    Stored separately from AI-extracted state so subsequent AI extraction
    runs never erase values the user typed manually.
    Uses a read-modify-write so earlier direct values are not lost.
    """
    client = _client()
    ref = client.collection(_COLLECTION).document(session_id)
    snap = _snap(ref)
    existing_json = (snap.to_dict() or {}).get("direct_fields_json") if snap.exists else None
    try:
        existing: dict[str, str] = json.loads(existing_json) if existing_json else {}
    except Exception:
        existing = {}
    existing.update({k: v for k, v in fields.items() if v is not None})
    ref.set(
        {
            "session_id": session_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "direct_fields_json": json.dumps(existing, ensure_ascii=False),
        },
        merge=True,
    )


def get_direct_fields(session_id: str) -> dict[str, str]:
    """Return the directly-set field values for *session_id* (empty dict if none)."""
    client = _client()
    ref = client.collection(_COLLECTION).document(session_id)
    snap = _snap(ref)
    if not snap.exists:
        return {}
    json_str = (snap.to_dict() or {}).get("direct_fields_json")
    if not json_str:
        return {}
    try:
        return json.loads(json_str)
    except Exception:
        return {}


def upsert_deferred_fields(session_id: str, fields: dict[str, Any]) -> None:
    """Persist fields the user explicitly chose to defer.

    Values are metadata objects, e.g. {"deferred_at": "..."}; callers may also
    pass truthy placeholders for backwards compatibility.
    """
    if not fields:
        return

    client = _client()
    ref = client.collection(_COLLECTION).document(session_id)
    snap = _snap(ref)
    existing_json = (snap.to_dict() or {}).get("deferred_fields_json") if snap.exists else None
    try:
        existing: dict[str, Any] = json.loads(existing_json) if existing_json else {}
    except Exception:
        existing = {}

    now = datetime.now(timezone.utc).isoformat()
    for key, value in fields.items():
        if value is None:
            existing.pop(key, None)
        elif isinstance(value, dict):
            existing[key] = value
        else:
            existing[key] = {"deferred_at": now}

    ref.set(
        {
            "session_id": session_id,
            "updated_at": now,
            "deferred_fields_json": json.dumps(existing, ensure_ascii=False),
        },
        merge=True,
    )


def get_deferred_fields(session_id: str) -> dict[str, Any]:
    """Return persisted deferred fields for *session_id*."""
    client = _client()
    ref = client.collection(_COLLECTION).document(session_id)
    snap = _snap(ref)
    if not snap.exists:
        return {}
    json_str = (snap.to_dict() or {}).get("deferred_fields_json")
    if not json_str:
        return {}
    try:
        parsed = json.loads(json_str)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def remove_deferred_fields(session_id: str, field_keys: list[str]) -> None:
    """Remove fields from the persisted deferred-field set."""
    if not field_keys:
        return
    upsert_deferred_fields(session_id, {key: None for key in field_keys})


def get_workflow_state(session_id: str) -> dict | None:
    """Return persisted workflow cursor state for *session_id*."""
    client = _client()
    ref = client.collection(_COLLECTION).document(session_id)
    snap = _snap(ref)
    if not snap.exists:
        return None
    json_str = (snap.to_dict() or {}).get("workflow_state_json")
    if not json_str:
        return None
    try:
        parsed = json.loads(json_str)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def upsert_workflow_state(session_id: str, state: dict) -> None:
    """Persist workflow cursor state for *session_id*."""
    client = _client()
    ref = client.collection(_COLLECTION).document(session_id)
    ref.set(
        {
            "session_id": session_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "workflow_state_json": json.dumps(state, ensure_ascii=False),
        },
        merge=True,
    )


def get_discovery_state(session_id: str) -> dict | None:
    """Return the last saved discovery state for *session_id*, or None.

    Returns the parsed dict: {completeness, fields, missing_priority},
    or None if nothing has been saved yet.
    """
    client = _client()
    ref = client.collection(_COLLECTION).document(session_id)
    snap = _snap(ref)
    if not snap.exists:
        return None
    data = snap.to_dict() or {}
    ai_json = data.get("discovery_state_json")

    if not ai_json:
        return None

    try:
        state: dict = json.loads(ai_json)
    except Exception:
        state = {"completeness": 0, "fields": {}, "missing_priority": []}

    # Tag every AI-extracted field with source='ai' before direct fields overlay.
    for entry in state.get("fields", {}).values():
        if isinstance(entry, dict):
            entry.setdefault("source", "ai" if entry.get("filled") else None)

    return state


def set_finalization_error(session_id: str) -> None:
    """Mark a session finalizer run as failed so the frontend can stop polling."""
    client = _client()
    ref = client.collection(_COLLECTION).document(session_id)
    ref.set(
        {
            "session_id": session_id,
            "finalization_status": "error",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        merge=True,
    )
