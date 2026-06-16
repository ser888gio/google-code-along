# System Architecture

## Overview

The RS Generator is a cloud-native, AI-first application built on Google Cloud Platform. It follows a client-server-cloud architecture where a Next.js frontend talks to a Python/FastAPI backend. The backend uses Google ADK and Gemini models to run a structured requirements discovery conversation, maintain a live Requirements Specification (RS) field state, generate diagrams and documents, and compile a final analysis.

The current implementation is centered on:

- A chat-first Next.js UI with optional voice mode.
- A FastAPI backend hosted on Cloud Run.
- Google ADK for the primary text and audio agents.
- Direct Gemini API key usage, not Vertex AI mode.
- Firestore for persisted session, discovery, workflow, final-analysis, and feedback data.
- GCS for uploaded files and generated artifacts.
- BigQuery plus Cloud Monitoring/Trace for observability and safety analysis.

---

## High-Level Architecture Diagram

```text
+------------------------------------------------------------------+
| User Browser                                                     |
|                                                                  |
|  +--------------------------+   +------------------------------+ |
|  | Chat UI                  |   | RS workspace                  | |
|  | Next.js / React          |<->| Preview, BPMN, Data, DB,     | |
|  | Text and voice modes     |   | Analysis, Summary            | |
|  +-------------+------------+   +------------------------------+ |
+----------------+-------------------------------------------------+
                 |
                 | HTTP + SSE: POST /chat/stream
                 | HTTP: uploads, discovery, diagrams, docs, feedback
                 | WebSocket: /ws/{user_id}/{session_id}
                 v
+------------------------------------------------------------------+
| Backend (Cloud Run)                                              |
| FastAPI + uvicorn                                                |
|                                                                  |
|  +------------------------------------------------------------+  |
|  | Google ADK runtime                                         |  |
|  |                                                            |  |
|  |  +------------------------+   +--------------------------+ |  |
|  |  | Orchestrator agent     |   | Audio agent              | |  |
|  |  | Gemini 3.1 Pro preview |   | Gemini 3.1 Flash Live    | |  |
|  |  +------------+-----------+   +-------------+------------+ |  |
|  +---------------+-----------------------------+--------------+  |
|                  |                             |                 |
|  +---------------v-----------------------------v--------------+  |
|  | Backend workflow and generation pipeline                   |  |
|  | - field workflow cursor and classifiers                    |  |
|  | - discovery extraction                                     |  |
|  | - finalizer                                                |  |
|  | - PDF/DOCX/RS-template DOCX export                         |  |
|  | - BPMN and Data Flow Mermaid generation                    |  |
|  +------------------------------------------------------------+  |
+------------------+------------------+----------------------------+
                   |                  |
       +-----------v------+   +-------v--------+   +----------------+
       | Firestore        |   | GCS            |   | Gemini API     |
       | sessions,        |   | uploads,       |   | direct key     |
       | feedback, state  |   | analyses, docs |   | usage          |
       +-----------+------+   +-------+--------+   +----------------+
                   |
                   v
       +------------------+
       | BigQuery views   |
       | observability    |
       +------------------+
```

---

## Component Breakdown

### Frontend (Cloud Run - Next.js)

| Component | Responsibility |
|---|---|
| `app/page.tsx` | Main chat UI, session lifecycle, history loading, voice mode, finalization polling |
| `MessageBubble` in `page.tsx` | Render conversation turns with Markdown and feedback controls |
| `RsLiveTemplate` | Real-time RS preview; shows all canonical fields with fill status and direct-input controls |
| `BpmnPanel` / `DataflowPanel` | Request backend-generated Mermaid syntax and render diagrams |
| `FirestoreSrsPanel` | Displays compiled Firestore SRS snapshot data |
| `AnalysisPanel` | Displays finalizer output once `GET /analyses/{session_id}` reports completion |
| `FileUpload` | Uploads files to backend `/upload`, which writes them to GCS |
| `lib/api.ts` | HTTP and SSE API client for chat, discovery, docs, diagrams, uploads, and feedback |
| `lib/useWebSocket.ts` | Persistent WebSocket connection for voice mode |
| `lib/useAudioRecorder.ts` / `lib/useAudioPlayer.ts` | Browser PCM capture/playback for Gemini Live voice mode |
| `app/generated/rsSchema.ts` | Auto-generated field and section metadata from backend schema |

