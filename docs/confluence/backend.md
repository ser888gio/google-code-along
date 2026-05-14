# Backend Technical Documentation

## Overview

The backend is a **Python 3.12 FastAPI** application that orchestrates the AI agents, manages session state, handles document generation, and exposes REST and WebSocket endpoints consumed by the frontend. It is built on top of **Google Agent Development Kit (ADK)** and talks to Gemini models directly via the `GOOGLE_API_KEY`.

---

## Technology Stack

| Technology | Version | Purpose |
|---|---|---|
| Python | 3.12 | Runtime |
| FastAPI | 0.136.1+ | HTTP framework and WebSocket server |
| uvicorn | 0.46.0+ | ASGI server |
| google-adk | 1.31.1+ | Agent orchestration framework (mandatory) |
| google-generativeai | 0.8.6+ | Gemini API client |
| google-cloud-firestore | 2.27.0+ | Session persistence |
| google-cloud-storage | 3.4.1+ | File storage and knowledge base |
| reportlab | 4.4.10+ | PDF document generation |
| python-docx | 1.2.0+ | Word document generation |
| opentelemetry-* | 0.59b0+ | Distributed tracing and metrics |
| python-dotenv | 1.2.2+ | Environment variable loading |
| ruff | 0.9.0+ | Linting and formatting (dev) |

**Package manager:** `uv` (lock file: `uv.lock`)
**Virtual environment:** `backend/.venv`

---

## Directory Structure

```
backend/
├── agent/
│   ├── agent.py              # ADK agent instances (orchestrator + audio)
│   ├── discovery_agent.py    # Per-turn field extraction agent
│   ├── finalizer_agent.py    # RS compilation agent
│   ├── research_agent.py     # GCS knowledge base retrieval tools
│   ├── prompt.py             # System prompt for the orchestrator
│   └── __init__.py
├── generation/
│   ├── compiler.py           # Chat history → structured RS JSON
│   ├── pdf_export.py         # RS JSON → PDF (reportlab)
│   ├── word_export.py        # RS JSON → DOCX (python-docx)
│   ├── srs_compiler.py       # Legacy SRS format support
│   └── __init__.py
├── bpmn/
│   ├── generator.py          # Gemini prompt → BPMN Mermaid syntax
│   ├── prompts.py
│   └── __init__.py
├── dataflow/
│   ├── generator.py          # Gemini prompt → Dataflow Mermaid syntax
│   ├── prompts.py
│   └── __init__.py
├── context/
│   ├── extractor.py          # Uploaded file → extracted context (Gemini vision)
│   ├── prompts.py
│   └── __init__.py
├── firestore/
│   ├── writer.py             # Firestore read/write for all session data
│   └── __init__.py
├── gcs/
│   ├── connector.py          # GCS bucket I/O and knowledge base keyword search
│   └── __init__.py
├── observability/
│   ├── callbacks.py          # ADK before/after hooks for logging
│   ├── cost.py               # Per-turn token and USD cost tracking
│   ├── metrics.py            # OpenTelemetry metric definitions
│   ├── safety.py             # Jailbreak and adversarial input detection
│   ├── safety_anomalies.py   # BigQuery-backed anomaly detection
│   ├── tracing.py            # Distributed tracing setup
│   ├── turns.py              # Turn-level metrics aggregation
│   ├── redteam/
│   │   └── run_redteam.py    # Adversarial testing harness
│   └── __init__.py
├── privacy/
│   ├── redactor.py           # PII redaction rules applied to stored data
│   └── __init__.py
├── prompts/
│   ├── agent.py              # Orchestrator persona system prompt
│   ├── bpmn.py               # BPMN generation prompt
│   ├── dataflow.py           # Dataflow generation prompt
│   ├── context.py            # File context extraction prompt
│   ├── srs.py                # RS compilation prompt
│   └── __init__.py
├── scripts/
│   └── generate_frontend_schema.py   # Codegen: field_schema.py → rsSchema.ts
├── tests/
│   ├── conftest.py
│   ├── test_agent_prompts.py
│   ├── test_api_integration.py
│   ├── test_compiler.py
│   ├── test_diagram_prompts.py
│   ├── test_e2e_smoke.py
│   ├── test_finalizer_agent.py
│   ├── test_observability_*.py
│   ├── test_pdf_export.py
│   ├── test_one_field_workflow.py
│   └── __init__.py
├── main.py                   # FastAPI application entry point
├── field_schema.py           # CANONICAL RS field definitions (single source of truth)
├── config.py                 # All environment config loaded once at startup
├── admin_sessions.py         # Admin API: list/get sessions and metrics
├── answer_classifier.py      # Detects when user directly answers a field question
├── answer_quality.py         # Scores quality of extracted field answers
├── audio_websocket.py        # Gemini Live API WebSocket handler (voice mode)
├── direct_field_context.py   # Augments user messages with direct-input field context
├── session_bridge.py         # Session state management helpers
├── solution_configs.py       # Preset solution architecture configurations
├── logger.py                 # Centralized logging setup
├── utils.py                  # Miscellaneous utilities
├── requirements.txt          # Pinned dependencies (generated from uv.lock)
├── .env.example              # Environment variable template
└── Dockerfile                # Python 3.12-slim container
```

