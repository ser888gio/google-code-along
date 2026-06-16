# Software Architecture Documentation

## Overview

The RS (Requirement Specification) Generator is a client–server–cloud application: a **Next.js 16 / React 19** frontend and a **Python 3.12 / FastAPI** backend, each deployed as its own **Cloud Run** service in `europe-west4`. The backend drives an AI requirements-discovery interview using **Google ADK** over **Gemini** models, maintains a live RS field state, and compiles documents, diagrams, and a final analysis. Firestore is the durable operational store, GCS holds files and generated artifacts, and BigQuery serves admin analytics.

## System Context

| External actor / system | Interaction |
|---|---|
| Business user (browser) | Chat-first discovery UI, optional voice mode, RS preview, document/diagram download |
| Admin user | BigQuery-backed session review and metrics screens (IAP / bearer token) |
| Gemini API (direct API key) | All LLM inference — orchestrator, audio, discovery, finalizer, diagram scoring |
| Google Cloud (Firestore, GCS, BigQuery, Cloud Trace/Monitoring) | Persistence, storage, analytics, observability |

## Layers / Services

### Frontend — Next.js workspace (Cloud Run)
- **Purpose**: Two-panel workspace — chat on the left, RS/diagram/analysis panels on the right.
- **Technology**: Next.js App Router, React 19, TypeScript, Tailwind, Mermaid.
- **Entry Points**: `app/page.tsx` (main client workspace), `app/admin/*` (admin screens).
- **Dependencies**: `lib/api.ts` (HTTP/SSE/upload client), `lib/useWebSocket.ts` + audio hooks (voice), `app/generated/rsSchema.ts` (generated field metadata).
- **Interfaces**: Renders SSE chat stream, RS live preview (`RsLiveTemplate`), BPMN/Dataflow panels, `AnalysisPanel`.
- **Location**: `frontend/app/`, `frontend/lib/`.

### API layer — FastAPI routers (Cloud Run)
- **Purpose**: HTTP/SSE/WebSocket surface; one router per domain.
- **Technology**: FastAPI + uvicorn; CORS middleware; global exception handler.
- **Entry Points**: `backend/main.py` wires routers: `chat`, `discovery`, `documents`, `diagrams`, `sessions`, `feedback`, `admin`.
- **Interfaces**: `POST /chat/stream` (SSE), `WS /ws/{user_id}/{session_id}`, `POST /context/extract`, document/diagram/upload/admin endpoints.
- **Location**: `backend/main.py`, `backend/api/*.py`.

### Turn engine + workflow FSM
- **Purpose**: Deterministic per-turn orchestration — classify the latest answer, advance the discovery FSM, persist, and maybe launch the finalizer.
- **Technology**: Plain Python; `answer_classifier.py` / `answer_quality.py` scoring.
- **Entry Points**: `chat_turn.py` (`_prepare_workflow_turn`).
- **Interfaces**: `workflow_state.py` FSM — `DISCOVERY → WRAP_UP → READY_TO_FINALIZE → FINALIZING → COMPLETE`; emits `active_field`, `field_status`, coverage gaps.
- **Location**: `backend/chat_turn.py`, `backend/workflow_state.py`, `backend/answer_*.py`.

### ADK runtime — conversational agents
- **Orchestrator agent** (`gemini-3.1-pro-preview`): drives the discovery interview as an expert IT business consultant; streams text + optional `[FINALIZING]` marker. Tools: `search_vertex_ai` (stub), `search_past_analyses`, `list_knowledge_base_docs`. ADK `InMemorySessionService` holds live conversation events (process-local).
- **Audio agent** (`gemini-3.1-flash-live-preview`): bidirectional voice over WebSocket; PCM frames in/out; transcripts bridged back into the text orchestrator's ADK session.
- **Location**: `backend/agent/agent.py`, `backend/agent/research_agent.py`.

### Background AI pipelines
- **Discovery extraction** (`gemini-3.1-flash-lite`): extracts the 28 canonical RS fields from the transcript; triggered by `POST /context/extract` after each turn and before finalization. Persisted as `discovery_state_json`. (`agent/discovery_agent.py`)
- **Finalizer** (`gemini-3.1-pro-preview`): on `[FINALIZING]`, runs as a background task — synthesizes transcript + fields + readable uploads into `final_analysis.json`. Writes GCS + Firestore. (`agent/finalizer_agent.py`)

