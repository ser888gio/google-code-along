# Plan 001: Add characterization tests for the turn engine, FSM, and Firestore writer

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat effe765..HEAD -- backend/chat_turn.py backend/workflow_state.py backend/firestore/writer.py backend/tests/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW (test-only change — no production code is modified)
- **Depends on**: none
- **Category**: tests
- **Planned at**: commit `effe765`, 2026-06-10

## Why this matters

`backend/chat_turn.py` (387 lines) is the turn engine that runs around every single conversation turn — it classifies answers, advances the workflow FSM, persists state, and launches the finalizer. `backend/firestore/writer.py` (982 lines) is the only persistence layer. Neither has any direct test today; `backend/workflow_state.py` (the FSM) is only exercised indirectly by 7 tests in `backend/tests/test_one_field_workflow.py`. Plan 002 will modify `chat_turn.run_turn_postprocessing`, and a later refactor may split these modules — characterization tests must land first so those changes have a safety net. This plan locks in *current* behavior; it does not fix any bugs.

## Current state

Relevant files:

- `backend/chat_turn.py` — turn engine. Two main entry points:
  - `prepare_workflow_turn(...)` (lines 129–226) — async; loads discovery/deferred/workflow state from Firestore (via `loop.run_in_executor`), advances the FSM, persists workflow state, returns a dict with keys `workflow`, `workflow_context`, `direct_fields`, `deferred_fields`, `classification`, `tail_text`, `solution_type`.
  - `run_turn_postprocessing(...)` (lines ~290–388) — async; persists the conversation turn (fire-and-forget `loop.run_in_executor` at line 322) and, when `is_finalizing=True`, extracts discovery fields and launches `run_finalizer` via `asyncio.create_task` (line 380).
- `backend/workflow_state.py` — FSM. `Phase`/`FieldStatus`/`WorkflowEvent` StrEnums, transition table `_TRANSITIONS` (lines 51–60), `WorkflowState` dataclass with `transition()` (raises `InvalidTransition` on bad moves), `to_dict()`/`from_dict()` round-trip (lines 116–166; `from_dict` falls back to safe defaults on bad input).
- `backend/firestore/writer.py` — all persistence. Notable functions for this plan: `set_finalization_pending` (line 686), `upsert_final_analysis` (line 704), `get_final_analysis` (line 730, returns `None` / `{"finalization_status": "pending"|"error"}` / full dict with `"complete"`), `upsert_discovery_state` (line 761), plus `append_conversation_turn`, `get_discovery_state`, `get_workflow_state`, `upsert_workflow_state`, `upsert_deferred_fields`, `remove_deferred_fields`.
- `backend/tests/conftest.py` — installs stub modules for `google.adk`, `google.genai`, and `google.cloud.firestore` **before collection**, so backend modules import without GCP credentials. `google.cloud.firestore.Client` is a `MagicMock` (line 138). This means `firestore/writer.py` functions can be tested by patching `firestore.writer._client`.
- `backend/tests/test_one_field_workflow.py` — the structural exemplar. Plain functions named `test_*`, no classes, direct construction of `WorkflowState`, e.g.:

```python
# backend/tests/test_one_field_workflow.py:15-20
def test_pick_next_active_field_prioritizes_required_schema_order():
    state = WorkflowState()
    state.field_status["use_case_title"] = "answered"
    state.field_status["department"] = "answered"

    assert pick_next_active_field(state) == "requester"
```

Key excerpt — the FSM transition table you will characterize (`backend/workflow_state.py:51–60`):

```python
_TRANSITIONS: dict[tuple[Phase, WorkflowEvent], Phase] = {
    (Phase.DISCOVERY, WorkflowEvent.FIELD_FOUND): Phase.DISCOVERY,
    (Phase.DISCOVERY, WorkflowEvent.FIELDS_EXHAUSTED): Phase.WRAP_UP,
    (Phase.WRAP_UP, WorkflowEvent.FINALIZE_CHOSEN): Phase.READY_TO_FINALIZE,
    (Phase.WRAP_UP, WorkflowEvent.REOPEN_DEFERRED): Phase.DISCOVERY,
    (Phase.WRAP_UP, WorkflowEvent.FIELD_FOUND): Phase.DISCOVERY,
    (Phase.WRAP_UP, WorkflowEvent.FIELDS_EXHAUSTED): Phase.WRAP_UP,
    (Phase.READY_TO_FINALIZE, WorkflowEvent.FINALIZE_STARTED): Phase.FINALIZING,
    (Phase.FINALIZING, WorkflowEvent.FINALIZE_COMPLETE): Phase.COMPLETE,
}
```

