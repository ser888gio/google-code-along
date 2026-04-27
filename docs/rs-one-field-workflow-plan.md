# RS One-Field Discovery Workflow Plan

This plan upgrades the Requirements Specification discovery chat so the
assistant asks exactly one field question per turn, while the backend owns the
field cursor and prevents unanswered fields from being silently skipped.

## Context

Today the orchestrator can ask 1-2, and sometimes 3, field questions in one
assistant message. When the user answers only the last question, the earlier
question can be lost in conversation history. The LLM sees that the topic moved
forward and may never return to the unanswered field.

User feedback:

> Neodpovedela jsem na otazky a uz se k nim nevratil.
> Povazuji za vhodnejsi neretezit otazky = vzdy jen jedna.

Required behavior:

- Ask exactly one field question per assistant turn.
- Advance only when that field receives an answer, an explicit deferral, or an
  accepted not-applicable decision.
- Treat answers like `nevim`, `I don't know`, `TBD`, or `doplnim pozdeji` as
  valid deferrals, not as field values.
- Handle clarification questions without looping.
- Still extract extra fields the user volunteers proactively.
- Revisit deferred and still-missing fields in an explicit wrap-up phase before
  finalization.

## Core Decision

The backend owns the active field cursor. The LLM does not decide which field is
currently being solved.

The backend flow is:

1. Pick `active_field` deterministically from workflow state and field priority.
2. Tell the LLM: ask exactly this field.
3. Persist that same `active_field` before or with the assistant turn.
4. On the next user turn, classify the reply against that persisted field.

This removes the fragile "what did the LLM just ask?" problem. There is no need
to infer the asked field from assistant text, no `missing_priority[0]` guess, and
no JSON envelope is required for correctness.

## Out Of Scope

The user will define answer-quality criteria in a later phase. This phase only
adds a non-blocking rating seam. Advancement is controlled by classification and
extraction, not by a final quality rubric.

## Persisted State

Add workflow state to Firestore separately from existing extracted and direct
field state.

Existing concepts:

- `discovery_state_json`: AI-extracted RS field values.
- `direct_fields_json`: user-entered deterministic fields from the right panel.

New concepts:

- `workflow_state_json`: cursor, per-field status, phase, miss counts.
- `deferred_fields_json`: all deferred fields, not only direct fields.

Example `workflow_state_json`:

```json
{
  "phase": "discovery",
  "active_field": "product_owner",
  "field_status": {
    "use_case_title": "answered",
    "department": "answered",
    "requestor": "answered",
    "product_owner": "missing"
  },
  "clarification_counts": {
    "product_owner": 0
  },
  "miss_counts": {
    "product_owner": 0
  },
  "last_question_by_field": {
    "product_owner": "Kdo je Product Owner?"
  }
}
```

Allowed phases:

- `discovery`
- `wrap_up`
- `ready_to_finalize`
- `finalizing`
- `complete`

Allowed field statuses:

- `missing`
- `answered`
- `deferred`
- `clarification_requested`
- `not_applicable`

Example `deferred_fields_json`:

```json
{
  "saved_time_hours_per_year": {
    "deferred_at": "2026-04-27T10:32:11Z"
  },
  "risk_avoidance": {
    "deferred_at": "2026-04-27T10:35:02Z"
  }
}
```

## Field Ownership

The backend controller decides `active_field`. The LLM only phrases:

- the question for that active field
- clarification explanations
- short acknowledgements of proactive extra information
- wrap-up summaries

The LLM must not choose a different next field, skip the active field, or bundle
multiple field questions.

## Per-Turn Backend Flow

This ordering is important. Classification and extraction must happen before the
augmented user message is built for the LLM.

For each user message:

1. Load `workflow_state_json`, `discovery_state_json`, `direct_fields_json`, and
   `deferred_fields_json`.
2. Read previous `active_field` from workflow state. This is the field the
   assistant was solving last turn.
3. Classify the user's reply against previous `active_field`:
   - `answered`
   - `deferred`
   - `clarification_requested`
   - `not_answered`
4. Extract proactively supplied fields across all 22 fields.
5. Reconcile workflow state.
6. Pick the next `active_field`.
7. Persist the newly chosen `active_field` before or with the assistant turn, so
   refreshes or interrupted streams do not lose the cursor.
