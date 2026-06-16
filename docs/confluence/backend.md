# Backend Technical Documentation

## Overview

The backend is a Python 3.12 FastAPI service that runs the conversational RS assistant, manages session state, stores uploaded artifacts, extracts RS template fields, generates diagrams and documents, and exposes observability instrumentation for the frontend and platform.

The service uses Google ADK for the main chat and audio agents. Some specialized jobs call Gemini directly through `google.genai.Client(api_key=GOOGLE_API_KEY)`, including discovery extraction, finalization, BPMN generation, and dataflow generation. Vertex AI inference is explicitly disabled through `GOOGLE_GENAI_USE_VERTEXAI=0`.

## Technology Stack

| Technology | Version | Purpose |
|---|---:|---|
| Python | >=3.12 | Runtime |
| FastAPI | 0.136.1 | HTTP API and WebSocket server |
| uvicorn | 0.46.0 | ASGI server |
| google-adk | 1.31.1 | ADK agent runtime and sessions |
| google-genai | 1.73.1 | Direct Gemini API calls |
| google-generativeai | 0.8.6 | Gemini dependency/client package |
| google-cloud-firestore | 2.27.0 | Session, discovery, feedback, and analysis persistence |
| google-cloud-storage | 3.4.1 | Uploads, generated artifacts, and knowledge base files |
| google-cloud-bigquery | 3.41.0 | Safety and observability queries |
| python-multipart | 0.0.27 | Multipart upload handling |
| reportlab | 4.4.10 | PDF generation |
| python-docx | 1.2.0 | DOCX generation |
| opentelemetry-instrumentation-fastapi | 0.59b0 | FastAPI instrumentation |
| opentelemetry-exporter-gcp-trace | 1.11.0 | Cloud Trace export |
| python-dotenv | 1.2.2 | Local `.env` loading |
| ruff | >=0.9.0 | Development linting/formatting |

Dependencies are managed with `uv` at the repository root. `backend/requirements.txt` is generated from `uv.lock` for the Docker build.

## Directory Structure