### Generation services
- **Documents**: legacy RS markdown compiler, SRS JSON compiler, PDF/DOCX/RS-template DOCX export (`backend/generation/`).
- **Diagrams**: readiness scoring + Mermaid generation — BPMN (score ≥ 90) and Data Flow (score ≥ 70) (`backend/bpmn/`, `backend/dataflow/`). Both require a live ADK session.

### Cross-cutting
- **Persistence**: `firestore/writer.py` (sessions, messages, discovery/workflow state, final analysis, feedback), `gcs/connector.py` (list/read/write/delete).
- **Privacy**: `privacy/redactor.py` redacts PII before persistence and stores original-text hashes.
- **Observability/safety**: `observability/` — model callbacks record tokens/cost/latency; `safety.py` enforces prompt checks + a per-session cost circuit breaker (`$5` default).

## Data Flow

### Flow 1 — Text chat turn (synchronous, SSE)
1. User sends a message; `lib/api.ts` opens `POST /chat/stream`.
2. `api/chat` loads persisted direct/discovery/deferred/workflow state from Firestore.
3. `chat_turn` classifies the latest answer, advances the FSM, and chooses the next `active_field`.
4. The ADK orchestrator (Gemini Pro) streams text back as SSE chunks; research tools may hit GCS.
5. Redacted message + metrics are persisted to Firestore.
6. Frontend appends chunks, updates active field, and (if `[FINALIZING]`) starts polling.

### Flow 2 — Per-turn discovery extraction (async, background)
1. After the turn, frontend calls `POST /context/extract`.
2. Discovery agent (Gemini Flash Lite) extracts all 28 RS fields + completeness.
3. Result merged with `direct_fields_json` and written to Firestore; RS preview updates.

### Flow 3 — Finalization (async, background task)
1. Orchestrator emits `[FINALIZING]`; backend sets `finalization_status="pending"` and launches `run_finalizer()`.
2. Finalizer (Gemini Pro) reads transcript + fields + readable uploads (`.txt/.md/.json/.csv`) from GCS.
3. Writes `analyses/{session_id}/final_analysis.json` to GCS and `final_analysis_json` to Firestore.
4. Frontend polls `GET /analyses/{session_id}` until `status="complete"`, then shows the Analysis tab.

### Flow 4 — Voice mode (bidirectional, WebSocket)
1. Browser opens `WS /ws/{user_id}/{session_id}` and streams PCM audio frames.
2. Audio agent (Gemini Flash Live) returns PCM audio + JSON transcript/status events.
3. Transcripts are injected into the text orchestrator's ADK session for continuity.

## API Contracts (key)

| Method / Path | Purpose |
|---|---|
| `POST /chat/stream` | SSE discovery chat turn |
| `POST /context/extract` | Trigger discovery field extraction |
| `GET /analyses/{session_id}` | Poll finalization status/result |
| `WS /ws/{user_id}/{session_id}` | Voice mode |
| `POST /bpmn/generate`, `POST /dataflow/generate` | Mermaid diagrams (readiness-gated) |
| `POST /document`, `/document/pdf`, `/document/docx`, `/document/rs-template/docx` | Document exports |
| `GET /admin/metrics`, `/admin/sessions[/{id}]` | BigQuery-backed admin review |

## Deployment Mapping

Two Cloud Run services (frontend, backend) in `europe-west4`, built and deployed by GitHub Actions (`.github/workflows/cicd.yaml`) on push to `develop`. Backend secrets injected from Secret Manager (`GOOGLE_API_KEY`, `GCS_BUCKET_NAME`, `FIRESTORE_COLLECTION`, `FIRESTORE_DATABASE`, `ADMIN_BEARER_TOKEN`). Frontend build args: `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_WS_URL`.

## Technical Debt / Concerns

- **ADK sessions are in-memory and process-local.** A backend restart loses live conversation context and in-flight finalization triggers; diagram endpoints then return "session not found".
- `search_vertex_ai` is a stub; retrieval is GCS keyword search only (no vector index).
- Finalizer text-extracts only `.txt/.md/.json/.csv`; PDF/Office uploads are listed, not parsed.
- `downloadPdf()` in the frontend is misnamed — it posts to a DOCX endpoint.
- Some older docs still reference 22 fields; the canonical schema has **28**.
</content>
</invoke>
