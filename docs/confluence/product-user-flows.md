# Product And User Flows

## Overview

The RS Generator helps business users turn a rough idea into a structured Requirement Specification. The main product experience is a conversational workspace: the user chats with an AI business consultant while a live RS panel fills in the formal fields needed for documentation, diagrams, and final analysis.

Primary user groups:

| User group | Goal |
|---|---|
| Business user | Explain a need in plain language and receive a structured RS draft. |
| Business analyst / consultant | Guide or review the discovery conversation and refine the output. |
| Developer / operator | Keep the app running, debug failures, and evolve the workflow. |

---

## Main Workspace

The main page is a two-panel workspace.

Left panel:

- Chat conversation.
- Text input.
- Optional voice mode.
- File upload surface.
- Message feedback controls.

Right panel:

- `Preview`: live RS template fields.
- `BPMN`: process diagram generation.
- `Data`: data-flow diagram generation.
- `Database`: Firestore-backed SRS snapshot.
- `Analysis`: finalizer output.
- `Summary`: document download surface.

The user can work mostly through chat, but direct-input fields in the Preview panel allow manual correction or explicit values for fields where precision matters.

---

## Flow 1: New Text Discovery Session

### Goal

Start from a blank idea and gather enough information to draft a formal Requirement Specification.

### Happy Path

```text
1. User opens the app.
2. Frontend starts with no session ID.
3. User sends the first message.
4. Frontend calls POST /chat/stream with session_id=null.
5. Backend creates a UUID session and ADK session.
6. Backend streams:
   - session_id
   - message_id
   - active_field
   - optional field_update events
   - assistant text chunks
   - [DONE]
7. Frontend stores session_id and renders the assistant message.
8. Frontend calls POST /context/extract.
9. Backend extracts RS field values and persists discovery state.
10. Frontend refreshes the Preview and Database tabs.
11. User continues answering one field at a time.
```

### User Experience Notes

- The assistant should ask focused, business-friendly questions.
- The active field should match what the assistant is currently trying to collect.
- The user does not need to know the RS schema; the Preview panel makes progress visible.
- If the user gives multiple details in one answer, proactive field updates may fill more than the active field.

### Important Edge Cases

| Case | Expected behavior |
|---|---|
| User gives a vague answer | Backend may mark the field as missing or ask a clarification. |
| User asks to answer later | Field becomes deferred and the workflow moves on. |
| User says not applicable | Allowed only for fields where schema permits it; otherwise treated as deferred/missing. |
| Backend restart | Firestore history and discovery state remain, but live ADK session context is lost. |
| Cost circuit trips | User gets a friendly cost-limit message and the turn stops. |
| Unsafe prompt is detected | User gets a friendly refusal/safety message. |

---

## Flow 2: Live RS Preview And Manual Field Editing

### Goal

Let the user see the formal RS taking shape and correct precise values without waiting for AI extraction.

### Happy Path

```text
1. User chats normally.
2. Frontend receives field_update events during streaming or extraction results after the turn.
3. Preview panel marks fields as filled, missing, or editable.
4. User edits a direct-input field.
5. Frontend calls PATCH /discovery/{session_id}/fields.
6. Backend stores the value in direct_fields_json.
7. Backend returns merged discovery state.
8. Preview panel updates completeness immediately.
```

### Field Card Types

| Card type | Meaning |
|---|---|
| Placeholder | Field is not filled yet. |
| Filled | AI extraction found a value. |
| Editable | User can type a direct value that should be preserved. |

### Product Rules

- Direct values override AI-extracted values.
- Direct values survive future extraction runs.
- The RS-template DOCX generation button becomes available when the completeness threshold is met.
- The current threshold in the frontend is 80 percent completeness.

---

## Flow 3: Voice Discovery Session

### Goal

Allow users to complete the same discovery process by speaking with the assistant.

### Happy Path