```text
backend/
|-- agent/
|   |-- agent.py              # ADK orchestrator and audio agent definitions
|   |-- discovery_agent.py    # Field extraction and one-field workflow helpers
|   |-- finalizer_agent.py    # Final analysis synthesis
|   |-- prompt.py             # Orchestrator system prompt
|   `-- research_agent.py     # Knowledge base / past analysis tools
|-- answer_classifier.py      # Detects whether a user answered the active field
|-- answer_quality.py         # Scores field-answer quality
|-- audio_websocket.py        # Gemini Live API WebSocket bridge
|-- bigquery/                 # BigQuery support package
|-- bpmn/
|   |-- generator.py          # Gemini -> Mermaid BPMN/flowchart text
|   `-- prompts.py
|-- config.py                 # Environment, model names, and runtime constants
|-- context/
|   |-- extractor.py          # Legacy upload-context extraction helpers
|   `-- prompts.py
|-- dataflow/
|   |-- generator.py          # Gemini -> Mermaid dataflow text
|   `-- prompts.py
|-- direct_field_context.py   # Injects direct/deferred field context into turns
|-- field_schema.py           # Canonical RS field schema
|-- firestore/
|   `-- writer.py             # Firestore read/write helpers
|-- gcs/
|   `-- connector.py          # Bucket I/O and knowledge-base listing/search
|-- generation/
|   |-- compiler.py           # Legacy chat history -> structured SRS JSON
|   |-- pdf_export.py         # Markdown -> PDF export
|   |-- srs_compiler.py       # Legacy four-block SRS compiler
|   `-- word_export.py        # RS template and legacy SRS DOCX export
|-- logger.py                 # Central logging setup
|-- main.py                   # FastAPI app entry point
|-- observability/
|   |-- callbacks.py          # ADK callback instrumentation
|   |-- cost.py               # Token/cost estimation helpers
|   |-- metrics.py            # OpenTelemetry metric definitions
|   |-- safety.py             # Prompt-risk and cost circuit breaker checks
|   |-- safety_anomalies.py   # BigQuery-backed anomaly helper queries
|   |-- tracing.py            # Trace setup helpers
|   |-- turns.py              # Turn-level metric aggregation
|   `-- redteam/run_redteam.py
|-- privacy/
|   `-- redactor.py           # PII redaction before persistence
|-- prompts/                  # Legacy/shared prompt modules
|-- scripts/
|   `-- generate_frontend_schema.py
|-- session_bridge.py         # Session helper utilities
|-- solution_configs.py       # Preset solution architecture configs
|-- tests/
|-- Dockerfile
|-- requirements.txt
`-- .env.example
```

## Runtime Configuration

`config.py` loads `.env` on import. The checked-in `backend/.env.example` currently lists only the core local variables, so deployment environments must also provide optional production variables below when needed.

| Variable | Required | Default | Used for |
|---|---|---|---|
| `GOOGLE_API_KEY` | Yes | None | Gemini API and ADK model access |
| `GOOGLE_CLOUD_PROJECT` | Production/staging | None | Firestore, BigQuery, Cloud Trace links |
| `GCS_BUCKET_NAME` | Production/staging | None | Uploads, generated docs, knowledge base |
| `FIRESTORE_COLLECTION` | Production/staging | None | Main session collection |
| `FIRESTORE_DATABASE` | Production/staging | None | Firestore database ID |
| `ALLOWED_ORIGINS` | No | `http://localhost:3000` | CORS allow-list, comma-separated |
| `APP_ENV` / `ENVIRONMENT` | No | `development` | Startup validation behavior |
| `BIGQUERY_DATASET` | No | `observability` | BigQuery dataset for safety and observability queries |
| `BIGQUERY_MESSAGES_VIEW` | No | `{project}.{dataset}.messages` | Message view for analysis queries |
| `BIGQUERY_FEEDBACK_VIEW` | No | `{project}.{dataset}.feedback` | Feedback view for analysis queries |
| `COST_CIRCUIT_BREAKER_USD` | No | `5.0` | Per-session in-memory cost limit |
| `GOOGLE_CLOUD_AUDIO_REGION` | No | `europe-west1` | Audio-region constant |
| `GOOGLE_CLOUD_REGION` | In `.env.example` | None | Present in example; not read directly by `config.py` |

Startup validation is environment-dependent:

- In `development`, only `GOOGLE_API_KEY` is mandatory. Missing GCP, GCS, or Firestore variables produce warnings and fail only when those integrations are used.
- In `staging` or `production`, `GOOGLE_API_KEY`, `GOOGLE_CLOUD_PROJECT`, `GCS_BUCKET_NAME`, `FIRESTORE_COLLECTION`, and `FIRESTORE_DATABASE` are required.

## Model Configuration

All model names live in `config.py`.

| Constant | Current value | Used by |
|---|---|---|
| `MODEL_AUDIO` | `gemini-3.1-flash-live-preview` | Gemini Live/audio agent |
| `MODEL_ORCHESTRATOR` | `gemini-3.1-pro-preview` | Main ADK chat agent |
| `MODEL_FINALIZER` | `gemini-3.1-pro-preview` | Final analysis synthesis |
| `MODEL_DISCOVERY` | `gemini-3.1-flash-lite` | Field extraction |
| `MODEL_RESEARCH` | `gemini-3.1-flash-lite` | Reserved/configured for research features |
| `MODEL_BPMN` | `gemini-3.1-flash-lite` | BPMN diagram generation |
| `MODEL_DATAFLOW` | `gemini-3.1-flash-lite` | Dataflow diagram generation |
| `MODEL_SRS_COMPILER` | `gemini-3.1-flash-lite` | Legacy SRS compiler |

## Canonical Field Schema

`field_schema.py` is the single source of truth for RS template fields and drives both backend behavior and frontend generated TypeScript schema.

Current schema shape:

- 28 total fields.
- 20 required fields.
- 8 optional fields.
- 9 direct-input fields.
- 5 strict direct-input fields.
- 4 suggestable direct-chat fields.
- 6 sections: identity/current state, target state, value/ROI, priority/risk, technical context, and additional information.

Important exports include:

```python
SECTION_TITLES
FIELD_SCHEMA
EMPTY_FIELDS
FIELD_LABELS
REQUIRED_FIELDS
DIRECT_FIELD_KEYS
STRICT_DIRECT_INPUT_KEYS
SUGGESTABLE_DIRECT_CHAT_FIELD_KEYS
build_sections()
is_required_complete()
calculate_completeness()
normalize_discovery_state()
```

`scripts/generate_frontend_schema.py` converts this Python schema into `frontend/app/generated/rsSchema.ts`. Regenerate the frontend schema after any field changes.

```powershell
cd backend
..\.venv\Scripts\python.exe scripts\generate_frontend_schema.py
```

Adjust the Python path to match the active virtual environment.

## Session and Agent Architecture

`main.py` creates one shared ADK `InMemorySessionService`, one `Runner` for the text orchestrator, and one `Runner` for the audio agent. ADK session state is therefore process-local and is lost on backend restart. Firestore persists chat messages, discovery state, direct/deferred fields, workflow state, feedback, and final analysis results, but it does not fully restore an in-flight ADK runner session.

### Main Orchestrator

`agent/agent.py` defines `rs_agent`:

- ADK `Agent` named `business_analyst_orchestrator`.
- Uses `MODEL_ORCHESTRATOR`.
- Uses `ORCHESTRATOR_SYSTEM_PROMPT`.
- Registers research tools from `RESEARCH_TOOLS`.
- Uses observability callbacks before/after model and tool calls.

The orchestrator streams natural-language interview responses. It may emit internal markers:

- `[FINALIZING]` starts the asynchronous final analysis pipeline.
- `[GENERATE_RS]` is a legacy document-generation marker used by `/document`, `/document/pdf`, and `/document/docx`.

### Audio Agent

`audio_agent` is a separate ADK agent using `MODEL_AUDIO` through a custom `_ApiKeyGemini` wrapper so the Live API uses `GOOGLE_API_KEY`. `audio_websocket.py` handles bidirectional audio transport at `WS /ws/{user_id}/{session_id}` and shares the same ADK session service as text chat.

### Discovery and One-Field Workflow

`agent/discovery_agent.py` performs two related jobs:

- Extracts field values from conversation text through direct Gemini API calls using `MODEL_DISCOVERY`.
- Maintains workflow helpers for the active field, deferred fields, answer classification, and quality scoring.

The backend does not broadcast discovery state over a WebSocket. Instead:

- `/chat/stream` may emit a pre-stream `field_update` SSE event when the active field can be updated immediately from the user's latest answer.
- The frontend calls `/context/extract` to run/refresh extraction for a session.
- Firestore stores the latest merged discovery state.

### Research Tools

`agent/research_agent.py` exposes:

- `search_past_analyses(query, session_id=None, max_results=3)`: keyword-ranks stored GCS analyses under `analyses/*/final_analysis.json`.
- `list_knowledge_base_docs(category="templates")`: lists GCS files under `knowledge_base/templates/`, `knowledge_base/guidelines/`, or `knowledge_base/examples/`.
- `search_vertex_ai(...)`: currently a compatibility stub that reports Vertex AI Search is unavailable and points callers to `search_past_analyses`.

Research is therefore GCS-backed today, not Vertex AI Search-backed.

## API Endpoints

### Health and Chat

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Returns service status, timestamp, configured project, and bucket |
| `POST` | `/chat` | Non-streaming chat; returns `reply`, `session_id`, and `message_id` |
| `POST` | `/chat/stream` | SSE chat stream with chunks, workflow events, finalization event, and `[DONE]` |
| `WS` | `/ws/{user_id}/{session_id}` | Bidirectional audio WebSocket |

