# System Architecture

## Overview

The RS Generator is a cloud-native, AI-first application built on Google Cloud Platform. It follows a **client–server–cloud** architecture where a React frontend talks to a Python backend, which orchestrates multiple specialized Gemini AI agents to conduct a conversational requirements interview and produce a structured specification document.

---

## High-Level Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        User's Browser                           │
│                                                                 │
│  ┌─────────────────────────┐   ┌───────────────────────────┐   │
│  │      Chat UI            │   │   RsLiveTemplate Sidebar  │   │
│  │  (Next.js / React)      │◄──│   (live field tracking)   │   │
│  └──────────┬──────────────┘   └───────────────────────────┘   │
└─────────────┼───────────────────────────────────────────────────┘
              │  SSE / WebSocket (streaming)
              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Backend  (Cloud Run)                          │
│                   FastAPI + uvicorn                             │
│                                                                 │
│  ┌────────────────────────────────────────────────────────┐    │
│  │                 Google ADK Orchestration               │    │
│  │                                                        │    │
│  │  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐ │    │
│  │  │ Orchestrator │  │  Discovery   │  │  Finalizer  │ │    │
│  │  │    Agent     │  │    Agent     │  │    Agent    │ │    │
│  │  │ (2.5 Pro)    │  │ (Flash Lite) │  │  (2.5 Pro)  │ │    │
│  │  └──────┬───────┘  └──────┬───────┘  └──────┬──────┘ │    │
│  └─────────┼─────────────────┼─────────────────┼─────────┘    │
│            │                 │                 │               │
│  ┌─────────▼─────────────────▼─────────────────▼─────────┐    │
│  │        Document Generation Pipeline                    │    │
│  │  PDF Export  │  DOCX Export  │  BPMN  │  Dataflow     │    │
│  └────────────────────────────────────────────────────────┘    │
└──────────────────────┬──────────────────────────────────────────┘
                       │
         ┌─────────────┼──────────────────┐
         ▼             ▼                  ▼
  ┌─────────────┐ ┌──────────┐  ┌─────────────────┐
  │  Firestore  │ │   GCS    │  │  Gemini API     │
  │  (sessions) │ │ (files,  │  │  (direct key)   │
  │             │ │  KB)     │  │                 │
  └─────────────┘ └──────────┘  └─────────────────┘
```

---

## Component Breakdown

### Frontend (Cloud Run — Next.js)

| Component | Responsibility |
|---|---|
| `page.tsx` | Root chat UI; session lifecycle management |
| `MessageBubbles` | Render conversation turns with Markdown |
| `RsLiveTemplate` | Real-time RS sidebar; shows all 22 fields with fill status |
| `BpmnPanel` / `DataflowPanel` | Render Mermaid diagrams from backend-generated syntax |
| `FileUpload` | Upload files to GCS via signed URL |
| `lib/api.ts` | All HTTP and SSE communication with the backend |
| `lib/useWebSocket` | Persistent WebSocket for voice mode |
| `app/generated/rsSchema.ts` | Auto-generated field/section metadata (never hand-edited) |

### Backend (Cloud Run — Python/FastAPI)

| Module | Responsibility |
|---|---|
| `main.py` | FastAPI entry point; all HTTP and WebSocket routes |
| `agent/agent.py` | ADK agent instances (orchestrator, audio) |
| `agent/discovery_agent.py` | Per-turn field extraction (async, fire-and-forget) |
| `agent/finalizer_agent.py` | Full RS compilation from conversation |
| `agent/research_agent.py` | GCS knowledge base retrieval tools |
| `field_schema.py` | Single source of truth: 22 fields, 6 sections |
| `generation/` | PDF, DOCX, RS JSON compilation |
| `bpmn/`, `dataflow/` | Diagram syntax generation |
| `firestore/writer.py` | All Firestore read/write operations |
| `gcs/connector.py` | All GCS read/write and knowledge base search |
| `observability/` | Cost tracking, safety, tracing, anomaly detection |
| `privacy/redactor.py` | PII redaction before storage |

---

## AI Agent Design

The backend uses **three specialized agents** orchestrated by Google ADK, each with a distinct role and model:

### Orchestrator Agent

- **Model:** `gemini-2.5-pro-preview`
- **Role:** Drives the conversational interview; persona: *Expert IT Business Consultant*
- **Tools:** `search_past_analyses`, `list_knowledge_base_docs` (GCS retrieval)
- **Output:** Streaming text response + optional markers (`[FINALIZING]`, `[GENERATE_RS]`)
- **Context:** Holds the entire conversation history in its context window

### Discovery Agent

- **Model:** `gemini-2.0-flash-lite`
- **Role:** Extracts RS field values from the latest conversation turn
- **Triggered:** After every user message (asynchronously)
- **Output:** Partial `discovery_state` dict (field key → value)
- **Cost:** Cheap and fast; runs on a short excerpt, not full history

### Finalizer Agent

- **Model:** `gemini-2.5-pro-preview`
- **Role:** Synthesizes all extracted fields + grounding examples into a complete RS JSON
- **Triggered:** When orchestrator emits `[GENERATE_RS]`
- **Input:** Full `discovery_state` + knowledge base examples + conversation summary
- **Output:** Structured RS JSON passed to PDF/DOCX compilers and diagram generators

### Audio Agent

- **Model:** `gemini-2.0-flash-live-001`
- **Role:** Bidirectional voice streaming (speech-to-text + text-to-speech)
- **Transport:** WebSocket (`/ws/audio/{session_id}`)
- **Output:** Transcribed text injected into the main session as a regular chat message

---

## Session Lifecycle

```
1. [CREATED]
   Frontend generates a UUID session ID.
   First message sent → session document created in Firestore.