---

## Environment Variables

Copy `backend/.env.example` to `backend/.env`.

| Variable | Required | Description |
|---|---|---|
| `GOOGLE_API_KEY` | Yes | Gemini API key (direct, not Vertex AI) |
| `GOOGLE_CLOUD_PROJECT` | Yes | GCP project ID |
| `GOOGLE_CLOUD_REGION` | Yes | GCP region (e.g., `europe-west4`) |
| `GCS_BUCKET_NAME` | Yes | Cloud Storage bucket for sessions and knowledge base |
| `FIRESTORE_COLLECTION` | Yes | Firestore collection name (e.g., `srs_sessions`) |
| `FIRESTORE_DATABASE` | Yes | Firestore database ID |
| `ADMIN_BEARER_TOKEN` | Yes | Static bearer token for the admin API |
| `APP_ENV` | No | `development` / `staging` / `production` (default: `development`) |
| `BIGQUERY_DATASET` | No | BigQuery dataset for observability (default: `observability`) |
| `GOOGLE_APPLICATION_CREDENTIALS` | In containers | Path to GCP service account JSON |

---

## Models

All models are configured in `config.py`:

| Agent | Model | Reason |
|---|---|---|
| Orchestrator | `gemini-2.5-pro-preview` | Large context window; holds full conversation history |
| Finalizer | `gemini-2.5-pro-preview` | Complex synthesis from long input |
| Discovery | `gemini-2.0-flash-lite` | Fast, cheap; runs after every turn |
| Research | `gemini-2.0-flash-lite` | Fast retrieval from GCS knowledge base |
| Audio | `gemini-2.0-flash-live-001` | Bidirectional streaming for voice mode |
| BPMN / Dataflow | `gemini-2.0-flash-lite` | Diagram syntax generation |

---

## Field Schema (`field_schema.py`)

This is the **single source of truth** for every RS field. All other systems (backend logic, frontend UI) derive from it.

### Sections (6 total)

| # | Section Name |
|---|---|
| 1 | Identity & Current State |
| 2 | Target State |
| 3 | Value & ROI |
| 4 | Priority & Risk |
| 5 | Technical Context |
| 6 | Additional |

### Fields (22+ total)

Each field is defined with:

| Attribute | Type | Description |
|---|---|---|
| `label` | str | Human-readable display name |
| `required` | bool | Whether field is mandatory for a complete RS |
| `section` | int | Section number (1–6) |
| `direct_input` | bool | User can fill this directly (not AI-extracted) |
| `ai_extractable` | bool | AI can infer value from conversation |
| `multiline` | bool | Textarea vs single-line input |
| `match_terms` | list[str] | Keywords that trigger field detection |
| `validation_mode` | str | `"soft"` (advisory) or `"strict"` (blocking) |
| `expected_shape` | str | Description of what a valid answer looks like |
| `example_good` | str | Positive example for the LLM rubric |
| `rubric` | str | Scoring criteria for answer quality |

### Key Utility Exports

```python
SECTION_TITLES: dict[int, str]
FIELD_SCHEMA: dict[str, FieldDefinition]
EMPTY_FIELDS: dict[str, None]     # Initialized empty state
FIELD_LABELS: dict[str, str]      # key → display label
DIRECT_FIELD_KEYS: list[str]      # Fields user fills directly

def build_sections() -> list[Section]: ...  # Ordered section metadata with nested fields
```

**Deferred answer patterns** (Czech + English): phrases like `"nevím"`, `"don't know"`, `"N/A"`, `"later"` — when detected, the field is marked deferred and skipped in the current turn.

---

## Agent Architecture

The backend uses **Google ADK** as the mandatory orchestration layer. Three specialized agents cooperate:

### 1. Orchestrator Agent (`agent/agent.py`)

```python
rs_agent = Agent(
    name="business_analyst_orchestrator",
    model="gemini-2.5-pro-preview",
    instruction=ORCHESTRATOR_SYSTEM_PROMPT,
    tools=[search_past_analyses, list_knowledge_base_docs],
    before_model_callback=before_model_cb,
    after_model_callback=after_model_cb,
)
```

