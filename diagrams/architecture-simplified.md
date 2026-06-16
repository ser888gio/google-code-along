# Architecture Overview (Simplified)

## System Summary

The RS Generator turns a rough business idea into a structured Requirement Specification through an AI-guided discovery chat. A Next.js frontend talks to a FastAPI backend that runs Google ADK + Gemini agents; Firestore, GCS, and BigQuery provide persistence and analytics.

## Major Components

### Frontend (Next.js / React)
**Purpose**: Chat workspace, live RS preview, diagram/analysis panels, and voice mode.
**Contains**: `page.tsx`, `RsLiveTemplate`, BPMN/Dataflow/Analysis panels, `lib/api.ts`, admin screens.

### Backend API (FastAPI on Cloud Run)
**Purpose**: HTTP/SSE/WebSocket surface and turn orchestration.
**Contains**: domain routers (`chat`, `discovery`, `documents`, `diagrams`, `sessions`, `feedback`, `admin`), the workflow FSM, classifiers, and generation services.

### Conversational Agents (Google ADK + Gemini)
**Purpose**: Run the discovery interview and voice conversation.
**Contains**: Orchestrator agent (Gemini Pro), Audio agent (Gemini Flash Live).

### Background AI Pipelines (Gemini)
**Purpose**: Per-turn field extraction and final-analysis synthesis.
**Contains**: Discovery extractor (Gemini Flash Lite), Finalizer (Gemini Pro).

### Firestore (Operational Data)
**Purpose**: Durable session state — messages, RS fields, workflow state, final analysis, feedback.

### Cloud Storage (GCS)
**Purpose**: Uploaded files, generated RS-template DOCX, `final_analysis.json`, and the knowledge base.

### Gemini API (LLM Inference)
**Purpose**: All model calls via direct API key (Vertex AI mode is off).

### BigQuery (Admin Analytics)
**Purpose**: Flattened message/feedback views powering admin metrics and session review.

## Data Flow

1. User chats in the browser → `POST /chat/stream` (SSE) to the backend API.
2. Backend advances the workflow FSM and streams the Orchestrator agent's reply from Gemini.
3. Each turn is persisted to Firestore; a background Discovery extractor updates the 28 RS fields.
4. When discovery is ~complete, the Orchestrator emits `[FINALIZING]`; the Finalizer writes `final_analysis.json` to GCS + Firestore.
5. Frontend polls `GET /analyses/{id}` and renders the analysis; admin screens read BigQuery views.

## Key Interactions

| From | To | What |
|------|-----|------|
| User | Frontend | Chat + voice |
| Frontend | Backend API | SSE chat, REST, WebSocket |
| Backend API | Gemini API | Orchestrator / agent inference |
| Background pipelines | Firestore + GCS | Persist fields & final analysis |
| Backend API | Firestore / GCS | Session state, files, artifacts |
| Admin | BigQuery | Metrics & session review |
</content>