2. [DISCOVERY]
   Orchestrator interviews the user (Phase 1 & 2).
   After every turn:
     ├── Discovery Agent extracts field values → saved to Firestore
     ├── Frontend sidebar updates from Firestore state
     └── Safety + cost callbacks run

3. [GENERATING]
   Orchestrator emits [GENERATE_RS].
   Finalizer compiles RS JSON.
   BPMN + Dataflow syntax generated.
   All artifacts saved to Firestore and GCS.

4. [FINALIZED]
   User reviews draft RS in chat.
   User can request refinements → Finalizer re-runs (review loop).
   User downloads PDF or DOCX.
```

---

## Data Storage Design

### Firestore (Operational Data)

Firestore is the authoritative store for all session state. The frontend and backend both read/write through `firestore/writer.py`.

```
srs_sessions/
└── {session_id}/
    ├── conversation[]        # Message history [{role, content, ts}]
    ├── discovery_state{}     # Extracted field values (partial)
    ├── direct_fields{}       # User-entered direct inputs
    ├── deferred_fields[]     # Field keys deferred by user
    ├── workflow_state        # "discovery" | "generating" | "finalized"
    ├── final_analysis{}      # Compiled RS JSON
    └── metadata{}            # session_id, created_at, user_email, cost_usd
```

### Google Cloud Storage (Binary & Bulk Data)

GCS stores files that are too large or unstructured for Firestore.

```
{GCS_BUCKET}/
├── sessions/{session_id}/
│   └── {uploaded_files}          # User uploads (PDF, XLSX, images)
├── analyses/{session_id}/
│   └── final_analysis.json       # Compiled RS snapshot
└── knowledge_base/
    ├── templates/                 # Blank RS templates
    └── examples/                  # Historical RS examples (few-shot grounding)
```

### BigQuery (Observability)

Firestore data is streamed or batch-exported to BigQuery views for analytics and anomaly detection. Views are defined in `infra/firestore-bigquery/`.

---

## Streaming Architecture

Two streaming protocols are used:

### Server-Sent Events (SSE) — Chat responses

```
Browser → POST /chat/{session_id}
          ← SSE stream: agent response chunks (text/event-stream)
          ← SSE close: full response received
```

The frontend appends each chunk to the current message bubble in real time.

### WebSocket — Voice mode

```
Browser ↔ WS /ws/audio/{session_id}
```

Audio frames are sent to the backend, forwarded to `gemini-2.0-flash-live-001` via the Gemini Live API, and the response audio frames are streamed back. Transcribed text is also extracted and injected into the text session.

---

## RS Field Schema Architecture

`field_schema.py` is the **single source of truth** for all RS structure. This prevents drift between backend logic and frontend rendering.

```
backend/field_schema.py  (canonical Python definitions)
         │
         └── scripts/generate_frontend_schema.py
                   │
                   └── frontend/app/generated/rsSchema.ts  (auto-generated TypeScript)
                             │
                             └── RsLiveTemplate.tsx  (consumes at runtime)
