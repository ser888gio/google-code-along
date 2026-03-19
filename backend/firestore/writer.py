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
from datetime import datetime, timezone
from typing import Any

from config import FIRESTORE_COLLECTION, FIRESTORE_DATABASE, GCP_PROJECT
from google.cloud import firestore

_COLLECTION = FIRESTORE_COLLECTION


def _client() -> firestore.Client:
    return firestore.Client(project=GCP_PROJECT, database=FIRESTORE_DATABASE)


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
    snap = ref.get()
    if not snap.exists:
        return None
    return snap.to_dict()


def append_conversation_turn(
    session_id: str, user_text: str, assistant_text: str
) -> None:
    """Append one user+assistant turn to the messages array for *session_id*.

    Uses ArrayUnion so each call safely appends without overwriting prior turns.
    Creates the document if it does not exist yet.
    """
    ts = datetime.now(timezone.utc).isoformat()
    client = _client()
    ref = client.collection(_COLLECTION).document(session_id)
    ref.set(
        {
            "session_id": session_id,
            "messages": firestore.ArrayUnion(
                [
                    {"role": "user", "text": user_text, "ts": ts},
                    {"role": "assistant", "text": assistant_text, "ts": ts},
                ]
            ),
        },
        merge=True,
    )


def get_conversation_history(session_id: str) -> list[dict[str, Any]]:
    """Return the messages list for *session_id*, or [] if not found."""
    client = _client()
    ref = client.collection(_COLLECTION).document(session_id)
    snap = ref.get()
    if not snap.exists:
        return []
    return snap.to_dict().get("messages", [])


def list_sessions() -> list[dict[str, Any]]:
    """Return a summary of all sessions ordered by updated_at descending."""
    client = _client()
    results = []
    for doc in client.collection(_COLLECTION).stream():
        data = doc.to_dict()
        messages = data.get("messages", [])
        preview = next((m["text"] for m in messages if m.get("role") == "user"), None)
        results.append(
            {
                "session_id": data.get("session_id") or doc.id,
                "updated_at": data.get("updated_at"),
                "preview": preview,
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
            # Full JSON stored as a string so sub-field types don't need a Firestore schema
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
    snap = ref.get()
    if not snap.exists:
        return None
    data = snap.to_dict()
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
        except Exception:
            pass
    return data


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
