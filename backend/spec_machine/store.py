"""Firestore persistence for section state.

Layout (the session document *is* the spec):
  srs_sessions/{session_id}                         spec_cursor, spec_schema_version, updated_at
  srs_sessions/{session_id}/sections/{field_key}    PersistedSection
  srs_sessions/{session_id}/section_events/{id}     append-only decision log

Only persisted fields are stored — never internal machine state names.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, cast

from config import (
    FIRESTORE_COLLECTION,
    FIRESTORE_SECTION_EVENTS_SUBCOLLECTION,
    FIRESTORE_SECTIONS_SUBCOLLECTION,
    SPEC_SCHEMA_VERSION,
)
from google.cloud import firestore
from google.cloud.firestore_v1.base_document import DocumentSnapshot
from logger import get_logger
from privacy import redact_text

from spec_machine.model import (
    CommitRequest,
    LoadedDocument,
    MetaRequest,
    PersistedSection,
    RevisionConflict,
    SectionEventRecord,
    coerce_section,
)

logger = get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _snap(ref: Any, transaction: Any | None = None) -> DocumentSnapshot:
    return cast(DocumentSnapshot, ref.get(transaction=transaction) if transaction is not None else ref.get())


def _event_doc(event_id: str, record: SectionEventRecord) -> dict[str, object]:
    reason = redact_text(record["reason"]) if record["reason"] else None
    return {**record, "reason": reason, "event_id": event_id}


class FirestoreSectionStore:
    def __init__(self, client: firestore.Client, session_id: str, *, collection: str = FIRESTORE_COLLECTION) -> None:
        self._client = client
        self._session_id = session_id
        self._collection = collection

    def _session_ref(self) -> Any:
        return self._client.collection(self._collection).document(self._session_id)

    def _section_ref(self, section_id: str) -> Any:
        return self._session_ref().collection(FIRESTORE_SECTIONS_SUBCOLLECTION).document(section_id)

    def _new_event_ref(self) -> Any:
        return self._session_ref().collection(FIRESTORE_SECTION_EVENTS_SUBCOLLECTION).document()

    # --- reads ---

    def load_document(self) -> LoadedDocument:
        session = _snap(self._session_ref())
        data = (session.to_dict() or {}) if session.exists else {}
        cursor = data.get("spec_cursor")
        sections = {
            doc.id: coerce_section(doc.to_dict())
            for doc in self._session_ref().collection(FIRESTORE_SECTIONS_SUBCOLLECTION).stream()
        }
        return LoadedDocument(sections=sections, cursor=cursor if isinstance(cursor, str) else None)

    def load_section(self, section_id: str) -> PersistedSection:
        snap = _snap(self._section_ref(section_id))
        return coerce_section(snap.to_dict() if snap.exists else None)

    # --- writes ---

    def commit(self, request: CommitRequest) -> int:
        """The single commit path: revision check, section write, event append, dependents stale — atomically."""
        transaction = self._client.transaction()
        return cast(int, firestore.transactional(self._commit_in_transaction)(transaction, request))

    def _commit_in_transaction(self, transaction: Any, request: CommitRequest) -> int:
        ref = self._section_ref(request.section_id)
        snap = _snap(ref, transaction)
        current = coerce_section(snap.to_dict() if snap.exists else None)
        if request.expected_revision is None:
            if current["status"] == request.status and current["value"] == request.value:
                return current["revision"]
        elif current["revision"] != request.expected_revision:
            raise RevisionConflict(
                f"section={request.section_id} expected={request.expected_revision} stored={current['revision']}"
            )

        now = _now_iso()
        revision = current["revision"] + 1
        section: PersistedSection = {
            "status": request.status,
            "value": request.value,
            "tbd": request.tbd,
            "proposal": None,
            "draft": None,
            "revision": revision,
            "stale": False,
        }
        transaction.set(ref, {**section, "updated_at": now})
        event_ref = self._new_event_ref()
        transaction.set(event_ref, _event_doc(event_ref.id, request.event))
        for dependent in request.dependents:
            transaction.set(self._section_ref(dependent), {"stale": True, "updated_at": now}, merge=True)
        transaction.set(
            self._session_ref(),
            {"session_id": self._session_id, "updated_at": now, "spec_schema_version": SPEC_SCHEMA_VERSION},
            merge=True,
        )
        return revision

    def save_meta(self, request: MetaRequest) -> None:
        """Persist a skip (status + kept proposal/draft). Not a decision, so the revision is not bumped."""
        transaction = self._client.transaction()
        firestore.transactional(self._save_meta_in_transaction)(transaction, request)

    def _save_meta_in_transaction(self, transaction: Any, request: MetaRequest) -> None:
        ref = self._section_ref(request.section_id)
        snap = _snap(ref, transaction)
        current = coerce_section(snap.to_dict() if snap.exists else None)
        if current["revision"] != request.expected_revision or current["status"] in ("filled", "tbd"):
            # A decision was committed elsewhere since this skip started; the skip no longer applies.
            logger.info(f"Skip not persisted (section changed): section={request.section_id}")
            return
        now = _now_iso()
        transaction.set(
            ref,
            {
                "status": "skipped",
                "proposal": request.proposal,
                "draft": request.draft,
                "revision": current["revision"],
                "updated_at": now,
            },
            merge=True,
        )
        event_ref = self._new_event_ref()
        transaction.set(event_ref, _event_doc(event_ref.id, request.event))

    def record_event(self, record: SectionEventRecord) -> None:
        event_ref = self._new_event_ref()
        event_ref.set(_event_doc(event_ref.id, record))

    def save_export(self, payload: dict[str, object]) -> None:
        self._session_ref().set(
            {
                "session_id": self._session_id,
                "spec_export_json": json.dumps(payload, ensure_ascii=False),
                "updated_at": _now_iso(),
            },
            merge=True,
        )

    def save_cursor(self, cursor: str | None) -> None:
        self._session_ref().set(
            {"session_id": self._session_id, "spec_cursor": cursor, "updated_at": _now_iso()},
            merge=True,
        )
