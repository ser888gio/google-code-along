"""Backfill srs_sessions/{id}/sections/* from the legacy rs_field_state_json (migration step 2).

Dry run by default; pass --apply to write. Never overwrites an existing section document, so it is
safe to re-run during the dual-write period and after the state machine has started writing.

    cd backend
    ..\\.venv\\Scripts\\python.exe scripts\\migrate_sections.py                 # dry run, all sessions
    ..\\.venv\\Scripts\\python.exe scripts\\migrate_sections.py --session ID    # one session
    ..\\.venv\\Scripts\\python.exe scripts\\migrate_sections.py --apply
"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from config import (
    FIRESTORE_COLLECTION,
    FIRESTORE_SECTION_EVENTS_SUBCOLLECTION,
    FIRESTORE_SECTIONS_SUBCOLLECTION,
    SPEC_SCHEMA_VERSION,
)
from field_schema import FIELD_SCHEMA
from spec_machine.model import PersistedSection, SectionEventRecord, empty_section


@dataclass
class SessionPlan:
    session_id: str
    sections: dict[str, PersistedSection] = field(default_factory=dict)
    events: list[SectionEventRecord] = field(default_factory=list)


def _legacy_state(session_data: Mapping[str, Any]) -> dict[str, Any]:
    raw = session_data.get("rs_field_state_json")
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw) if raw else {}
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def plan_session(session_id: str, session_data: Mapping[str, Any], existing: Iterable[str]) -> SessionPlan:
    """Map legacy accepted values to `filled` sections; dismissed suggestions become `reject` events."""
    plan = SessionPlan(session_id)
    skip = set(existing)
    state = _legacy_state(session_data)
    now = datetime.now(timezone.utc).isoformat()
    for key in FIELD_SCHEMA:
        if key in skip:
            continue
        entry = state.get(key) if isinstance(state.get(key), dict) else {}
        section = empty_section()
        accepted = entry.get("accepted")
        value = str(accepted.get("value") or "").strip() if isinstance(accepted, dict) else ""
        if value:
            section["status"] = "filled"
            section["value"] = value
        plan.sections[key] = section
        dismissed = entry.get("dismissed_suggestions")
        for suggestion in dismissed if isinstance(dismissed, list) else []:
            plan.events.append(
                {
                    "field_key": key,
                    "kind": "reject",
                    "before": None,
                    "after": str(suggestion),
                    "reason": "migrated:dismissed_suggestion",
                    "modality": "chat",
                    "ts": now,
                }
            )
    return plan


def _apply(client: Any, plan: SessionPlan) -> None:
    session_ref = client.collection(FIRESTORE_COLLECTION).document(plan.session_id)
    batch = client.batch()
    now = datetime.now(timezone.utc).isoformat()
    for key, section in plan.sections.items():
        batch.set(
            session_ref.collection(FIRESTORE_SECTIONS_SUBCOLLECTION).document(key),
            {**section, "updated_at": now},
        )
    for record in plan.events:
        event_ref = session_ref.collection(FIRESTORE_SECTION_EVENTS_SUBCOLLECTION).document()
        batch.set(event_ref, {**record, "event_id": event_ref.id})
    batch.set(session_ref, {"spec_schema_version": SPEC_SCHEMA_VERSION, "updated_at": now}, merge=True)
    batch.commit()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="write to Firestore (default: dry run)")
    parser.add_argument("--session", action="append", default=[], help="limit to these session ids")
    args = parser.parse_args(argv)

    from firestore.writer import _client

    client = _client()
    collection = client.collection(FIRESTORE_COLLECTION)
    snapshots = [collection.document(sid).get() for sid in args.session] if args.session else list(collection.stream())

    totals = {"sessions": 0, "filled": 0, "empty": 0, "skipped_existing": 0, "reject_events": 0}
    for snap in snapshots:
        if not snap.exists:
            print(f"missing session: {snap.id}")
            continue
        existing = [doc.id for doc in snap.reference.collection(FIRESTORE_SECTIONS_SUBCOLLECTION).stream()]
        plan = plan_session(snap.id, snap.to_dict() or {}, existing)
        filled = sum(1 for s in plan.sections.values() if s["status"] == "filled")
        totals["sessions"] += 1
        totals["filled"] += filled
        totals["empty"] += len(plan.sections) - filled
        totals["skipped_existing"] += len(existing)
        totals["reject_events"] += len(plan.events)
        print(
            f"{snap.id}: filled={filled} empty={len(plan.sections) - filled} "
            f"existing={len(existing)} reject_events={len(plan.events)}"
        )
        if args.apply and (plan.sections or plan.events):
            _apply(client, plan)

    mode = "APPLIED" if args.apply else "DRY RUN"
    print(f"{mode}: " + " ".join(f"{key}={value}" for key, value in totals.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
