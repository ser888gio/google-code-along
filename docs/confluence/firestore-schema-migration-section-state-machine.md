# Firestore Schema Migration: Section State Machine

Last updated: 2026-11-02

## Why

The per-field lifecycle state machine lives in `backend/spec_machine/` (see its `README.md`). It handles
gathering → generating → proposed → editing → validating → committing → accepted/tbd/skipped. Skip and
"I don't know" are distinct outcomes, and the machine adds dependency staleness and an audit trail. It
needs per-field documents with a revision counter, which the current single-document model cannot provide.
This doc covers the Firestore migration only.

## Current State (before migration)

Everything for one discovery session lives in **one document**, `srs_sessions/{session_id}`, written with
`set(..., merge=True)` (`backend/firestore/writer.py`):

- `discovery_state_json`: AI-extracted suggestions. Never a decision. **Not migrated**; it stays where it is.
- `rs_field_state_json`: per-field user decisions (`accepted` value + `dismissed_suggestions`).
  See `docs/accepted-rs-field-state-flow.md`.

Missing for the new machine: `skipped`/`tbd` status, a revision counter with optimistic concurrency, an
append-only event log, `depends_on`/staleness, and a `kind: ai | simple` marker.

## Target State

The session document *is* the spec; no new top-level identity.

```
srs_sessions/{session_id}                         spec_cursor, spec_schema_version (2), spec_export_json
srs_sessions/{session_id}/sections/{field_key}    PersistedSection, one per FIELD_SCHEMA key
srs_sessions/{session_id}/section_events/{id}     append-only decision log
```

`section_events` (not `events`) avoids confusion with ADK session events.

```python
class PersistedSection(TypedDict):
    status: Literal["empty", "skipped", "tbd", "filled"]
    value: str | None
    tbd: TbdInfo | None          # {note?, open_question?, owner?}
    proposal: str | None         # kept across skip
    draft: str | None            # kept across skip-from-editing
    revision: int
    stale: bool

class SectionEventRecord(TypedDict):  # stored with event_id; reason is PII-redacted
    field_key: str
    kind: Literal["accept", "reject", "edit", "tbd", "skip"]
    before: str | None
    after: str | None
    reason: str | None
    modality: Literal["chat", "voice"]
    ts: str
```

`FieldDef` additions in `backend/field_schema.py`: `kind` (default `"ai"`), `input_format`
(`name | number | text`, simple fields only), and `depends_on` (default empty).

## Field Classification (done)

Simple fields (never sent to the LLM, validated deterministically):

| Field | input_format | Why |
|---|---|---|
| `department`, `requester`, `product_owner` | `name` | A name or code; voice input is read back for confirmation |
| `saved_time_hours_per_year` | `number` | Must contain a figure |
| `cost_saving`, `revenue_increase` | `text` | User-provided figure or "unknown"; the AI cannot know it |
| `comments`, `attachments` | `text` | Literal user input / uploads |

All other fields are `ai`. This differs from a pure "`direct_input` and not `ai_extractable`" rule:
`department`, `requester` and `product_owner` are AI-extractable but are plain names, so they are simple.
`use_case_title` stays `ai`.

`depends_on` is **empty for every field**. Dependency edges need a product decision. Until then commits
mark nothing stale and the background dependent review never runs.

## Mapping Legacy Data

- `rs_field_state_json.<field>.accepted.value` → `status: "filled"`, `value`, `revision: 0`.
- No accepted value → `status: "empty"`.
- Each `dismissed_suggestions` entry → one `reject` event with `reason: "migrated:dismissed_suggestion"`.
  This keeps the pre-migration audit trail.
- No legacy data maps to `skipped` or `tbd`; those only appear once the machine is used.

## Migration Steps

| # | Step | Status |
|---|---|---|
| 1 | Add `kind`, `input_format`, `depends_on` to `FieldDef` | Done. Generated frontend schema is unchanged. |
| 2 | Backfill `backend/scripts/migrate_sections.py` | Done. Dry run by default. Never overwrites an existing section doc. |
| 3 | Dual-write: legacy accept/dismiss/clear also write sections/events (`spec_machine/legacy_mirror.py`) | Done. Best-effort: a mirror failure is logged, never fails the legacy request. |
| 4 | Cut over reads: `compose_rs_field_view`, `RsLiveTemplate`, DOCX export read `sections/*` | **Not started.** Do after the machine is validated in staging. |
| 5 | Stop dual-write for new sessions; keep old fields (no destructive cleanup) | **Not started.** Before this step, write the inverse (sections → `rs_field_state_json`) script for rollback. |
| 6 | Firestore rules: deny client-SDK access to `sections` and `section_events` (`infra/firestore/firestore.rules`) | File added. **Merge into the live rules manually**; this repo did not manage rules before. |

Run order for a rollout:

```powershell
cd backend
..\.venv\Scripts\python.exe scripts\migrate_sections.py --session <one-test-session>   # inspect output
..\.venv\Scripts\python.exe scripts\migrate_sections.py                               # dry run, all
..\.venv\Scripts\python.exe scripts\migrate_sections.py --apply
```

Deploy the dual-write code **before** running `--apply`, so no legacy write lands between backfill and
dual-write. Re-running the backfill is safe because existing section docs are skipped.

Legacy writes go through the same commit transaction with `expected_revision=None` (last writer wins,
idempotent for an unchanged value). They still bump the revision, so a live machine actor holding an older
revision gets a `commit_conflict` and reloads instead of overwriting the legacy edit.

## Rollback

Before step 5 nothing old is removed: point reads back at `rs_field_state_json`/`discovery_state_json` and
stop calling the `/spec` endpoints. The `sections`/`section_events` subcollections can stay; nothing else
reads them. After step 5, rollback needs the inverse script mentioned above.

## Testing

- `tests/test_spec_machine.py`: the 13 machine scenarios plus abort, timeout, busy-navigation and store edge
  cases. They run against the real `FirestoreSectionStore` on an in-memory Firestore fake
  (`tests/fake_firestore.py`) with atomic transactions.
- `tests/test_spec_intents.py`: utterance mapping, validation, legacy mirror.
- `tests/test_spec_api.py`: HTTP endpoints with Firestore and the LLM stubbed.
- `tests/test_migrate_sections.py`: backfill planning.
- Not yet covered: a run against the Firestore emulator or a staging project.