```text
1. User enables voice mode.
2. If no session exists, frontend creates a UUID locally.
3. Frontend opens WS /ws/{user_id}/{session_id}.
4. Browser captures microphone audio with AudioWorklet.
5. Frontend sends binary PCM frames to the backend.
6. Backend streams audio to Gemini Live through ADK.
7. Backend sends assistant audio frames back to the browser.
8. Backend sends transcript events:
   - user_transcript_partial
   - user_transcript
   - text
   - turn_complete
9. Backend injects the voice turn into the text ADK session.
10. Frontend refreshes extraction and Preview after turn completion.
```

### User Experience Notes

- Voice mode requires microphone permission.
- Voice mode requires HTTPS or localhost.
- The transcript should appear so the user can understand what the system heard.
- Switching back to text should preserve the voice context because transcripts are injected into the shared ADK session.

### Important Edge Cases

| Case | Expected behavior |
|---|---|
| Microphone permission denied | User remains in text mode or sees voice connection failure. |
| WebSocket disconnects | Current hook reports disconnected; it does not auto-reconnect. |
| Gemini Live API error | Backend sends a voice error event and logs details. |
| Finalizer marker appears in voice response | Backend emits `turn_complete` with `finalizing=true` and starts finalizer post-processing. |

---

## Flow 4: File Uploads

### Goal

Attach source material to a session, such as spreadsheets, notes, or examples.

### Happy Path

```text
1. User has an active session.
2. User selects or drags a file into the upload widget.
3. Frontend posts multipart form data to POST /upload.
4. Backend sanitizes session ID and filename.
5. Backend writes file to GCS under sessions/{session_id}/.
6. Frontend receives filename and GCS path.
7. Frontend refreshes GET /uploads/{session_id}.
8. Frontend stores uploaded paths in the attachments direct field.
```

### Product Rules

- A session ID is required before upload.
- Maximum upload size is 10 MB.
- Uploaded files are stored in GCS and listed for the session.
- The current finalizer reads text content from plain text extensions only: `.txt`, `.md`, `.json`, and `.csv`.
- PDF, DOCX, and image uploads are stored and visible but not deeply text-extracted in the current MVP.

---

## Flow 5: Diagram Generation

### Goal

Generate visual process and data-flow diagrams from the conversation.

### BPMN Flow

```text
1. User opens the BPMN tab.
2. User requests generation.
3. Frontend calls POST /bpmn/generate.
4. Backend checks readiness from live ADK session transcript.
5. If score < 90, backend returns missing items.
6. If score >= 90, backend returns Mermaid syntax.
7. Frontend renders Mermaid in an iframe.
```

### Data Flow Diagram Flow

```text
1. User opens the Data tab.
2. User requests generation.
3. Frontend calls POST /dataflow/generate.
4. Backend checks readiness from live ADK session transcript.
5. If score < 70, backend returns missing items.
6. If score >= 70, backend returns Mermaid syntax.
7. Frontend renders Mermaid in an iframe.
```

### Product Rules

- Diagram generation is on demand, not automatic.
- Diagram generation currently requires a live ADK session.
- After a backend restart, diagram endpoints may return `Session not found` even if Firestore has saved history.
- Mermaid is rendered client-side with strict security mode.

---

## Flow 6: Finalization And Analysis

### Goal

When enough information has been collected, generate the final analysis package.

### Happy Path

```text
1. User confirms they are ready to finalize.
2. Backend workflow enters ready_to_finalize.
3. Orchestrator emits the [FINALIZING] marker.
4. Backend removes the marker from visible assistant text.
5. Backend streams {"event":"finalizing"} to the frontend.
6. Frontend switches to the Analysis tab and shows a finalizing overlay.
7. Backend marks finalization_status="pending".
8. Backend extracts final discovery fields.
9. Backend runs the finalizer in the background.
10. Finalizer writes final_analysis.json to GCS.
11. Finalizer writes final_analysis_json and status to Firestore.
12. Frontend polls GET /analyses/{session_id} every 5 seconds.
13. When status is complete, frontend renders AnalysisPanel.
```

### Final Analysis Includes