### Backend (Cloud Run - Python/FastAPI)

| Module | Responsibility |
|---|---|
| `main.py` | FastAPI entry point; HTTP routes, SSE route, WebSocket route, session orchestration |
| `agent/agent.py` | ADK text orchestrator and audio agent instances |
| `agent/discovery_agent.py` | Gemini-based field extraction plus workflow cursor helpers |
| `answer_classifier.py` / `answer_quality.py` | Per-field answer classification, deferral detection, and answer quality scoring |
| `direct_field_context.py` | Merges direct-input field values into hidden prompt context |
| `agent/finalizer_agent.py` | Final analysis compilation and persistence |
| `agent/research_agent.py` | GCS past-analysis search and knowledge-base listing tools |
| `field_schema.py` | Canonical RS schema: 28 fields, 6 sections |
| `generation/` | Legacy RS markdown compiler, SRS JSON compiler, PDF/DOCX/RS-template DOCX export |
| `bpmn/`, `dataflow/` | Diagram readiness scoring and Mermaid syntax generation |
| `firestore/writer.py` | Firestore persistence for sessions, messages, discovery state, workflow state, final analysis, feedback |
| `gcs/connector.py` | GCS list/read/write/delete/existence operations |
| `observability/` | Metrics, tracing, model callbacks, safety checks, cost tracking, anomaly queries |
| `privacy/redactor.py` | Local redaction and hashing for persisted conversation and feedback text |

---

## AI Agent Design

The backend uses two ADK agents plus two direct Gemini helper pipelines.

### Orchestrator Agent

- Model: `gemini-3.1-pro-preview`
- Role: Drives the conversational discovery interview as an expert IT business consultant.
- Transport: ADK runner used by `/chat` and `/chat/stream`.
- Tools: `search_vertex_ai`, `search_past_analyses`, `list_knowledge_base_docs`.
- Output: Streaming text response plus optional finalization marker `[FINALIZING]`.
- Context: ADK `InMemorySessionService` holds live conversation events for the current backend process.

Important implementation detail: ADK sessions are currently in-memory. Firestore persists messages and field state, but a backend restart drops live ADK session context and any in-flight finalization trigger.

### Discovery Extraction

- Model: `gemini-3.1-flash-lite`
- Role: Extracts the canonical RS field values from the conversation transcript.
- Triggered by:
  - `POST /context/extract` after frontend chat turns.
  - Finalization pre-processing before `run_finalizer`.
- Output: `{"completeness", "fields", "missing_priority"}` where `fields` contains all canonical keys.
- Persistence: Saved to Firestore as `discovery_state_json`, then merged with `direct_fields_json` when read.

### Workflow Cursor and Answer Classification

The backend owns a deterministic discovery workflow cursor. Before each streamed model turn, `_prepare_workflow_turn` updates:

- `phase`: `discovery`, `wrap_up`, `ready_to_finalize`, `finalizing`, or `complete`.
- `active_field`: the next field the assistant should ask about.
- `field_status`: `missing`, `answered`, `deferred`, `clarification_requested`, or `not_applicable`.
- `miss_counts`, `clarification_counts`, and coverage gaps.

This state is persisted as `workflow_state_json` and used to build hidden context for the orchestrator.

### Finalizer Pipeline

- Model: `gemini-3.1-pro-preview`
- Role: Synthesizes the final use-case analysis JSON.
- Triggered: When the orchestrator emits `[FINALIZING]`.
- Input:
  - Conversation transcript.
  - Latest discovery fields.
  - User-uploaded readable file contents from `sessions/{session_id}/`.
  - Optional `research_context` parameter. The current main path does not pass this parameter.
- Output:
  - GCS: `analyses/{session_id}/final_analysis.json`.
  - Firestore: `finalization_status`, `finalized_at`, and `final_analysis_json`.