- Drives the conversational interview across Phase 1, 2, and 3
- Holds the full chat history in context
- Calls research tools to ground responses in historical RS examples
- Emits `[FINALIZING]` and `[GENERATE_RS]` markers to trigger downstream processing

### 2. Discovery Agent (`agent/discovery_agent.py`)

Runs **after every turn** (asynchronously, fire-and-forget):

- Receives the latest user message and conversation excerpt
- Extracts values for any newly answered RS fields
- Returns a partial `discovery_state` dict (field key → extracted value)
- Results are merged into Firestore and broadcast to the frontend sidebar

### 3. Finalizer Agent (`agent/finalizer_agent.py`)

Triggered when the orchestrator emits `[GENERATE_RS]`:

- Reads the full `discovery_state` from Firestore
- Retrieves grounding examples from the GCS knowledge base
- Compiles a complete, structured RS JSON document
- Returns the document for PDF/DOCX export and diagram generation

### Audio Agent (`agent/agent.py`)

A separate ADK agent using `gemini-2.0-flash-live-001`. Handles bidirectional audio streaming over WebSocket via `audio_websocket.py`. Voice input is transcribed and injected into the same session as a regular text message.

---

## API Endpoints (`main.py`)

### Chat

| Method | Path | Description |
|---|---|---|
| `POST` | `/chat/{session_id}` | Send a message; returns an SSE stream of agent response chunks |
| `WS` | `/ws/audio/{session_id}` | WebSocket for bidirectional voice streaming (Gemini Live) |

### Session State

| Method | Path | Description |
|---|---|---|
| `GET` | `/session/{session_id}` | Full session state (conversation, discovery state, workflow phase) |
| `PATCH` | `/session/{session_id}/direct-fields` | Update user-entered direct fields |

### Document Export

| Method | Path | Description |
|---|---|---|
| `GET` | `/session/{session_id}/export/pdf` | Generate and download RS as PDF |
| `GET` | `/session/{session_id}/export/docx` | Generate and download RS as DOCX |

### Diagrams

| Method | Path | Description |
|---|---|---|
| `GET` | `/session/{session_id}/bpmn` | Return Mermaid BPMN diagram string |
| `GET` | `/session/{session_id}/dataflow` | Return Mermaid dataflow diagram string |

### File Upload

| Method | Path | Description |
|---|---|---|
| `POST` | `/session/{session_id}/upload-url` | Return a signed GCS URL for direct browser upload |

### Admin (bearer token required)

| Method | Path | Description |
|---|---|---|
| `GET` | `/admin/sessions` | List all sessions with metadata |
| `GET` | `/admin/sessions/{session_id}` | Full session detail |
| `GET` | `/admin/metrics` | Aggregated cost, token, safety, and fill-rate metrics |

---

## Data Flow

```
User message
    │
    ▼
POST /chat/{session_id}
    │
    ├─► Orchestrator Agent (ADK + Gemini 2.5 Pro)
    │       ├── Research tools (GCS knowledge base search)
    │       └── Streams response chunks → SSE to frontend
    │
    └─► [async, fire-and-forget]
            ├── Discovery Agent → extract field values → Firestore
            ├── Answer Classifier → detect direct answers
            └── Safety callbacks → jailbreak check, cost circuit breaker
```

When `[GENERATE_RS]` is emitted:

```
Finalizer Agent
    ├── Read discovery_state from Firestore
    ├── Retrieve knowledge base examples from GCS
    ├── Compile RS JSON (compiler.py)
    ├── Generate BPMN syntax (bpmn/generator.py)
    ├── Generate Dataflow syntax (dataflow/generator.py)
    ├── Write final_analysis.json to GCS
    └── Update Firestore with compiled RS
```

---

## Firestore Data Model

Collection: `{FIRESTORE_COLLECTION}` (e.g., `srs_sessions`)
Document ID: `{session_id}` (UUID)

| Field | Type | Description |
|---|---|---|
| `conversation` | array | Ordered list of `{role, content, timestamp}` messages |
| `discovery_state` | map | Current extracted RS field values (key → value or null) |
| `direct_fields` | map | User-entered direct field values |
| `deferred_fields` | list | Field keys the user deferred ("answer later") |
| `workflow_state` | string | `discovery` / `generating` / `finalized` |
| `final_analysis` | map | Compiled RS JSON (populated after finalization) |
| `metadata` | map | `session_id`, `created_at`, `user_email`, `cost_usd` |

---

## GCS Structure

Bucket: `{GCS_BUCKET_NAME}`

```
sessions/{session_id}/           # Session artifacts
    uploaded_file.pdf            # User-uploaded files
    final_analysis.json          # Compiled RS
analyses/{session_id}/
    final_analysis.json          # Synonym path for retrieval
knowledge_base/
    templates/                   # Blank RS templates
    examples/                    # Historical RS examples (few-shot grounding)
```