- Cleaned use-case form values.
- Technology recommendation.
- Recommended team profile.
- Priority tier and score.
- Risks, dependencies, and open questions.
- Metadata such as session ID, finalized time, model, and discovery completeness.

### Important Edge Cases

| Case | Expected behavior |
|---|---|
| Poll returns `not_found` | Finalization was not triggered or state has not been written yet. |
| Poll returns `pending` | Keep polling. |
| Poll returns `error` | Show failure state; backend logs contain finalizer failure details. |
| Cost circuit trips during finalizer extraction | Finalization is marked as error. |
| Backend restarts mid-finalization | In-flight background work may be lost because live ADK session state is in memory. |

---

## Flow 7: Document Download

### Goal

Export the collected requirement information as a Word or PDF document.

### RS-Template DOCX Flow

```text
1. Preview completeness reaches the configured threshold.
2. User clicks the RS-template DOCX download action.
3. Frontend calls POST /document/rs-template/docx.
4. Backend reads current discovery fields.
5. Backend generates rs_template.docx.
6. Backend saves the file to GCS under sessions/{session_id}/.
7. Backend returns DOCX bytes to the browser.
```

This is the main export path tied to the live RS fields.

### Legacy Document Flows

| Endpoint | Output | Notes |
|---|---|---|
| `POST /document` | Markdown JSON | Depends on legacy `[GENERATE_RS]` marker. |
| `POST /document/pdf` | PDF bytes | Depends on legacy generated markdown. |
| `POST /document/docx` | DOCX bytes | Compiles SRS JSON from the live session conversation. |

### Product Caveats

- `downloadPdf()` in frontend code is a stale function name; it currently downloads DOCX from `/document/docx`.
- Legacy document paths depend more heavily on live ADK session context than the RS-template DOCX path.

---

## Flow 8: Feedback

### Goal

Collect quality signals at message and session level for product improvement and operational analysis.

### Message Feedback

```text
1. User clicks thumbs up or thumbs down on an assistant message.
2. Frontend calls POST /feedback.
3. Backend stores vote and optional redacted comment in Firestore feedback collection.
4. BigQuery views can surface feedback for offline review.
```

The user can later update the comment through `PATCH /feedback/{message_id}`.

### Session Feedback

```text
1. User rates the overall session.
2. Frontend calls POST /feedback/session.
3. Backend stores session rating and comment.
4. Backend records session outcome metrics.
```

### Product Value

- Helps identify repeated questions, poor answers, and missing workflow fields.
- Provides signal for prompt, workflow, and extraction improvements.

---

## End-To-End Happy Path

```text
1. User describes the idea in chat.
2. Assistant asks structured discovery questions.
3. Preview fills across 28 canonical RS fields.
4. User edits precise direct fields when needed.
5. User uploads supporting files.
6. User generates BPMN/Data diagrams when enough detail exists.
7. User confirms finalization.
8. Analysis tab displays finalizer output.
9. User downloads RS-template DOCX.
10. User submits feedback.
```

---

## Current Product Limitations

- Live ADK sessions are in memory, so backend restarts can affect chat continuity, diagrams, and legacy document paths.
- The app has no full reconnect or replay mechanism for voice WebSocket sessions.
- Uploaded rich documents are not fully parsed for finalizer context yet.
- Some generated field labels may still fall back to English in localized UI.
- There is no separate pull-request CI workflow documented as current behavior; deployment workflow is the main GitHub Actions path.

---

## Suggested Acceptance Checks

Before demoing or releasing a build, run through:

1. Start a new text session and receive streamed assistant response.
2. Confirm Preview fields fill after extraction.
3. Edit at least one direct-input field and confirm it persists.
4. Upload a small `.txt` or `.csv` file and confirm it appears in uploads.
5. Generate RS-template DOCX after enough completeness.
6. Trigger finalization and confirm Analysis tab reaches `complete`.
7. Submit thumbs feedback on an assistant message.
8. Test voice mode on localhost if the change touches audio or WebSocket code.
