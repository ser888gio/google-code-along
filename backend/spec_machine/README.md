# Section state machine (`spec_machine`)

Controls the lifecycle of each RS field ("section") and the navigation between them, for chat and voice.
One section per `FIELD_SCHEMA` entry; section config (`kind`, `required`, `depends_on`, `input_format`)
comes from `backend/field_schema.py`.

| File | Role |
|---|---|
| `model.py` | Section config, typed events, persisted shapes, `MachineServices` (all side effects) |
| `section.py` | `SectionActor`: per-field lifecycle |
| `document.py` | `DocumentActor`: one actor per field, navigation, proposal queue, staleness, review, finalize |
| `intents.py` | Utterance → typed events (keywords first, small model only for ambiguous simple-field replies) |
| `store.py` | Firestore persistence: commit transaction, skip metadata, event log, cursor |
| `services.py` | Production services: Gemini generation, deterministic validation, directory lookup |
| `legacy_mirror.py` | Dual-write of legacy `rs_field_state_json` decisions (migration step 3) |

## Rules the code enforces

- **The LLM never picks a transition.** `generate` runs only in `generating` and returns
  `ProposalOutput` or `QuestionOutput`. User intents are typed events.
- **The committed value is independent of the current state.** Revising, editing, rejecting or cancelling
  never touches `ctx.value`; only a successful commit does.
- **Simple sections never call the LLM.** "I don't know" → directory lookup; `REVISE` is ignored.
- **One commit path:** `validating → committing` → `FirestoreSectionStore.commit`, a transaction that checks
  the revision, writes the section with `revision + 1`, appends an event, and marks dependents stale.
- **Skip ≠ "I don't know".** Skip keeps the proposal/draft (persisted, revision unchanged). TBD is a
  decision and goes through the commit path.
- Only persisted fields are stored. Machine state names never reach Firestore; `init`/`rest` rebuild state
  from `status`/`value`/`tbd`/`proposal`/`draft`.

## How the agent loop drives it

The agent loop (chat handler or voice turn handler) never mutates section data itself. Per user turn:

1. **Map the utterance.** `POST /spec/{session_id}/utterance` with `{"text": ..., "modality": "chat"|"voice"}`.
   The router reads the current section's state and kind, calls `resolve_utterance`, and sends the events.
   UI buttons skip the mapping and post typed events directly:
   `POST /spec/{session_id}/events` with `{"type": "ACCEPT"}`, `{"type": "SUBMIT", "value": ...}`,
   `{"type": "NEXT"}`, `{"type": "GO_TO", "section_id": ...}`, `{"type": "MARK_TBD", "owner": ...}`, ...
2. **Read the result.** Both endpoints wait for the current section's generation, validation or commit to
   finish (`wait: false` to return immediately) and return `snapshot.current`:
   - `agent_message` + `message_code`: what the assistant should say next, for example a generated question,
     the "I don't know" offer, the voice read-back (`confirm_value`) or a validation error. Use
     `message_code` to localise the text (Czech/English).
   - `proposal` + `rationale` while `state == "proposed"`: present it for accept, edit or refine.
   - `state`, `status`, `value`, `tbd`, `stale`, `lookup_results`, `needs_confirmation`.
   - `snapshot.sections[*].queued_proposal`: background proposals for other sections, shown as a badge.
     They are delivered when the user enters that section and never steal focus.
   - `snapshot.state == "reviewingOpenItems"` → show `snapshot.open_items` once.
     `finalize_blocked` lists the fields that block `FINALIZE`.
3. **On `commit_conflict`** (another instance or the legacy endpoint changed the field), post
   `{"type": "RELOAD_SECTION", "section_id": ...}`.

Speaking or displaying `agent_message` is the agent's job. The machine only decides *what* happens.

## Deviations from the original spec (deliberate)

- `MARK_TBD` is also accepted in `gathering`, `proposed`, `editing`, `awaitingInput` and `generationFailed`.
  This lets "ask Martin" work without an "I don't know" round trip first.
- `CANCEL` is also accepted in `gathering` (only when the field already has a decision), `unsure` and
  `lookingUp`, so the user can always back out of a revision.
- `SKIP` is also accepted in `confirming` and `lookingUp`, so navigating away never leaves a section stuck.
- `MARK_STALE` applies in any state (Firestore marks dependents stale regardless of their state).
- Committing TBD clears the value: `status` is the single source for "decided as open item".

## Limitations

- Actors are process-local (like ADK sessions) and capped at 256 sessions per instance. They rehydrate from
  Firestore on first use. Cross-instance edits surface as revision conflicts.
- Queued background proposals are in memory only; a restart drops the badge, not any decision.
- `depends_on` is empty for every field until product defines the dependency edges.
- The "I don't know" directory is the optional JSON file at `SECTION_DIRECTORY_PATH`
  (`{"name": ["Jana Nováková", ...]}`, or keyed by field id). Without it, lookup returns no matches and the
  user is offered TBD or skip.
