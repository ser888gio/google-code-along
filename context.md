# Project Context

Last updated: 2026-06-10

## Purpose

This repository is the AI-assisted Requirement Specification (RS) Generator. It helps business users turn a rough idea into a structured RS document through a guided discovery conversation, live field extraction, diagram generation, and DOCX/PDF-style export flows.

The user-facing assistant should behave like an expert IT business consultant: professional, patient, clear, and business-focused. It should gather requirements, clarify contradictions, and avoid making implementation or architecture decisions on behalf of the user.

## Product Shape

- Main workflow: chat-first discovery interview for current state, target state, requirements, risks, technical context, and additional information.
- Live RS preview: the frontend shows canonical RS fields as the conversation progresses.
- Finalization: the backend synthesizes chat history, discovered fields, uploaded text-like files, and knowledge-base context into final analysis data.
- Outputs: RS template DOCX, legacy document exports, BPMN-style Mermaid diagrams, data flow diagrams, final analysis, admin review views, and feedback capture.
- Persistence: Firestore stores sessions, messages, extracted fields, workflow state, final analysis, and feedback. GCS stores uploads, generated artifacts, knowledge base documents, and final analysis JSON.

## Architecture

The project is a monorepo with a Python/FastAPI backend and a Next.js frontend.

```text
frontend/       Next.js 16, React 19, TypeScript, Tailwind, Mermaid, Skoda UI provider
backend/        Python 3.12, FastAPI, Google ADK, Gemini API, Firestore, GCS
docs/           More complete architecture, backend, frontend, deployment, and API docs
infra/          Monitoring, Firestore to BigQuery views, safety/anomaly jobs
scripts/        Repo maintenance scripts
```

Important implementation docs:

- `docs/confluence/architecture.md`: system architecture and data flow.
- `docs/confluence/backend.md`: backend modules, endpoints, config, and constraints.
- `docs/confluence/frontend.md`: frontend routes, components, API client, and UI caveats.
- `backend/AGENTS.md`: registry of backend LLM agents, direct Gemini calls, model constants, and call flow.
- `CLAUDE.md`: older project and persona notes. Some details are stale; prefer implementation docs and code when they differ.

## Canonical Sources

- `backend/field_schema.py` is the single source of truth for the RS schema. It currently defines 28 fields across 6 sections.
- `frontend/app/generated/rsSchema.ts` is generated from `backend/field_schema.py`. Do not edit it by hand.
- `backend/config.py` is the source for model names, environment variables, GCS prefixes, markers, and runtime constants.
- `frontend/lib/api.ts` is the central browser API client for backend HTTP, SSE, upload, document, diagram, feedback, and admin calls.
- `frontend/app/page.tsx` is the main chat workspace and session lifecycle surface.
- `backend/main.py` wires the FastAPI app and routers. The route implementations live under `backend/api/`.
- Accepted RS field state distinguishes user-accepted values from AI-extracted suggestions. DOCX export should use accepted values only. The acceptance policy belongs in `backend/field_schema.py` as an `acceptance_mode` field and is generated to the frontend with the rest of the RS schema. Persist user decisions in one rich `rs_field_state_json` Firestore field containing accepted values and dismissed suggestions, with no read-through fallback from legacy `direct_fields_json`. AI suggestions require individual user acceptance; do not add bulk accept.

## Backend Summary

The backend is a FastAPI service that uses Google ADK for the main chat and audio agents, plus direct Gemini calls for supporting pipelines.

Key areas:

- `backend/api/`: routers for chat, discovery, documents, diagrams, sessions, feedback, and admin.
- `backend/agent/agent.py`: ADK orchestrator and audio agent definitions.
- `backend/agent/prompt.py`: user-facing business-consultant system prompt.
- `backend/agent/discovery_agent.py`: field extraction and one-field workflow helpers.
- `backend/answer_classifier.py` and `backend/answer_quality.py`: per-turn answer classification and quality scoring.
- `backend/agent/finalizer_agent.py`: final analysis generation.
- `backend/generation/`: legacy compiler, SRS compiler, DOCX and PDF export.
- `backend/bpmn/` and `backend/dataflow/`: diagram readiness scoring and Mermaid generation.
- `backend/firestore/writer.py`: persisted session, field, workflow, analysis, and feedback state.
- `backend/gcs/connector.py`: GCS reads, writes, uploads, knowledge-base listing, and past-analysis lookup.
- `backend/observability/`: metrics, tracing, callbacks, safety checks, cost tracking, anomaly support.
- `backend/privacy/redactor.py`: PII redaction before persistence.