---

## Observability

### Cost Tracking (`observability/cost.py`)

Counts input and output tokens per turn and converts to USD. A circuit breaker halts the session if the cumulative cost exceeds **$5 USD** (configurable in `config.py`).

### Safety (`observability/safety.py`)

Checks every user message for:

- Jailbreak attempts (prompt injection, role-play overrides)
- Off-topic adversarial inputs
- Personal data leakage attempts

Flagged messages are logged and may trigger a warning response from the agent.

### Tracing (`observability/tracing.py`)

OpenTelemetry traces are emitted for:

- Each ADK agent invocation
- Tool calls (GCS, Firestore)
- Document generation pipeline

Traces can be exported to Cloud Trace or any OTLP-compatible backend.

### Anomaly Detection (`observability/safety_anomalies.py`)

BigQuery is queried periodically for sessions with anomalous patterns (unusual token ratios, repeated safety flags, cost spikes). Results are surfaced in the admin dashboard.

### Red-Teaming (`observability/redteam/run_redteam.py`)

A scripted adversarial harness that sends a suite of known attack prompts to the agent and verifies that each one is deflected correctly. Run manually before releases.

---

## Privacy (`privacy/redactor.py`)

PII redaction rules are applied before storing conversation messages in Firestore. Patterns include email addresses, phone numbers, and national ID formats (Czech + international).

---

## Document Generation

### PDF (`generation/pdf_export.py`)

Uses `reportlab`. Renders:

- Title page with project metadata
- All 6 RS sections with their fields
- Formatted tables for structured fields
- Footer with generation timestamp and session ID

### DOCX (`generation/word_export.py`)

Uses `python-docx`. Mirrors the PDF structure with native Word formatting (styles, tables, headings).

### BPMN (`bpmn/generator.py`)

Calls Gemini with the To-Be process description and returns a Mermaid-compatible flowchart/BPMN string. The string is served to the frontend and rendered client-side by Mermaid.js.

### Dataflow (`dataflow/generator.py`)

Same pattern as BPMN but generates a data flow diagram showing systems, data stores, and integrations.

---

## Schema Code Generation

`scripts/generate_frontend_schema.py` reads `field_schema.py` and writes `frontend/app/generated/rsSchema.ts`.

Run after any change to `field_schema.py`:

```bash
cd backend
.venv/Scripts/python scripts/generate_frontend_schema.py   # Windows
.venv/bin/python scripts/generate_frontend_schema.py       # Mac/Linux
```

The generated TypeScript file exports typed constants consumed by `RsLiveTemplate.tsx`.

---

## Running Locally

```bash
cd backend
cp .env.example .env            # fill in all required variables
.venv/Scripts/python -m pip install -r requirements.txt   # Windows
.venv/Scripts/python -m uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

> **Important:** Always use `.venv/Scripts/python` (Windows) or `.venv/bin/python` (Mac/Linux). The global Python interpreter on this machine is a different version and will install packages to the wrong location.

---

## Testing

```bash
cd backend
.venv/Scripts/python -m pytest tests/ -v
```

| Test File | Coverage Area |
|---|---|
| `test_agent_prompts.py` | System prompt content and guardrails |
| `test_api_integration.py` | FastAPI endpoint contracts |
| `test_compiler.py` | RS JSON compilation from mock history |
| `test_diagram_prompts.py` | BPMN and dataflow prompt structure |
| `test_e2e_smoke.py` | Full pipeline from greeting to PDF |
| `test_finalizer_agent.py` | Finalizer agent output structure |
| `test_pdf_export.py` | Non-empty PDF with expected headings |
| `test_one_field_workflow.py` | Single-field extraction end-to-end |
| `test_observability_*.py` | Cost tracking, safety flags, tracing |

---

## Code Quality

| Tool | Config | What it checks |
|---|---|---|
| `ruff` | `pyproject.toml` | Style (E), errors (F), import order (I), line length 120 |
| `mypy` | `pyproject.toml` | Static type checking |
| Pre-commit | `.pre-commit-config.yaml` | Runs ruff + mypy on every commit |

---

## Key Constraints

- **ADK is mandatory.** All agent routing must go through ADK. Do not call Gemini directly from `main.py`.
- **`field_schema.py` is the single source of truth.** Never duplicate field definitions in other files.
- **Always use the venv Python.** The global interpreter is a different version.
- **The agent never makes architecture decisions.** If a user asks the agent to choose a database or tech stack, the agent redirects to business requirements.
- **Model is accessed via `GOOGLE_API_KEY`.** Vertex AI is not used for inference.