`POST /chat` and `POST /chat/stream` accept `message`, optional `session_id`, optional `user_id` defaulting to `default_user`, and optional `direct_fields` / `deferred_fields`.

`/chat/stream` emits SSE `data:` frames. Known payloads include:

- Initial metadata: `{"session_id": "...", "message_id": "..."}`
- Active field update: `{"event": "active_field", "field_key": "..."}`
- Field update: `{"event": "field_update", "fields": {...}, "completeness": 42}`
- Text chunk: `{"text": "..."}`
- Finalization start: `{"event": "finalizing"}`
- Error: `{"error": "..."}`
- End marker: `data: [DONE]`

### Uploads and Session Data

| Method | Path | Description |
|---|---|---|
| `POST` | `/upload` | Multipart upload with `file` and `session_id`; 10 MB limit; writes to GCS |
| `GET` | `/uploads/{session_id}` | Lists uploaded files for a session |
| `GET` | `/sessions` | Lists Firestore sessions |
| `GET` | `/history/{session_id}` | Returns persisted chat history |
| `GET` | `/firestore/data/{session_id}` | Debug-style Firestore snapshot endpoint |

Uploaded filenames are sanitized and stored under `sessions/{session_id}/{filename}`.

### Discovery and Analysis

| Method | Path | Description |
|---|---|---|
| `POST` | `/context/extract` | Runs or returns discovery extraction for a session |
| `GET` | `/discovery/{session_id}` | Returns persisted discovery/direct/deferred/workflow state |
| `PATCH` | `/discovery/{session_id}/fields` | Merges direct/deferred field updates |
| `GET` | `/analyses/{session_id}` | Returns final analysis status and completed analysis JSON |

`/context/extract` uses a per-session lock to avoid duplicate concurrent Gemini extraction. If the ADK session has been lost, it falls back to Firestore discovery state when available.

`/analyses/{session_id}` returns one of these states:

- `not_found`
- `pending`
- `error`
- `complete`

### Documents and Diagrams

| Method | Path | Description |
|---|---|---|
| `POST` | `/document` | Legacy markdown RS generation from ADK session history after `[GENERATE_RS]` |
| `POST` | `/document/pdf` | Legacy markdown-to-PDF export |
| `POST` | `/document/docx` | Legacy four-block SRS JSON-to-DOCX export |
| `POST` | `/document/rs-template/docx` | DOCX export from current RS template fields |
| `POST` | `/bpmn/generate` | Generates Mermaid BPMN/flowchart text; ready threshold 90 |
| `POST` | `/dataflow/generate` | Generates Mermaid dataflow text; ready threshold 70 |

`/document/rs-template/docx` saves `sessions/{session_id}/rs_template.docx` in GCS and returns the file with `X-GCS-Path`.

### Feedback

| Method | Path | Description |
|---|---|---|
| `POST` | `/feedback` | Creates message-level feedback |
| `PATCH` | `/feedback/{message_id}` | Updates message-level feedback |
| `POST` | `/feedback/session` | Stores session-level rating/comment and closes the session |

## Main Chat Flow

```text
User message
  |
  v
POST /chat or /chat/stream
  |
  |-- validate input against safety rules and cost circuit breaker
  |-- ensure ADK session exists
  |-- merge direct/deferred field state
  |-- classify/rate active-field answer for one-field workflow
  |-- optionally emit field_update before the LLM response
  |
  v
ADK orchestrator runner
  |
  |-- may call research tools
  |-- streams text chunks to the client
  |-- stores redacted user/assistant messages in Firestore
  |
  v
If [FINALIZING] appears:
  |-- emit finalizing SSE event
  |-- mark Firestore finalization_status=pending
  |-- extract latest discovery fields
  `-- schedule run_finalizer(...)
