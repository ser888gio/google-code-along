# How Conversation Context Works (Text & Voice)

This document explains how the RS Generator feeds **memory/context** to the agent
so it knows which fields are already filled, which one to ask next, and never
re-asks for information the user has already provided — in both **text** and
**voice** mode.

---

## The core idea

The backend owns a small amount of **workflow state** per session (what's
answered, what's deferred, which field is "active"). On every turn it renders
this into a **hidden context block** and prepends it to the user's message before
the LLM sees it. The agent's system prompt is written to treat this block as
authoritative:

> "The backend sends a hidden Workflow context block in each user message. It
> tells you the current phase and the single active field. You must follow it."
> — [`backend/prompts/agent.py`](../backend/prompts/agent.py)

So the agent never has to "remember" field state on its own — the backend hands
it the clipboard on every turn.

---

## Where field state lives

State is persisted in **Firestore** (collection `srs_sessions`, document =
`session_id`) across four independent JSON blobs, all written with `merge=True`
so they never clobber each other:

| Blob | Holds | Written by |
|---|---|---|
| `direct_fields_json` | Values the user **typed into the form** (source = "user") | `upsert_direct_fields` |
| `discovery_state_json` | Values the **AI extracted** from conversation (source = "ai") | `upsert_discovery_state` |
| `deferred_fields_json` | Fields the user chose to **skip for now** | `upsert_deferred_fields` |
| `workflow_state_json` | The backend **cursor**: phase, active field, per-field status | `upsert_workflow_state` |

`get_discovery_state(session_id)` returns a **merged** view: AI-extracted values
with direct (user-typed) values overlaid on top — user values always win.

Field definitions themselves come from a single source of truth:
[`backend/field_schema.py`](../backend/field_schema.py) (22 fields across 6
sections). Never duplicate field definitions elsewhere.

---

## The hidden context block

The renderer is
[`build_augmented_user_message`](../backend/direct_field_context.py) in
`direct_field_context.py`. Given the current state it produces text like:

```
Workflow context:
- Phase: discovery
- Active field: Target Users. Ask exactly one question about this field.
- Already answered, do not re-ask:
  - Use Case Title: Sales Report Automation
  - Product Owner: Jane Doe
- Deferred, do not ask now; revisit at wrap-up:
  - System Requirements

User message:
<the user's actual message>
```

This block is the entire "memory" the agent needs for a turn. Both text and voice
modes use **this same renderer** so they stay consistent — if a field is added or
renamed in `field_schema.py`, both modes pick it up automatically.

---

## Text mode flow (per turn)

Endpoint: `POST /chat/stream` in [`backend/main.py`](../backend/main.py).

```
user sends message
      │
      ▼
load direct_fields + discovery_state + deferred_fields + workflow_state (Firestore)
      │
      ▼
_prepare_workflow_turn()           ← advances the cursor for THIS message:
  • classifies the user's answer to the active field
  • marks fields answered/deferred
  • picks the next active field (pick_next_active_field)
  • persists updated workflow_state  (upsert_workflow_state)
      │
      ▼
build_augmented_user_message(message, ..., workflow_context=...)
      │
      ▼
runner.run_async()  → agent responds, streamed back via SSE
      │
      ▼
post-turn: extract fields, persist conversation + discovery state
```

The key point: **text mode rebuilds and injects the block on every single turn.**

---

## Voice mode flow

Endpoint: `WebSocket /ws/{user_id}/{session_id}`, handled by
[`backend/audio_websocket.py`](../backend/audio_websocket.py). Voice uses the
Gemini Live API and shares the **same `session_id`** and the **same system
prompt** as text mode.

### The problem this design solves

The voice agent is told (by the shared prompt) to expect the hidden context
block — but the Live API conversation is audio-driven, so there's no per-turn
"augmented user message" to attach it to. If voice starts blind, it re-asks for
fields the user already filled in text mode.

### Voice session priming

On WebSocket connect we **prime** the voice session with the same block, once,
as a synthetic history event:

```
voice WebSocket connects
      │
      ▼
_ensure_audio_session()              ← get or create the ADK audio session
      │
      ▼
_prime_audio_session()
  • load_voice_priming(session_id):
        - get_direct_fields(...)
        - build_workflow_context_snapshot(...)   ← READ-ONLY (see below)
        - build_augmented_user_message("", ..., workflow_context=...)
        - returns None if there's no real progress (fresh session)
  • if priming text exists and isn't already the latest priming event:
        append it as a synthetic "user" Event tagged [VOICE_PRIMING]
      │
      ▼
audio_runner.run_live()              ← agent now sees the block in history
```

Two deliberate design choices:

1. **Appended to history, NOT pushed through the live request queue.**
   Sending it through `live_request_queue.send_content(...)` would look like an
   (empty) user message and could make the agent start talking on connect.
   Appending it as a history event means the agent simply *sees* the context on
   its next real (spoken) turn.

2. **`build_workflow_context_snapshot` is read-only.**
   Unlike `_prepare_workflow_turn`, it performs **no classification and no
   `upsert_*`**. There's no pending message to classify at connect time, and a
   voice connect must never mutate the cursor the text turn owns. It only *reads*
   current state and computes the block.

### Idempotency

Each priming event is tagged with a `[VOICE_PRIMING]` marker. Before appending,
`_prime_audio_session` scans history for the latest priming event and **skips** if
the text is unchanged. This prevents duplicate hidden blocks from accumulating
when the user toggles text↔voice repeatedly.

---

## The reverse direction: SessionBridge

[`backend/session_bridge.py`](../backend/session_bridge.py) handles the *other*
direction. After each completed voice turn, it injects the voice transcripts
(user + assistant) into the text orchestrator's ADK session as synthetic
`Content` events. This way, when the user switches **back** to text mode, the
text agent has full conversational context of what was said in voice.

- **Priming** = give voice the current text/form memory *before* it speaks.
- **SessionBridge** = give text the voice transcripts *after* a voice turn.

They're complementary and operate independently.

---

## The frontend race guard

Even with correct backend priming, switching to voice **mid-completion** could
read stale state if the in-flight text turn or debounced field PATCHes hadn't
landed yet. So when turning voice **on**, the frontend
([`frontend/app/page.tsx`](../frontend/app/page.tsx)):

1. **Blocks the toggle while `isStreaming`** (button is `disabled`), so voice
   can't start until the text turn settles.
2. **Flushes pending field PATCHes** via `rsState.flushPendingPatches()` before
   connecting, so manually-typed fields are persisted to Firestore first.

Turning voice **off** stays immediate.

---

## Quick reference

| Concern | Function | File |
|---|---|---|
| Render the hidden block | `build_augmented_user_message` | `direct_field_context.py` |
| Advance cursor for a text turn (mutating) | `_prepare_workflow_turn` | `main.py` |
| Read-only context snapshot (for voice) | `build_workflow_context_snapshot` | `main.py` |
| Build voice priming text | `load_voice_priming` | `main.py` |
| Inject priming into voice session | `_prime_audio_session` | `audio_websocket.py` |
| Pick next field to ask | `pick_next_active_field` | `agent/discovery_agent.py` |
| Bridge voice → text history | `SessionBridge.inject_voice_turn` | `session_bridge.py` |
| Merged field view | `get_discovery_state` | `firestore/writer.py` |
| Field source of truth | — | `field_schema.py` |