8. Build hidden workflow context with the new `active_field`.
9. Stream the assistant response through the existing ADK runner.
10. Persist conversation turn, extraction output, workflow state, and deferrals.

### Reconciliation Rules

For the previous active field:

- `answered`: store the value, mark `answered`, clear miss count.
- `deferred`: do not store the reply as a value, mark `deferred`, write to
  `deferred_fields_json`, clear miss count.
- `clarification_requested`: keep the same field active, increment
  `clarification_counts`, instruct the LLM to explain and re-ask.
- `not_answered`: keep the same field active, increment `miss_counts`; after 2
  misses, instruct the LLM to offer to mark it unknown.

For proactively extracted fields:

- Mark confident extracted fields as `answered`.
- Skip them later in `pick_next_active_field`.
- If the proactive field is already deferred, remove it from
  `deferred_fields_json` once a real value is provided.

If no required or optional field remains `missing`, set:

```json
{
  "phase": "wrap_up",
  "active_field": null
}
```

## Backend Ordering Fix

In `backend/main.py`, `/chat/stream` currently builds `user_content` before the
pre-stream extractor runs inside `event_generator`. For this workflow, the
controller must run before `user_content` is constructed.

Recommended change:

- Move workflow load, classification, proactive extraction, reconciliation, next
  field selection, and context building above `user_content = types.Content(...)`
  in both `/chat` and `/chat/stream`.
- Keep existing `field_update` SSE events before the assistant text starts
  streaming.
- Add an optional `active_field` SSE event for frontend highlighting.

## Active-Field Classifier

Add `backend/answer_classifier.py`.

Suggested return type:

```python
class ClassifierResult(TypedDict):
    classification: Literal[
        "answered",
        "deferred",
        "clarification_requested",
        "not_answered",
    ]
    value: str | None
    confidence: float
    proactive_fields: dict[str, dict]
```

### Deterministic Fast Paths

Use these before any LLM call:

- Deferral phrases, matched diacritic-insensitively:
  - `nevim`
  - `netusim`
  - `neznam`
  - `zjistim pozdeji`
  - `doplnim pozdeji`
  - `preskocit`
  - `ted nevim`
  - `zatim neni jasne`
  - `to je zatim jedno`
  - `nemame urceno`
  - `I don't know`
  - `not sure`
  - `TBD`
  - `unknown`
  - `n/a`
- Direct-field plausible answer:
  - only for direct fields
  - short
  - no question mark
  - no newline
  - cleaned value is non-empty
- Short question-like reply:
  - catches common clarification requests like `Co tim myslite?`
  - if it ends with `?` and has no field-shaped content, classify as
    `clarification_requested`

### LLM Fallback

For ambiguous replies, use one small structured Gemini Flash call. It should
classify the active field and extract proactive fields in one pass to avoid two
foreground LLM calls.

Example output:

```json
{
  "active_field_result": {
    "field": "department",
    "classification": "answered",
    "value": "HR",
    "confidence": 0.95
  },
  "proactive_fields": {
    "requestor": {
      "filled": true,
      "value": "Jan Novak",
      "confidence": 0.92
    }
  },
  "clarification_answer_needed": false
}
```

`confidence` is logged only in this phase.

### Mixed Clarification And Answer

The classifier must handle mixed intent.

Example:

```text
Product Owner znamena vlastnik? Pak asi Jana.
```

Expected behavior:

- If the value is clear, classify as `answered`.
- The assistant can still briefly confirm the meaning in its acknowledgement.
- Do not stay in `clarification_requested` if a confident value was provided.

## Proactive Over-Answers

The assistant asks one field at a time. The extractor still listens across all
22 fields.

Example:

```text
Assistant: Pro jake oddeleni to je?
User: Je to pro HR a requestor je Jan Novak.
```

Expected result:

- `department = HR`
- `requestor = Jan Novak`
- both fields are marked `answered`
- the workflow skips `requestor` later
- the assistant asks the next still-missing field

This keeps the conversation natural without allowing the assistant to bundle
questions.

## LLM Call Budget

Avoid two foreground LLM calls per turn where possible.

Recommended split:

- Foreground path:
  - deterministic fast paths
  - one small classifier/proactive-extraction Flash call only when needed
