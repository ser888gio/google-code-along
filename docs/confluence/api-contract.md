# API Contract

## Overview

The frontend talks to the FastAPI backend through HTTP, Server-Sent Events, and a bidirectional WebSocket.

Base URLs:

| Context | Default |
|---|---|
| HTTP API | `http://localhost:8080` |
| WebSocket API | `ws://localhost:8080` |
| Frontend dev server | `http://localhost:3000` |

The frontend uses these environment variables:

```text
NEXT_PUBLIC_API_URL=http://localhost:8080
NEXT_PUBLIC_WS_URL=ws://localhost:8080
```

Unless noted otherwise, JSON endpoints use:

```text
Content-Type: application/json
```

Error responses generally use FastAPI's standard shape:

```json
{
  "detail": "Human readable error"
}
```

---

## Authentication

Most user-facing endpoints are not authenticated by the app itself. They rely on deployment-level controls, CORS, and GCP runtime identity for backend access to Firestore/GCS.

---

## Core Types

### `ChatRequest`

Used by `POST /chat` and `POST /chat/stream`.

```json
{
  "message": "We need an automated sales report.",
  "session_id": "optional-existing-session-id",
  "user_id": "default_user",
  "direct_fields": {
    "solution_name": "Sales Report Automation"
  },
  "deferred_fields": ["acceptance_criteria"]
}
```

Fields:

| Field | Required | Description |
|---|---:|---|
| `message` | Yes | User's latest message. |
| `session_id` | No | Existing session ID. Backend generates a UUID when omitted. |
| `user_id` | No | ADK user ID. Defaults to `default_user`. |
| `direct_fields` | No | Manual field values from the live RS panel. Stored separately so extraction does not erase them. |
| `deferred_fields` | No | Field keys the user wants to answer later. |

### `ContextResponse`

Used by discovery/extraction endpoints.

```json
{
  "completeness": 42,
  "fields": {
    "business_problem": {
      "filled": true,
      "value": "Manual reporting takes two days each month."
    },
    "acceptance_criteria": {
      "filled": false,
      "value": null
    }
  }
}
```

`fields` is keyed by canonical field key from `backend/field_schema.py`.

### `SessionRef`

Used by document and diagram endpoints.

```json
{
  "session_id": "session-uuid",
  "user_id": "default_user"
}
```

---

## Health

### `GET /health`

Checks that the backend process is serving traffic.

Response:

```json
{
  "status": "ok"
}
```

---

## Chat

### `POST /chat`

Non-streaming chat endpoint. The frontend primarily uses `/chat/stream`, but this endpoint is useful for tests and simple clients.

Request:

```json
{
  "message": "I need a dashboard for monthly sales.",
  "session_id": null,
  "user_id": "default_user"
}
```

Response:

```json
{
  "reply": "Thanks. Let's start with the current reporting process...",
  "session_id": "generated-or-existing-session-id",
  "message_id": "assistant-message-id"
}
```

Notes:

- Runs the same safety preflight and workflow preparation as streaming chat.
- Persists the conversation turn to Firestore in the background.
- If the model emits the finalization marker, the non-streaming path does not expose a separate `finalizing` event to the client.

### `POST /chat/stream`

Primary text-chat endpoint. Returns `text/event-stream`.

Request:

```json
{
  "message": "The report should be emailed every Monday morning.",
  "session_id": "session-uuid",
  "user_id": "default_user",
  "direct_fields": {
    "report_frequency": "Weekly, every Monday morning"
  }
}
```

SSE event format:

```text
data: {"session_id":"session-uuid","message_id":"assistant-message-id"}

data: {"active_field":"target_users"}

data: {"field_update":{"key":"report_frequency","value":"Weekly, every Monday morning"}}

data: {"text":"Great, weekly Monday delivery is clear."}

data: {"event":"finalizing"}

data: [DONE]
```

Possible SSE payloads:

| Payload | Meaning |
|---|---|
| `{"session_id": "..."}` | Session was created or confirmed. Usually first event. |
| `{"message_id": "..."}` | ID for the assistant message, used for feedback. |
| `{"active_field": "..."}` | Backend workflow field the assistant is currently asking about. |
| `{"field_update": {"key": "...", "value": "..."}}` | Pre-stream extraction found a changed field value. |
| `{"text": "..."}` | Assistant text chunk. Append to the active assistant bubble. |
| `{"event": "finalizing"}` | Finalizer pipeline has been triggered. Start polling `/analyses/{session_id}`. |
| `{"error": "..."}` | Stream-level error. Show the message and stop the stream. |
| `[DONE]` | Stream is complete. |
| `: keepalive` | SSE comment to keep the connection open. Ignore in the client UI. |

Safety/cost behavior:

- Unsafe prompts produce an SSE error with a friendly message.
- Cost circuit breaker produces an SSE error and ends the stream.
- Internal streaming errors produce a generic retry message.

---

## Discovery And Field State