```

## Finalization Flow

`run_finalizer()` in `main.py` performs the final analysis pipeline:

1. Reads uploaded artifacts from `sessions/{session_id}/`.
2. Includes text content for `.txt`, `.md`, `.json`, and `.csv` files.
3. Lists binary files such as PDFs or Office docs as attachments but does not parse their content in this path.
4. Calls `agent.finalizer_agent.run_finalizer_agent(...)` using `MODEL_FINALIZER`.
5. Writes JSON to GCS at `analyses/{session_id}/final_analysis.json`.
6. Stores `final_analysis_json`, `finalization_status`, and `finalized_at` in Firestore.

The frontend polls `GET /analyses/{session_id}` for completion.

## Firestore Data Model

Main collection: `{FIRESTORE_COLLECTION}`

Document ID: `{session_id}`

Important fields:

| Field | Type | Notes |
|---|---|---|
| `session_id` | string | Session UUID |
| `updated_at` | timestamp | Last write time |
| `messages` | array | Redacted user/assistant messages appended with `ArrayUnion` |
| `discovery_state_json` | string | AI-extracted field state as serialized JSON |
| `direct_fields_json` | string | User-entered direct fields as serialized JSON |
| `deferred_fields_json` | string | Deferred field keys/values as serialized JSON |
| `workflow_state_json` | string | One-field workflow state as serialized JSON |
| `finalization_status` | string | `pending`, `complete`, or `error` |
| `finalized_at` | timestamp | Completion/error timestamp |
| `final_analysis_json` | string | Final analysis JSON string |
| `session_status` | string | Set to `ended` after session feedback |
| `ended_at` | timestamp | Session feedback timestamp |

For compatibility/reporting, `persist_srs_fields()` also writes flattened SRS summary fields:

- `s1_context`
- `s1_business_problem`
- `s2_target_state`
- `s2_success`
- `s3_scope_in_out`
- `s3_boundaries`
- `s4_data_systems`
- `s4_integrations_access`

Stored message entries include redacted text, text hash, trace/span IDs, model, token and cost metrics, timings, tool calls, phase, finish reason, and timestamps. `get_discovery_state()` merges direct fields over AI-extracted fields and recomputes completeness over required fields.

Feedback is stored in a separate top-level `feedback` collection:

- Message feedback documents are keyed by `message_id`.
- Session feedback documents are keyed as `session:{session_id}`.
- Feedback comments are redacted before storage.

## GCS Layout

Bucket: `{GCS_BUCKET_NAME}`

```text
sessions/{session_id}/{filename}          # User uploads
sessions/{session_id}/rs_template.docx    # Current RS template DOCX export
analyses/{session_id}/final_analysis.json # Finalizer output
knowledge_base/templates/                 # Template documents
knowledge_base/guidelines/                # Guideline documents
knowledge_base/examples/                  # Example documents
```

There is no current code path that writes final analysis JSON to `sessions/{session_id}/final_analysis.json`; the finalizer writes it under `analyses/{session_id}/`.

## Observability, Safety, and Privacy

### Safety

`observability/safety.py` applies deterministic prompt-risk checks before model execution. It looks for prompt injection, prompt extraction, data exfiltration, role injection, jailbreak patterns, obfuscated exfiltration, and PII-extraction attempts.

Blocked requests return:

- HTTP 400 for non-streaming endpoints.
- An SSE `{"error": "..."}` payload for streaming chat.

The same module keeps an in-memory per-session cost accumulator and blocks requests with HTTP 429 after `COST_CIRCUIT_BREAKER_USD`.

### Cost, Metrics, and Tracing

- `observability/cost.py` estimates model cost from token metadata.
- `observability/metrics.py` defines counters/histograms for turns, feedback, tokens, costs, safety blocks, and generation events.
- `observability/tracing.py` configures tracing.
- `observability/callbacks.py` wires ADK callbacks into logging/metrics.
- `observability/safety_anomalies.py` queries BigQuery views for anomaly detection helpers.

### Privacy

`privacy/redactor.py` redacts PII before persisting chat and feedback text. Firestore stores redacted text plus original-text hashes for traceability, not raw message bodies.

## CORS and Error Handling

`ALLOWED_ORIGINS` defaults to `http://localhost:3000` and is parsed as a comma-separated list. CORS allows credentials, methods `GET`, `POST`, `PATCH`, and `OPTIONS`, and headers `Content-Type` and `Authorization`.