- Background path:
  - existing full `extract_discovery_fields` run for panel completeness and
    persisted full-state extraction

The full extractor should not block the assistant response unless the workflow
controller needs it for the current turn.

## Not-Applicable Rules

`not_applicable` must be controlled by field rules, not accepted for every field.

Suggested initial policy:

- Allow `not_applicable` for optional or situational fields:
  - `cost_saving`
  - `revenue_increase`
  - `risk_avoidance`
  - `comments`
  - `attachments`
- Treat `not_applicable` on core required fields as `deferred` unless the product
  owner later defines exceptions.

This prevents `not_applicable` from becoming an accidental skip path for required
data.

## Direct Fields

Keep frontend immediate filling for migration:

- `use_case_title`
- `department`
- `requestor`
- `product_owner`
- `saved_time_hours_per_year`
- `cost_saving`
- `revenue_increase`
- `comments`
- `attachments`

However, backend workflow state is canonical. Long term, the frontend should
optimistically fill direct values, while the backend confirms status and cursor
movement.

## Prompt Changes

Update `ORCHESTRATOR_SYSTEM_PROMPT`:

- Replace "Ask 1-2 focused questions" with "Ask exactly one field question per
  turn."
- Prohibit compound question chains and "and also..." tails.
- Tell the agent the backend provides the active field.
- Tell the agent to ask only about that field and not pick another.
- Tell the agent to acknowledge proactive extra information without asking for
  it again.
- Tell the agent to answer clarification requests and re-ask the same field in
  clearer wording.
- Tell the agent to offer an unknown/later option after repeated misses.
- Keep the existing language rule.
- Keep `[FINALIZING]` as the finalization signal.

Example hidden context:

```text
Workflow context:
- Phase: discovery
- Active field: Product Owner
- Ask exactly one question about this field.
- The user just asked for clarification. Explain Product Owner briefly, then ask again.
- Already answered, do not re-ask:
  - Customer Department: HR
  - Requestor: Jan Novak
- Deferred, do not ask now; revisit at wrap-up:
  - Saved Time (hours/year)

User message:
Co znamena Product Owner?
```

If `miss_counts[active_field] >= 2`, add:

```text
- The user has missed this field 2 times. Offer to mark it unknown or fill it later.
```

## Wrap-Up Phase

When no fields remain `missing`, set `phase = wrap_up` and `active_field = null`.

Wrap-up hidden context:

```text
Workflow context:
- Phase: wrap_up
- Required fields are all answered, deferred, or not applicable.
- Do not ask ordinary discovery questions.
- Summarize what was captured in one short paragraph.
- List deferred or unknown fields explicitly:
  - Saved Time (hours/year)
  - Risk Avoidance
- Ask whether the user wants to fill any of them now, or finalize with them as open questions.
```

User choices:

- If the user fills deferred values, update those fields, remove them from
  `deferred_fields_json`, and continue.
- If the user wants to fill one specific deferred field, set phase back to
  `discovery` and make that field active.
- If the user says to finalize, set `phase = ready_to_finalize`; the next
  assistant response emits `[FINALIZING]`.

Update `FINALIZER_SYSTEM_PROMPT`:

- Deferred fields must be written as `unknown`, `TBD`, or listed under
  `open_questions`.
- Never fabricate values for deferred fields.

Special case for `use_case_title`:

- If deferred earlier, the wrap-up assistant may suggest an English title from
  gathered context.
- The user should confirm or edit it before it becomes `answered`.

## Answer-Quality Hook

Add `backend/answer_quality.py`.

```python
async def rate_answer(
    field_key: str,
    question: str,
    answer: str,
    classification: str,
) -> dict:
    """Return {'verdict': 'accepted' | 'needs_followup' | 'deferred', 'reason': str}.

    Phase 1 stub: maps classifier output directly and logs only.
    This does not gate workflow advancement yet.
    """
```

Later, replace the stub with a field-specific LLM rubric when the answer-quality
criteria are defined.

## Critical Files

- `backend/prompts/agent.py`
  - one-question rule
  - active-field instruction
  - clarification and miss-count behavior
  - finalizer deferred-field behavior