### `POST /context/extract`

Runs discovery extraction for the current session and persists the result to Firestore.

Request:

```json
{
  "session_id": "session-uuid",
  "user_id": "default_user"
}
```

Response:

```json
{
  "completeness": 65,
  "fields": {
    "context": {
      "filled": true,
      "value": "Monthly sales reporting for regional managers."
    }
  }
}
```

Notes:

- The frontend calls this after each completed chat turn.
- A per-session lock deduplicates concurrent extraction calls.
- If the live ADK session is missing, the backend falls back to saved Firestore discovery state.
- If no saved state exists, the response is `{"completeness":0,"fields":{}}`.

### `GET /discovery/{session_id}`

Returns the last saved merged discovery state.

Response:

```json
{
  "completeness": 65,
  "fields": {
    "solution_name": {
      "filled": true,
      "value": "Sales Report Automation"
    }
  }
}
```

Used when loading historical sessions so the Preview panel can restore state without re-running extraction.

### `PATCH /discovery/{session_id}/fields`

Stores direct manual field values.

Request:

```json
{
  "fields": {
    "solution_name": "Sales Report Automation",
    "attachments": "gs://bucket/sessions/session-uuid/source.csv"
  }
}
```

Response:

```json
{
  "completeness": 70,
  "fields": {
    "solution_name": {
      "filled": true,
      "value": "Sales Report Automation"
    }
  }
}
```

Direct fields are stored separately in Firestore and overlaid onto AI-extracted discovery state.

---

## Uploads

### `POST /upload`

Uploads one file through the backend to GCS.

Content type:

```text
multipart/form-data
```

Form fields:

| Field | Required | Description |
|---|---:|---|
| `file` | Yes | File content. |
| `session_id` | Yes | Session folder under `sessions/{session_id}/`. |

Response:

```json
{
  "gcs_path": "gs://bucket/sessions/session-uuid/source.csv",
  "filename": "source.csv"
}
```

Rules:

- Maximum upload size is 10 MB.
- Session ID and filename are sanitized before writing to GCS.
- The frontend uploads via `XMLHttpRequest` to report progress.

### `GET /uploads/{session_id}`

Lists uploaded files for a session.

Response:

```json
{
  "session_id": "session-uuid",
  "files": [
    {
      "filename": "source.csv",
      "gcs_path": "gs://bucket/sessions/session-uuid/source.csv"
    }
  ]
}
```

---

## Documents

### `POST /document`

Legacy readiness endpoint for generated RS markdown.

Request:

```json
{
  "session_id": "session-uuid",
  "user_id": "default_user"
}
```

Response when ready:

```json
{
  "ready": true,
  "markdown": "# Requirement Specification\n..."
}
```

Response when not ready:

```json
{
  "ready": false,
  "markdown": null
}
```

This path depends on the legacy `[GENERATE_RS]` marker in live ADK session events.

### `POST /document/pdf`

Returns a generated PDF as a binary response.

Response headers:

```text
Content-Type: application/pdf
Content-Disposition: attachment; filename=requirement_specification.pdf
```

Errors:

- `404`: no legacy RS document found in the live ADK session.

### `POST /document/docx`

Returns a generated SRS DOCX as a binary response.

Response headers:

```text
Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document
Content-Disposition: attachment; filename=requirement_specification.docx
```

Errors:

- `422`: SRS JSON could not be compiled from the conversation.

### `POST /document/rs-template/docx`

Generates the RS-template DOCX from current discovery fields, saves it to GCS, and returns the DOCX bytes.

Response headers:

```text
Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document
Content-Disposition: attachment; filename=rs_template.docx
X-GCS-Path: gs://bucket/sessions/session-uuid/rs_template.docx
```

This is the main download path used by the live RS Preview.

---

## Diagrams

### `POST /bpmn/generate`

Checks whether the conversation is ready for BPMN generation and returns Mermaid syntax when ready.

Request:

```json
{
  "session_id": "session-uuid",
  "user_id": "default_user"
}
```

Response when ready:

```json
{
  "ready": true,
  "mermaid": "flowchart TD\n  A[Start] --> B[Validate data]",
  "score": 92,
  "missing": null
}
```

Response when not ready:

```json
{
  "ready": false,
  "mermaid": null,
  "score": 72,
  "missing": ["process trigger", "exception path"]
}
```

Rules:

- Requires a live ADK session.
- Readiness score must be at least 90.
- Returns `404` if the live ADK session is not found.

### `POST /dataflow/generate`

Checks whether the conversation is ready for Data Flow Diagram generation and returns Mermaid syntax when ready.

Rules:

- Requires a live ADK session.
- Readiness score must be at least 70.
- Returns `404` if the live ADK session is not found.

Response shape matches `/bpmn/generate`.

---

## Feedback

### `POST /feedback`

Stores thumbs-up or thumbs-down feedback for an assistant message.

Request:

```json
{
  "session_id": "session-uuid",
  "message_id": "assistant-message-id",
  "vote": "down",
  "comment": "It asked for the same thing twice."
}
```

Response:

```json
{
  "status": "ok"
}
```

Errors:

- `400`: invalid vote or payload.
- `404`: assistant message was not found.

### `PATCH /feedback/{message_id}`

Adds or replaces the comment for existing message feedback.

Request:

```json
{
  "session_id": "session-uuid",
  "comment": "The answer was useful after the second paragraph."
}
```

Response:

```json
{
  "status": "ok"
}
```

### `POST /feedback/session`

Stores overall session feedback and records the session as ended/abandoned unless finalization already recorded completion.

Request:

```json
{
  "session_id": "session-uuid",
  "rating": 4,
  "comment": "Good structure, a little long."
}
```

Response:

```json
{
  "status": "ok"
}
```

---

## Sessions And History

### `GET /sessions`

Returns stored session summaries.

Response:

```json
[
  {
    "session_id": "session-uuid",
    "updated_at": "2026-05-14T12:00:00Z",
    "preview": "We need an automated sales report..."
  }
]
```

### `GET /history/{session_id}`

Returns persisted conversation history.

Response:

```json
{
  "session_id": "session-uuid",
  "messages": [
    {
      "message_id": "assistant-message-id",
      "role": "assistant",
      "text": "Let's define the business problem.",
      "ts": "2026-05-14T12:00:00Z"
    }
  ]
}
```

---

## Final Analysis

### `GET /analyses/{session_id}`

Frontend polling endpoint after a `finalizing` event.

Response before finalization:

```json
{
  "status": "not_found"
}
```

Response while running:

```json
{
  "status": "pending"
}
```

Response on failure:

```json
{
  "status": "error"
}
```

Response when complete:

```json
{
  "status": "complete",
  "analysis": {
    "use_case_form": {},
    "technology_recommendation": {
      "primary": "Example",
      "rationale": "Example rationale",
      "alternatives": [],
      "constraints": []
    },
    "team_profile": {
      "recommended_team_type": "internal",
      "skills_required": [],
      "rationale": "Example rationale"
    },
    "priority_tier": {
      "tier": "tactical",
      "score": 75,
      "scoring_rationale": "Example rationale",
      "priority_drivers": []
    },
    "risk_and_dependencies": {
      "risks": [],
      "dependencies": [],
      "open_questions": []
    },
    "_meta": {
      "session_id": "session-uuid",
      "finalized_at": "2026-05-14T12:00:00Z",
      "model": "gemini-3.1-pro-preview",
      "discovery_completeness": 90
    }
  }
}
```

---

## Firestore SRS Data

### `GET /firestore/data/{session_id}`

Returns the latest compiled SRS snapshot fields stored in Firestore.

Response:

```json
{
  "session_id": "session-uuid",
  "data": {
    "session_id": "session-uuid",
    "updated_at": "2026-05-14T12:00:00Z",
    "s1_context": "Monthly reporting process...",
    "s1_business_problem": "Manual work causes delays..."
  }
}
```

If no SRS snapshot has been written:

```json
{
  "session_id": "session-uuid",
  "data": null
}
```

---

## Voice WebSocket

### `WS /ws/{user_id}/{session_id}`

Bidirectional voice endpoint used by voice mode.

Client to server:

| Frame type | Shape | Meaning |
|---|---|---|
| Binary | Raw PCM | 16 kHz, 16-bit, mono audio from browser microphone. |
| Text JSON | `{"type":"text","text":"..."}` | Text fallback injected into the Gemini Live request queue. |

Server to client:

| Frame type | Shape | Meaning |
|---|---|---|
| Binary | Raw PCM | Assistant audio, expected by frontend player as 24 kHz PCM. |
| Text JSON | `{"type":"user_transcript_partial","text":"..."}` | Live user caption chunk. |
| Text JSON | `{"type":"user_transcript","text":"..."}` | Final user transcript for the turn. |
| Text JSON | `{"type":"text","text":"..."}` | Assistant text transcript for the turn. |
| Text JSON | `{"type":"turn_complete","finalizing":false}` | Turn complete. Frontend can trigger extraction refresh. |
| Text JSON | `{"type":"error","message":"..."}` | Voice-mode error. |

Notes:

- Voice transcripts are injected into the shared ADK session so text mode can continue with voice context.
- After each voice turn, backend post-processing persists the turn and may trigger finalization.
- The frontend WebSocket hook does not currently implement automatic reconnection or message queuing.

---

## Contract Drift Risks

- Some comments still say 22 fields. The current schema is 28 fields across 6 sections.
- `/document` and `/document/pdf` rely on a legacy marker and live ADK session events.
- Diagram endpoints require a live ADK session, so they can fail after backend restart even when Firestore has saved state.
- Final analysis schema is still mirrored manually in frontend types and should eventually be generated from backend schema.
- Binary document endpoints return blobs, not JSON.