`main.py` registers a global exception handler that logs unexpected errors and returns a JSON 500 response, allowing FastAPI/CORS middleware to still attach CORS headers.

## Document Generation

There are two document-generation paths:

| Path | Source | Output |
|---|---|---|
| Current RS template export | Live RS template fields from request body | DOCX via `rs_template_to_docx()` |
| Legacy generated SRS export | ADK session history after `[GENERATE_RS]` | Markdown, PDF, or DOCX |

`generation/word_export.py` contains both `rs_template_to_docx(fields)` for the 28-field template and `srs_json_to_docx(srs)` for the legacy four-block SRS format.

`generation/pdf_export.py` converts generated markdown into a styled PDF using ReportLab. It supports headings, lists, requirement IDs, and a generation timestamp.

## Running Locally

From the repository root, install dependencies with `uv`:

```powershell
uv sync
```

Create `backend/.env` from `backend/.env.example` and fill in at least `GOOGLE_API_KEY`. GCP, GCS, and Firestore variables are needed for persistence, uploads, finalization storage, and most full-stack flows.

Run the backend with the active virtual environment:

```powershell
cd backend
..\.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

If the virtual environment is located at `backend/.venv`, use:

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

## Docker

`backend/Dockerfile`:

- Uses `python:3.12-slim`.
- Installs `backend/requirements.txt` with `pip install --require-hashes`.
- Copies backend source into `/app`.
- Exposes port `8080`.
- Runs `uvicorn main:app --host 0.0.0.0 --port 8080`.

Regenerate `backend/requirements.txt` from the lock file after dependency changes:

```powershell
uv export --frozen --no-dev --no-emit-project --output-file backend/requirements.txt
```

## Testing and Code Quality

Run backend tests from the backend directory with the active virtual environment:

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests -v
```

Notable test files:

| Test file | Coverage area |
|---|---|
| `test_agent_prompts.py` | Orchestrator prompt behavior |
| `test_api_integration.py` | FastAPI contracts |
| `test_compiler.py` | Legacy SRS compiler behavior |
| `test_diagram_prompts.py` | BPMN/dataflow prompts |
| `test_direct_field_context.py` | Direct/deferred field context injection |
| `test_e2e_smoke.py` | Full smoke path |
| `test_finalizer_agent.py` | Finalizer output structure |
| `test_observability_metrics.py` | Metrics behavior |
| `test_observability_safety.py` | Safety and cost circuit behavior |
| `test_one_field_workflow.py` | Active-field workflow |
| `test_pdf_export.py` | PDF export |

`pyproject.toml` currently configures Ruff. No mypy or pre-commit configuration is present in the repository.

## Known Constraints and Drift Risks

- Several code docstrings still mention 22 fields, but the canonical schema currently has 28 fields.
- Some module comments still refer to Vertex AI. Current inference uses `GOOGLE_API_KEY`; the research Vertex AI function is only a stub.
- ADK sessions are in-memory. Firestore keeps durable history and discovery state, but a backend restart can lose live ADK session context and in-flight finalizer triggers.
- `/context/extract` can return persisted Firestore discovery when ADK session state is missing.
- Upload finalization includes plain text-like files directly, but PDFs and Office files are currently listed rather than parsed by `run_finalizer()`.
- `GOOGLE_CLOUD_REGION` is present in `.env.example`, while `config.py` defines `GOOGLE_CLOUD_AUDIO_REGION` for the audio-region constant.
- `BIGQUERY_*`, `COST_CIRCUIT_BREAKER_USD`, `APP_ENV`, `ENVIRONMENT`, and `GOOGLE_CLOUD_AUDIO_REGION` are used by code but are not currently included in `.env.example`.
- `MODEL_RESEARCH` is configured, but current research tools are deterministic GCS helper functions rather than model calls.
