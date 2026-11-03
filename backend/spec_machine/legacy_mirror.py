"""Dual-write: mirror legacy `rs_field_state_json` decisions into the per-section documents.

Called after the legacy write succeeds. Best-effort by design — a mirror failure is logged and never
fails the legacy request; the backfill script (scripts/migrate_sections.py) repairs any drift.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from functools import cache

from field_schema import FIELD_SCHEMA
from google.cloud import firestore
from logger import get_logger

from spec_machine.model import (
    CommitRequest,
    EventKind,
    SectionEventRecord,
    build_dependents,
    section_configs_from_schema,
)
from spec_machine.store import FirestoreSectionStore

logger = get_logger(__name__)


@cache
def _schema_dependents() -> dict[str, tuple[str, ...]]:
    return build_dependents(section_configs_from_schema())


def _record(
    field_key: str, kind: EventKind, before: str | None, after: str | None, reason: str | None
) -> SectionEventRecord:
    return {
        "field_key": field_key,
        "kind": kind,
        "before": before,
        "after": after,
        "reason": reason,
        "modality": "chat",
        "ts": datetime.now(timezone.utc).isoformat(),
    }


def _best_effort(session_id: str, action: str, run: Callable[[], object]) -> None:
    try:
        run()
    except Exception as exc:  # noqa: BLE001 — the legacy write already succeeded; drift is repaired by backfill
        logger.warning(f"Section mirror failed: action={action} session_id={session_id} error={type(exc).__name__}")


def mirror_accepted(client: firestore.Client, session_id: str, fields: Mapping[str, str], source: str) -> None:
    store = FirestoreSectionStore(client, session_id)
    kind: EventKind = "accept" if source == "user_accept_suggestion" else "edit"
    for key, value in fields.items():
        if key not in FIELD_SCHEMA:
            continue
        request = CommitRequest(
            section_id=key,
            expected_revision=None,
            status="filled",
            value=value,
            tbd=None,
            event=_record(key, kind, None, value, f"legacy:{source}"),
            dependents=_schema_dependents()[key],
        )
        _best_effort(session_id, "accept", lambda r=request: store.commit(r))


def mirror_cleared(client: firestore.Client, session_id: str, keys: list[str]) -> None:
    store = FirestoreSectionStore(client, session_id)
    for key in keys:
        if key not in FIELD_SCHEMA:
            continue
        request = CommitRequest(
            section_id=key,
            expected_revision=None,
            status="empty",
            value=None,
            tbd=None,
            event=_record(key, "edit", None, None, "legacy:clear"),
            dependents=_schema_dependents()[key],
        )
        _best_effort(session_id, "clear", lambda r=request: store.commit(r))


def mirror_dismissed(client: firestore.Client, session_id: str, fields: Mapping[str, str]) -> None:
    store = FirestoreSectionStore(client, session_id)
    for key, value in fields.items():
        if key not in FIELD_SCHEMA:
            continue
        record = _record(key, "reject", None, value, "legacy:dismiss_suggestion")
        _best_effort(session_id, "dismiss", lambda r=record: store.record_event(r))