```

The schema drives:
- Which fields the Discovery Agent looks for
- Which fields appear in the RS sidebar
- Which fields trigger direct-input UI vs. AI extraction
- Validation rules for the Finalizer Agent rubric

---

## Knowledge Base Retrieval

When the Orchestrator or Finalizer runs, it can call `search_past_analyses` to retrieve relevant historical RS examples from GCS. The search is keyword-based (no vector embeddings in MVP):

1. List all files under `knowledge_base/examples/` in GCS
2. Download each file's metadata/summary
3. Score against the current project domain keywords
4. Return the top N matches as context for grounding

This approach improves RS quality by providing few-shot examples of well-formed RS sections.

---

## Observability Architecture

```
Every agent turn
    │
    ├── before_model_callback (ADK hook)
    │       ├── Safety check (jailbreak detection)
    │       ├── Cost circuit breaker check
    │       └── OpenTelemetry span start
    │
    ├── [Gemini API call]
    │
    └── after_model_callback (ADK hook)
            ├── Token count + USD cost update → Firestore
            ├── Turn-level metrics emit → Cloud Monitoring
            └── OpenTelemetry span end
```

Safety anomalies are also detected at the session level via a BigQuery query (`infra/safety/anomalous_sessions.sql`) that runs on a schedule (`infra/safety/anomaly-metric-job.yaml`).

---

## Security Considerations

| Concern | Mitigation |
|---|---|
| GCP credentials | Workload Identity Federation for CI/CD; Cloud Run service account for runtime |
| Gemini API key | Stored in Secret Manager; never committed |
| Admin API | Protected by static bearer token (`ADMIN_BEARER_TOKEN`) |
| PII in conversations | `privacy/redactor.py` redacts before Firestore writes |
| Prompt injection | `observability/safety.py` checks every user message |
| Supply chain | Docker images use hash-pinned Python dependencies (`--require-hashes`) |
| Secrets in repo | `.gitignore` excludes `.env`, `gcp-key.json`, `.venv/` |

---

## Code Quality Pipeline

Every commit triggers pre-commit hooks via `.pre-commit-config.yaml`:

```
trailing-whitespace      → file hygiene
check-yaml / check-toml  → config validation
shellcheck               → shell script linting
ruff-check               → Python lint (PEP8, unused imports)
ruff-format              → Python autoformat
mypy                     → Python type checking
knip                     → TypeScript dead code + unused dependencies
debtmap                  → Technical debt tracking (blocks on Critical)
```

Pull requests on `develop` also run the full test suite via GitHub Actions.

---

## Deployment Pipeline

```
git push → develop branch
    │
    └── GitHub Actions (cicd.yaml)
            │
            ├── Authenticate (Workload Identity Federation)
            ├── docker build + push → backend image (Artifact Registry)
            ├── gcloud run deploy → backend (Cloud Run, europe-west4)
            ├── docker build + push → frontend image (with backend URL baked in)
            └── gcloud run deploy → frontend (Cloud Run, europe-west4)
```

See the [Deployment Guide](deployment.md) for manual deploy instructions and GCP setup.

---

## Technology Decisions & Rationale

| Decision | Rationale |
|---|---|
| **Google ADK (mandatory)** | Hackathon requirement; provides agent orchestration, tool use, and state management |
| **Gemini 2.5 Pro for orchestrator** | Large context window is critical for holding full conversation history during RS generation |
| **Gemini Flash Lite for discovery** | Fast and cheap; runs after every turn so latency and cost matter |
| **Direct Gemini API key (not Vertex AI)** | Simpler setup, no Vertex AI provisioning required; large context window available |
| **Firestore for session state** | Real-time listeners, document model fits session structure, native GCP integration |
| **GCS for files and knowledge base** | Binary storage, signed URLs for direct browser upload, no size limits |
| **GCS keyword search (not Vertex AI Search)** | Simpler, no Vertex AI Search provisioning; sufficient for MVP knowledge base size |
| **reportlab + python-docx** | Mature libraries; no external services required for document generation |
| **Mermaid.js for diagrams** | Client-side rendering, no server infrastructure, wide diagram type support |
| **Cloud Run for hosting** | Serverless, scales to zero, no infrastructure management, native Docker support |
| **field_schema.py as single source of truth** | Prevents field definition drift between backend logic and frontend UI |