Current model constants live in `backend/config.py`:

- Orchestrator and finalizer: `gemini-3.1-pro-preview`
- Audio: `gemini-3.1-flash-live-preview`
- Discovery, BPMN, dataflow, SRS compiler, and research constant: `gemini-3.1-flash-lite`

## Frontend Summary

The frontend is a Next.js app using the App Router. The main route is a two-panel workspace: chat on the left and RS/document/diagram/analysis panels on the right.

Key areas:

- `frontend/app/page.tsx`: main client workspace, streaming chat handling, session state, finalization polling, uploads, voice mode, and feedback.
- `frontend/app/components/RsLiveTemplate.tsx`: live RS preview driven by generated schema metadata.
- `frontend/app/components/BpmnPanel.tsx` and `DataflowPanel.tsx`: diagram requests and rendering.
- `frontend/app/components/AnalysisPanel.tsx`: finalizer output display.
- `frontend/app/admin/`: BigQuery-backed admin metrics and session review pages.
- `frontend/app/i18n/`: small Czech/English locale layer.
- `frontend/lib/api.ts`: typed fetch/SSE/upload helpers.
- `frontend/lib/useWebSocket.ts`, `useAudioRecorder.ts`, and `useAudioPlayer.ts`: voice mode.

Known frontend caveats:

- Some newer RS fields may fall back to English labels because translation maps lag the generated schema.
- `downloadPdf()` is a stale function name that posts to a DOCX endpoint.
- The catch-all rewrite in `next.config.ts` is broad, while browser API calls usually target `NEXT_PUBLIC_API_URL` directly.

## Data And Integrations

Firestore is the durable operational store. Session documents contain redacted messages, discovery state JSON, direct/deferred field JSON, workflow state JSON, finalization status, final analysis JSON, session status, and compatibility SRS snapshot fields.

GCS paths:

```text
sessions/{session_id}/{filename}           User uploads
sessions/{session_id}/rs_template.docx     Generated RS template DOCX
analyses/{session_id}/final_analysis.json  Finalizer output
knowledge_base/{category}/                 Templates, guidelines, examples
```

BigQuery views under `infra/firestore-bigquery/` support admin metrics and session review. Monitoring and safety assets live under `infra/monitoring/` and `infra/safety/`.

## Local Development

Backend:

```powershell
cd backend
..\.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

If the virtual environment is inside `backend/.venv`, use:

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

Frontend:

```powershell
cd frontend
npm install
npm run dev
```

Useful checks:

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests -v

cd frontend
npm test
npm run lint
npm run knip

pre-commit run --all-files
```

## Important Constraints

- Do not edit `frontend/app/generated/rsSchema.ts` directly. Change `backend/field_schema.py` and regenerate.
- Keep the assistant persona business-focused. The assistant should not design the user's system architecture for them.
- Direct Gemini API key mode is used; Vertex AI Search is currently removed/stubbed.
- ADK sessions are process-local and in-memory. Firestore persists durable state, but backend restarts can lose live ADK session context and in-flight generation triggers.
- Finalization reads text-like uploaded files (`.txt`, `.md`, `.json`, `.csv`) but currently lists rather than parses PDFs and Office files in that path.
- Local development requires `GOOGLE_API_KEY`; production/staging also need GCP project, GCS bucket, Firestore collection, and Firestore database config.
- Admin endpoints require IAP or `ADMIN_BEARER_TOKEN` in production/staging.

## Known Drift Risks

- Older docs and comments may still refer to 22 fields; the current schema has 28.
- Some docs mention Vertex AI; current model calls use the direct Gemini API key and GCS-backed retrieval.
- `.env.example` and `.env.local.example` may lag the variables used by code.
- Pre-commit uses Ruff, mypy, Knip, Biome, ShellCheck, typos, gitleaks, and debtmap; local tool availability can affect hook results.
