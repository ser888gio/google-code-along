# RS Live Template Field Strategy

This document describes how the application fills the `RsLiveTemplate` form during
a discovery chat. The main idea is that not every field should require an LLM
call. Some fields are simple factual values and can be written directly, while
others benefit from LLM extraction, summarization, and rewriting.

## Field Categories

### Direct Fields

Direct fields are simple factual values that the user can provide as-is. When the
assistant asks for one of these fields and the user gives a short concrete answer,
the frontend writes the value into the form immediately.

Current direct/suggestable fields:

- `use_case_title`
- `department`
- `requestor`
- `product_owner`

Additional direct-only fields, typed in the right panel:

- `saved_time_hours_per_year`
- `cost_saving`
- `revenue_increase`
- `comments`
- `attachments`

Example:

```text
Assistant: Kdo je Product Owner?
User: Ales Priklad
```

The UI immediately fills:

```json
{
  "product_owner": "Ales Priklad"
}
```

This does not wait for `/context/extract` or an LLM extraction pass.

### LLM-Extracted Fields

LLM-extracted fields are narrative or analytical. The user may answer them in
messy natural language, and the system should turn that answer into a concise,
structured requirements value.

Examples:

- `process_as_is`
- `process_context`
- `trigger`
- `purpose_to_be`
- `impacted_users`
- `add_value`
- `time_criticality`
- `strategic_impact`
- `risk_avoidance`
- `systems_and_tools`
- `document_types`
- `data_security_classification`
- `solution_type`

Example:

```text
User: Dneska to oddeleni dela rucne v Excelu, kazdy patek sbiraji podklady
z mailu a pak to nekdo prepisuje do SAPu.
```

This should go through extraction/summarization so the RS field becomes cleaner,
for example:

```json
{
  "process_as_is": "The current process is manual. The team collects inputs from email each Friday, consolidates them in Excel, and then re-enters the result into SAP."
}
```

## Direct Chat Answer Flow

The frontend tracks whether the assistant just asked for a direct field.

1. The assistant response is streamed into the chat.
2. After the response finishes, the frontend checks whether it asked about a
   known direct field, such as Product Owner.
3. If yes, the frontend stores that field as `pendingDirectChatField`.
4. On the next user message, the frontend classifies the answer:
   - concrete answer: fill the field immediately
   - deferred/unknown answer: do not fill the field
5. The chat request includes the current `direct_fields` so the backend can pass
   them into the orchestrator context.

Relevant implementation:

- `frontend/app/page.tsx`
  - `inferDirectChatFieldFromAssistant`
  - `isDeferredDirectAnswer`
  - `applyDirectChatAnswer`
- `frontend/lib/api.ts`
  - sends `direct_fields`
  - sends `deferred_fields`
- `backend/direct_field_context.py`
  - builds hidden context for the orchestrator

## Deferred Answers

Some user replies mean "I do not know yet" rather than a real value. These must
not be written into the form as if they were the field value.

Examples:

- `Nevim`
- `Netusim`
- `Neznam`
- `Doplnim pozdeji`
- `TBD`
- `Unknown`
- `I don't know`
- `Not sure`

Example:

```text
Assistant: Kdo je Product Owner?
User: Nevim, doplnim pozdeji.
```

The result should be:

```json
{
  "product_owner": null
}
```

The frontend also sends:

```json
{
  "deferred_fields": ["product_owner"]
}
```

The backend converts this into hidden context for the assistant:

```text
The user deferred these fields. Do not ask for them again immediately;
revisit them near finalization if still required:
- Product Owner
```

This lets the conversation move on without incorrectly filling the form or
repeatedly asking the same question.

## Backend Context Injection

Before the backend sends a user message to the orchestrator, it augments the
message with form context.

If direct fields exist:

```text
Context from the Requirements Specification form, entered manually by the user.
Treat these fields as already provided and do not ask for them again:
- Product Owner: Ales Priklad

User message:
...
```

If fields were deferred:

```text
Context from the Requirements Specification form, entered manually by the user.
The user deferred these fields. Do not ask for them again immediately; revisit
them near finalization if still required:
- Product Owner

User message:
...
```

This solves the mismatch where the right-panel form knows a value, but the chat
agent would otherwise only see conversation history and ask for the value again.

## Persistence

Direct fields are persisted separately in Firestore as `direct_fields_json`.
When the discovery state is loaded, direct fields are merged on top of the
AI-extracted state.

This gives direct fields priority:

1. User-entered direct values are preserved.
2. Later AI extraction cannot erase them.
3. The unified discovery state still returns the same shape to the frontend:

```json
{
  "completeness": 42,
  "fields": {
    "product_owner": {
      "filled": true,
      "value": "Ales Priklad"
    }
  }
}
```

## Product Rule Of Thumb

Use deterministic direct filling when the answer is:

- short
- factual
- safe to store exactly as written
- tied to a specific form field

Use LLM extraction when the answer needs:

- summarization
- rewriting
- interpretation
- mapping across multiple fields
- validation against the broader conversation

Do not store deferrals as values. Treat them as "known missing for now" and
revisit later only if the field is still required.