- Frontend polling: `GET /analyses/{session_id}`.

### Audio Agent

- Model: `gemini-3.1-flash-live-preview`
- Role: Bidirectional voice conversation.
- Transport: WebSocket `/ws/{user_id}/{session_id}`.
- Protocol:
  - Client sends binary PCM audio frames and JSON text fallback frames.
  - Backend sends binary PCM audio and JSON transcription/status events.
- Session bridge: Voice transcripts are injected into the text orchestrator's ADK session so text mode can continue with the voice context.

---

## Session Lifecycle

```text
1. Created
   Frontend creates or receives a UUID session ID.
   First chat message sent to POST /chat/stream creates an ADK session if needed.

2. Discovery
   Backend loads persisted direct/discovery/deferred/workflow state.
   Backend classifies the latest answer and chooses the next active field.
   Orchestrator streams an answer via SSE.
   Frontend calls POST /context/extract after the turn.
   Discovery state and SRS snapshot are persisted to Firestore.

3. Wrap-up / Ready to Finalize
   Workflow enters wrap_up when required and optional field flow is exhausted.
   If the user chooses to generate/finalize, workflow enters ready_to_finalize.
   Orchestrator may emit [FINALIZING].

4. Finalizing
   Backend marks finalization_status="pending".
   Backend extracts final discovery fields and starts run_finalizer() in the background.
   Frontend receives an SSE finalizing event and polls GET /analyses/{session_id}.

5. Complete
   Finalizer writes final_analysis.json to GCS and final_analysis_json to Firestore.
   Frontend displays the Analysis tab when polling returns status="complete".
   User can download generated documents from document endpoints.

6. Feedback / End
   Users can submit message feedback and a session rating.
   Feedback is written to the top-level Firestore feedback collection.
```

---

## Data Storage Design

### Firestore (Operational Data)

Firestore is the authoritative persisted store. The backend is the writer/reader; the frontend accesses data through FastAPI endpoints.

Session documents are stored in the configured `FIRESTORE_COLLECTION`.

```text
{FIRESTORE_COLLECTION}/
+-- {session_id}/
    +-- session_id
    +-- updated_at
    +-- messages[]                 # Redacted user/assistant message docs
    +-- discovery_state_json        # JSON string: completeness, fields, missing_priority
    +-- direct_fields_json          # JSON string: user-entered direct-input fields
    +-- deferred_fields_json        # JSON string: deferred field metadata
    +-- workflow_state_json         # JSON string: phase, active_field, statuses, counts
    +-- finalization_status         # "pending" | "complete" | "error"
    +-- final_analysis_json         # JSON string: finalizer output
    +-- finalized_at
    +-- session_status
    +-- ended_at
    +-- SRS snapshot fields         # s1_context, s1_business_problem, etc.
```

Message documents include redacted text, original text hash, trace IDs, model, token counts, cost, latency, tool calls, phase, finish reason, and timestamp.

Feedback is stored separately:

```text
feedback/
+-- {assistant_message_id}
|   +-- feedback_type="message"
|   +-- session_id
|   +-- message_id
|   +-- vote
|   +-- comment_redacted
|   +-- comment_original_hash
+-- session:{session_id}
    +-- feedback_type="session"
    +-- rating
    +-- comment_redacted
    +-- ended_at
```

### Google Cloud Storage

GCS stores binary and bulky data. Uploads go through the backend `/upload` endpoint; the frontend does not currently use signed upload URLs.

```text
{GCS_BUCKET}/
+-- sessions/{session_id}/
|   +-- uploaded user files
|   +-- rs_template.docx
+-- analyses/{session_id}/
|   +-- final_analysis.json
+-- knowledge_base/
    +-- templates/
    +-- guidelines/
    +-- examples/
```

Upload constraints:

- Files are sanitized before writing.
- Current max upload size is 10 MB.
- Finalizer reads plain text extensions only: `.txt`, `.md`, `.json`, `.csv`.
- PDF/DOCX/image uploads are listed for context but not text-extracted yet.