- `backend/main.py`
  - reorder `/chat` and `/chat/stream`
  - load workflow state
  - classify, extract, reconcile, choose active field
  - build hidden workflow context before `user_content`
  - emit optional `active_field` SSE
- `backend/direct_field_context.py`
  - extend `build_augmented_user_message`
  - render workflow context blocks
- `backend/firestore/writer.py`
  - `get_workflow_state`
  - `upsert_workflow_state`
  - `initialize_workflow_state`
  - `get_deferred_fields`
  - `upsert_deferred_fields`
- `backend/agent/discovery_agent.py`
  - export `FIELD_LABELS`
  - add deterministic `pick_next_active_field`
- `backend/answer_classifier.py`
  - deterministic fast paths
  - Flash fallback
- `backend/answer_quality.py`
  - log-only rating seam
- `backend/prompts/context.py`
  - `ACTIVE_FIELD_CLASSIFIER_PROMPT`
- `frontend/app/page.tsx`
  - keep direct-field optimistic fill
  - consume optional `active_field` SSE for highlighting

## Reused Pieces

Do not replace these; extend them:

- `build_augmented_user_message` in `backend/direct_field_context.py`
- `extract_discovery_fields` in `backend/agent/discovery_agent.py`
- `merge_direct_fields` in `backend/direct_field_context.py`
- frontend deferral patterns from `DEFERRED_DIRECT_ANSWER_PATTERNS`
- pre-stream SSE path in `backend/main.py`
- `FIELD_SCHEMA` in `backend/agent/discovery_agent.py`

## Implementation Order

1. Add workflow-state and deferred-field Firestore helpers.
2. Add `FIELD_LABELS` and deterministic `pick_next_active_field`.
3. Add `answer_classifier.py` with deterministic fast paths.
4. Add `ACTIVE_FIELD_CLASSIFIER_PROMPT` and fallback classification.
5. Extend `build_augmented_user_message` with workflow context.
6. Update orchestrator and finalizer prompts.
7. Reorder `/chat` and `/chat/stream` so workflow control happens before
   `user_content` is built.
8. Reconcile field statuses and persist the active field before or with the
   assistant turn.
9. Add wrap-up phase handling.
10. Add answer-quality stub logging.
11. Add optional frontend active-field highlighting.
12. Add tests.

## Verification

Manual bug repro:

1. Start backend and frontend.
2. Start a new session.
3. Confirm greeting asks exactly one field question.
4. If assistant asks for title, reply: `Je to pro HR`.
5. Confirm `department = HR` is captured proactively.
6. Confirm title remains active and is asked again.
7. Reply: `nevim`.
8. Confirm title is deferred, no fake value is stored, and the assistant moves to
   the next field.
9. Reply to a Product Owner question with: `Co znamena Product Owner?`
10. Confirm the assistant explains and re-asks Product Owner.
11. Ignore a field twice.
12. Confirm the assistant offers to mark it unknown or fill it later.
13. Continue until all fields are answered, deferred, or not applicable.
14. Confirm wrap-up lists deferred fields.
15. Choose finalize.
16. Confirm final analysis lists deferred fields as open questions and does not
    invent values.

Firestore inspection:

- `workflow_state_json` updates every turn.
- `active_field` matches the field the assistant is asking.
- `deferred_fields_json` contains deferred fields.
- `discovery_state_json` and `direct_fields_json` continue to work.

Automated tests:

- `pick_next_active_field` required-field priority.
- optional-field priority after required fields.
- returns `None` when nothing is missing.
- deferral regex in Czech and English, diacritic-insensitive.
- clarification question heuristic.
- `build_augmented_user_message` discovery context.
- `build_augmented_user_message` wrap-up context.
- reconciliation for all four classifications.
- mixed clarification plus answer.
- not-applicable allowed and disallowed fields.
- mocked integration flow covering answer, deferral, clarification, not-answered,
  proactive extraction, and wrap-up.

## Success Criteria

- The assistant never bundles unrelated field questions.
- A field cannot be silently skipped because the user ignored it once.
- Clarification requests do not create repeat loops.
- Proactively provided future answers are captured and skipped later.
- Deferred fields persist across refreshes and mode changes.
- Wrap-up explicitly lists unknown/deferred fields.
- Final output distinguishes confirmed values from unknown or deferred values.