Conventions: Python 3.12, type hints, plain pytest (no test classes), `pytest-asyncio` style — check whether `pytest-asyncio` is installed by running the existing suite first; if async tests need it and it is absent, test async functions via `asyncio.run(...)` inside a sync test function instead of installing anything.

## Commands you will need

Run from the `backend/` directory. **Always use the venv interpreter** — the global `python` on this machine is the wrong version.

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Run full suite | `.\.venv\Scripts\python.exe -m pytest tests -v` | exit 0, all pass (74 tests pre-existing) |
| Run one file | `.\.venv\Scripts\python.exe -m pytest tests/test_workflow_state.py -v` | exit 0 |
| Lint (repo-wide, from repo root) | `pre-commit run --all-files` | exit 0 (some hooks may be skipped locally — that is acceptable per repo docs) |

If the venv is not at `backend/.venv`, check for a repo-root `.venv` and use `..\.venv\Scripts\python.exe` from `backend/`.

## Scope

**In scope** (the only files you should create/modify):
- `backend/tests/test_workflow_state.py` (create)
- `backend/tests/test_chat_turn.py` (create)
- `backend/tests/test_firestore_writer.py` (create)
- `plans/README.md` (status row update)

**Out of scope** (do NOT touch):
- `backend/chat_turn.py`, `backend/workflow_state.py`, `backend/firestore/writer.py` — this plan characterizes behavior; if you find a bug, write the test to match *current* behavior and note the bug in your report. Plan 002 fixes known issues.
- `backend/tests/conftest.py` — the stub installer is load-bearing for the whole suite. If your tests need an additional stub, STOP and report rather than editing it.
- Any production code anywhere.

## Git workflow

- Branch: `advisor/001-characterization-tests` off `develop`.
- One commit per step is fine; message style: short imperative summary (see `git log --oneline` for examples). Do NOT add a Co-Authored-By trailer (repo owner preference).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Baseline — run the existing suite

Run the full suite first to record the passing baseline and confirm the conftest stubs work in your environment.

**Verify**: `.\.venv\Scripts\python.exe -m pytest tests -v` → exit 0, note the test count.

### Step 2: FSM characterization — `backend/tests/test_workflow_state.py`

Import from `workflow_state`: `Phase`, `FieldStatus`, `WorkflowEvent`, `WorkflowState`, `InvalidTransition`. Write tests for:

1. Every entry in `_TRANSITIONS` — parametrize over the 8 valid (phase, event) → phase triples; assert `state.phase` after `transition()`.
2. At least 4 *invalid* combinations raise `InvalidTransition` (e.g. `FINALIZE_COMPLETE` from `DISCOVERY`, `FINALIZE_STARTED` from `WRAP_UP`, `FINALIZE_CHOSEN` from `DISCOVERY`, any event from `COMPLETE`).
3. Payload side effects: `FIELD_FOUND` sets `active_field`; `FINALIZE_CHOSEN` and `FIELDS_EXHAUSTED` clear it; `REOPEN_DEFERRED` sets `active_field`, resets its `field_status` to `MISSING` and its `miss_counts` to 0.
4. `to_dict()` → `from_dict()` round-trip preserves phase, active_field, field_status, counts, coverage_gaps.
5. `from_dict` robustness: `from_dict(None)` returns defaults; unknown phase string falls back to `Phase.DISCOVERY`; `active_field` not in `FIELD_SCHEMA` becomes `None`; unknown field-status strings become `MISSING`.

**Verify**: `.\.venv\Scripts\python.exe -m pytest tests/test_workflow_state.py -v` → all pass.

### Step 3: Turn-engine characterization — `backend/tests/test_chat_turn.py`

Test `prepare_workflow_turn` with all Firestore functions and classifiers patched (`unittest.mock.patch` on the names *as imported in `chat_turn`*, e.g. `chat_turn.get_discovery_state`, `chat_turn.classify_and_update_active_field`). Use `asyncio.run(...)` to drive the coroutine (or `pytest.mark.asyncio` if `pytest-asyncio` is already installed). Cases:

1. **Wrap-up + finalize choice**: stored workflow in `WRAP_UP` phase, message `"finalize"` → returned `workflow["phase"] == "ready_to_finalize"` (the helper `_is_finalize_choice` at `chat_turn.py:93–108` matches `finalize`, `generate`, `vygeneruj`, etc.).
2. **Wrap-up + non-finalize message with deferred fields**: phase moves back to `discovery` and the first deferred field becomes active (`_reopen_first_deferred_field`, lines 111–126); `remove_deferred_fields` is called with that key.
3. **Discovery with an active field**: `classify_and_update_active_field` and `apply_proactive_updates` are called; their patched results flow into the returned `classification`.
4. **Fields exhausted**: patch `pick_next_active_field` to return `None` → phase transitions to `wrap_up`.
5. **NOT_APPLICABLE coercion**: a field whose status is `NOT_APPLICABLE` and for which patched `is_not_applicable_allowed` returns `False` ends up `DEFERRED` (lines 203–206).
6. **Persistence call**: `upsert_workflow_state` is called once with the session id and the serialized state.

Then test `run_turn_postprocessing` (non-finalizing path only — the finalizing path's behavior is changing in Plan 002): with `append_conversation_turn` patched, calling it with `user_text`/`assistant_text` schedules a persistence call (patch `asyncio.get_running_loop` or assert via the patched function after letting the executor run; simplest: patch `chat_turn.append_conversation_turn` and run the coroutine inside `asyncio.run`, then assert the mock was called — `run_in_executor(None, ...)` with the default executor will execute the mock; allow a small `await asyncio.sleep(0)` loop if needed).

**Verify**: `.\.venv\Scripts\python.exe -m pytest tests/test_chat_turn.py -v` → all pass.

### Step 4: Firestore writer characterization — `backend/tests/test_firestore_writer.py`

Patch `firestore.writer._client` to return a `MagicMock` whose `collection(...).document(...)` returns a mock doc ref. Cases:

1. `set_finalization_pending(sid)` → doc ref `.set()` called with a dict containing `"finalization_status": "pending"` and `merge=True`.
2. `upsert_final_analysis(sid, {...})` → `.set()` payload contains `"finalization_status": "complete"` and a JSON string under `"final_analysis_json"` that round-trips via `json.loads`.
3. `get_final_analysis`: (a) snapshot `.exists` False → `None`; (b) status `"pending"` → `{"finalization_status": "pending"}`; (c) status `"complete"` with valid `final_analysis_json` → parsed dict including `finalization_status == "complete"`; (d) status `"complete"` with *corrupt* JSON → returns the raw data dict (current fallback behavior at lines 750–758). Note: `get_final_analysis` reads snapshots via a helper `_snap` — patch at whatever seam the live code exposes (check `firestore/writer.py` near line 741).
4. `upsert_discovery_state` and `append_conversation_turn`: assert `.set(..., merge=True)` / the actual write call shape — read the live function bodies first and assert what they do today.

**Verify**: `.\.venv\Scripts\python.exe -m pytest tests/test_firestore_writer.py -v` → all pass.

### Step 5: Full suite + lint

**Verify**: from `backend/`: `.\.venv\Scripts\python.exe -m pytest tests -v` → exit 0, baseline count + your new tests (expect ≥ 25 new). From repo root: `pre-commit run --all-files` → exit 0 (locally-unavailable hooks may skip).

## Test plan

This plan *is* the test plan — see Steps 2–4. Structural pattern: `backend/tests/test_one_field_workflow.py` (plain functions, direct state construction) and `backend/tests/conftest.py` for the stubbing approach.

## Done criteria

- [ ] `backend/tests/test_workflow_state.py`, `test_chat_turn.py`, `test_firestore_writer.py` exist
- [ ] `.\.venv\Scripts\python.exe -m pytest tests -v` (from `backend/`) exits 0 with ≥ 25 new tests
- [ ] No production file modified (`git status` shows only the three new test files + `plans/README.md`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The drift check shows `chat_turn.py`, `workflow_state.py`, or `firestore/writer.py` changed since `effe765` and the excerpts above no longer match.
- Your tests require modifying `backend/tests/conftest.py` or any production module.
- The fire-and-forget pattern in `run_turn_postprocessing` makes the Step 3 persistence assertion flaky after two honest attempts — report which assertion is flaky; Plan 002 makes these writes awaitable, so the test can be deferred to that plan.
- `pytest-asyncio` is needed but not installed and the `asyncio.run` fallback doesn't work for some test.

## Maintenance notes

- Plan 002 changes `run_turn_postprocessing` (awaited writes + finalizer guard) — its executor will extend `test_chat_turn.py`; keep the non-finalizing tests independent of write-scheduling details where possible.
- If `field_schema.py` gains/renames fields, the FSM tests that reference concrete keys (`use_case_title`, `department`, `requester`) need updating — prefer reading keys from `FIELD_SCHEMA` where the specific key doesn't matter.
- Reviewer focus: are the characterization assertions describing behavior we *want* to keep, or accidentally freezing a bug? Flag anything suspicious in the PR description rather than changing production code.