### BigQuery

BigQuery is used for observability and safety analytics. Views are defined in `infra/firestore-bigquery/`:

- `messages_view.sql`: flattens Firestore session `messages[]`.
- `feedback_view.sql`: reads the top-level Firestore `feedback` collection export.

## Streaming Architecture

### Server-Sent Events - Chat Responses

```text
Browser -> POST /chat/stream
        <- data: {"session_id": "..."}
        <- data: {"message_id": "..."}
        <- data: {"active_field": "..."}
        <- data: {"text": "..."}
        <- data: {"event": "finalizing"}       # only when [FINALIZING] detected
        <- data: [DONE]
```

The frontend appends text chunks to the active assistant bubble, updates active field state, pre-fills field updates when provided, and starts finalization polling on the finalizing event.

### WebSocket - Voice Mode

```text
Browser <-> WS /ws/{user_id}/{session_id}
```

Binary frames carry raw PCM audio. Text frames carry JSON events such as text fallback, transcript partials, transcript finals, errors, and turn completion.

---

## RS Field Schema Architecture

`backend/field_schema.py` is the canonical source for the RS structure. It currently defines 28 fields across 6 sections:

- 20 required fields.
- 8 optional fields.
- Direct-input metadata for fields that should be typed by the user or preserved from manual edits.
- Validation mode, expected shape, examples, and rubric metadata.

```text
backend/field_schema.py
        |
        v
backend/scripts/generate_frontend_schema.py
        |
        v
frontend/app/generated/rsSchema.ts
        |
        v
RsLiveTemplate.tsx and direct-chat helpers
```

The schema drives:

- Field order and section layout.
- Which fields are required or optional.
- Which fields can be directly edited.
- Which fields can be inferred from chat.
- Direct-chat pattern matching.
- Deferred-answer detection.
- Finalizer and extraction prompt metadata.

---

## Knowledge Base Retrieval

The orchestrator has three registered research tools:

- `search_vertex_ai`: currently a stub that returns "not available".
- `search_past_analyses`: scans `analyses/*/final_analysis.json` in GCS and ranks by keyword overlap.
- `list_knowledge_base_docs`: lists files under `knowledge_base/templates/`, `knowledge_base/guidelines/`, and `knowledge_base/examples/`.

The current MVP does not use vector embeddings or Vertex AI Search. The finalizer supports an optional `research_context` parameter, but the main finalization path does not currently pass retrieved examples into it.

---

## Document and Diagram Generation

### Documents

| Endpoint | Behavior |
|---|---|
| `POST /document` | Returns legacy generated RS markdown if `[GENERATE_RS]` exists in ADK session events |
| `POST /document/pdf` | Converts legacy RS markdown to PDF |
| `POST /document/docx` | Compiles SRS JSON from the conversation and returns DOCX |
| `POST /document/rs-template/docx` | Generates a DOCX from current RS field values, saves it to GCS, and returns it |

`[GENERATE_RS]` is still used by the legacy document compiler path. The final analysis pipeline uses `[FINALIZING]`.

### Diagrams

Diagrams are generated on demand, not automatically during finalization.

| Endpoint | Readiness | Output |
|---|---:|---|
| `POST /bpmn/generate` | Score >= 90 | Mermaid BPMN-style flowchart |
| `POST /dataflow/generate` | Score >= 70 | Mermaid Data Flow Diagram |

Both endpoints require a live ADK session. If the backend process restarted and the in-memory session is gone, they return session not found.

---

## Observability Architecture

```text
Request / turn
   |
   +--> safety preflight for user prompt and session cost
   |
   +--> ADK before_model_callback
   |       - stamp active span with model/session/user/agent attributes
   |       - add redacted prompt event
   |
   +--> Gemini API call
   |
   +--> ADK after_model_callback
   |       - record usage, token counts, cache reads, finish reason
   |       - compute model cost and add session cost
   |       - record latency and safety finish counters
   |
   +--> Firestore persistence
   |       - redacted messages and metrics fields
   |
   +--> Cloud Trace / Cloud Monitoring exporters
```

Additional observability surfaces:

- `observability/safety.py` blocks known unsafe prompt patterns and enforces per-session cost budget.
- `infra/safety/anomalous_sessions.sql` and `infra/safety/anomaly-metric-job.yaml` support scheduled anomaly detection.
- `infra/monitoring/` contains dashboard, log-based metrics, and alert policy definitions.
- BigQuery-backed session and feedback views support offline observability analysis.

---

## Security and Privacy Considerations

| Concern | Current mitigation |
|---|---|
| GCP credentials | GitHub Actions uses Workload Identity Federation; Cloud Run uses runtime service identity |
| Gemini API key | Injected from Secret Manager in deployment; direct API key mode is forced via `GOOGLE_GENAI_USE_VERTEXAI=0` |
| PII in stored messages | `privacy/redactor.py` redacts common emails, phones, API keys, and credit cards, and stores original text hashes |
| Prompt injection from user data | Finalizer wraps transcript and uploaded file content with explicit user-data guardrails |
| Prompt safety | `observability/safety.py` checks user prompts before chat execution |
| Cost runaway | Per-session cost circuit breaker defaults to `COST_CIRCUIT_BREAKER_USD=5.0` |
| Supply chain | Backend Docker install uses `pip install --require-hashes -r requirements.txt` |
| Secrets in repo | `.gitignore` excludes `.env`, `gcp-key.json`, `.venv/` |

---

## Code Quality Pipeline

Pre-commit hooks are configured in `.pre-commit-config.yaml`:

```text
trailing-whitespace
end-of-file-fixer
check-yaml / check-toml
check-added-large-files
shellcheck
ruff check --fix
ruff format
mypy
knip
debtmap
```

The current GitHub Actions workflow is deployment-focused. It runs on pushes to `develop` and builds/deploys backend and frontend to Cloud Run. It does not currently define a separate pull-request test workflow.

---

## Deployment Pipeline

```text
git push -> develop
    |
    v
GitHub Actions: .github/workflows/cicd.yaml
    |
    +--> Authenticate to Google Cloud via Workload Identity Federation
    +--> Configure Docker auth for Artifact Registry
    +--> Build and push backend image
    +--> Deploy backend to Cloud Run in europe-west4
    +--> Build frontend image with:
    |       NEXT_PUBLIC_API_URL=<backend URL>
    |       NEXT_PUBLIC_WS_URL=wss://<backend host>
    +--> Deploy frontend to Cloud Run in europe-west4
```

Backend runtime secrets are injected from Secret Manager:

- `GOOGLE_API_KEY`
- `GCS_BUCKET_NAME`
- `FIRESTORE_COLLECTION`
- `FIRESTORE_DATABASE`

See the [Deployment Guide](deployment.md) for manual deployment and GCP setup details.

---

## Technology Decisions and Rationale

| Decision | Rationale |
|---|---|
| Google ADK | Provides agent runtime, model callbacks, tool use, and Gemini Live integration |
| Gemini 3.1 Pro preview for orchestrator/finalizer | Large-context reasoning for discovery and final synthesis |
| Gemini 3.1 Flash Lite for discovery/diagrams | Lower latency and cost for extraction and scoring tasks |
| Direct Gemini API key | Simpler setup than Vertex AI mode for this MVP |
| Firestore for persisted session state | Document model fits session data; integrates with Firestore-to-BigQuery export |
| ADK in-memory sessions for live context | Simple local/cloud runtime, but persistent ADK sessions are needed before production hardening |
| GCS for uploads and generated artifacts | Durable storage for binary files and generated JSON/DOCX artifacts |
| GCS keyword search for past analyses | Simple MVP retrieval without vector index provisioning |
| BigQuery views for observability | Gives replayable analytics over redacted messages and feedback |
| `field_schema.py` as schema source | Prevents drift between extraction, workflow, exports, and frontend rendering |
| Mermaid.js for diagrams | Client-side rendering with simple backend-generated diagram syntax |
| Cloud Run for hosting | Serverless Docker deployment with native GCP integrations |
