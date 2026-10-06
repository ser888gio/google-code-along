# Coding Agent Instructions

Last updated: 2026-06-10

## Start Here

Before editing, read `context.md` and then the most relevant deeper doc:

- Backend work: `docs/confluence/backend.md` and `backend/AGENTS.md`
- Frontend work: `docs/confluence/frontend.md`
- Cross-system work: `docs/confluence/architecture.md`
- Deployment or cloud resources: `docs/confluence/deployment.md` and `infra/`

Prefer the current code over older planning docs when they conflict. `CLAUDE.md` is useful for product intent and persona, but it contains stale details.

## Agent Operating Rules

- Keep changes scoped to the requested behavior.
- Preserve user changes in the working tree. Check `git status --short` before broad edits.
- Use existing patterns before adding new abstractions.
- Do not introduce secrets, keys, credentials, tokens, real customer data, or raw PII into the repo.
- Keep the user-facing RS assistant persona business-focused and jargon-free.
- Do not make the RS assistant propose implementation architecture, choose a database, or write code for the end user.
- Do not edit generated files unless the task is specifically about generated output and the generator cannot be changed.

## Project-Specific Rules

- `backend/field_schema.py` is the RS schema source of truth.
- `frontend/app/generated/rsSchema.ts` is generated. Regenerate it after changing `backend/field_schema.py`.
- Model names and runtime constants belong in `backend/config.py`.
- API routes are organized under `backend/api/`; keep new endpoint behavior there rather than growing `main.py`.
- Frontend API calls should go through `frontend/lib/api.ts` unless there is a strong local reason.
- Frontend UI text should consider the existing Czech/English i18n layer.
- Voice mode relies on AudioWorklets and WebSocket endpoints; test browser behavior carefully after related changes.
- Mermaid rendering is handled through `MermaidDiagram.tsx`; avoid bypassing it for BPMN/dataflow panels.

## Commands

Backend test run:

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests -v
```

Backend app:

```powershell
cd backend
..\.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

If the venv is nested in `backend/.venv`:

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

Frontend app:

```powershell
cd frontend
npm run dev
```

Frontend checks:

```powershell
cd frontend
npm test
npm run lint
npm run knip
```

Generate frontend RS schema after backend schema changes:

```powershell
cd backend
..\.venv\Scripts\python.exe scripts\generate_frontend_schema.py
```

Repo checks:

```powershell
pre-commit run --all-files
```

## Backend Map

- `backend/main.py`: FastAPI app setup, middleware, health route, router includes.
- `backend/api/chat.py`: text chat and SSE streaming.
- `backend/api/discovery.py`: extraction and field state endpoints.
- `backend/api/documents.py`: document generation endpoints.
- `backend/api/diagrams.py`: BPMN and dataflow endpoints.
- `backend/api/sessions.py`: history, uploads, Firestore session data.
- `backend/api/feedback.py`: message and session feedback.
- `backend/agent/agent.py`: ADK text and audio agent objects.
- `backend/prompts/agent.py`: orchestrator and agent system prompts.
- `backend/agent/discovery_agent.py`: extraction and workflow helpers.
- `backend/agent/finalizer_agent.py`: final analysis pipeline.
- `backend/agent/research_agent.py`: GCS-backed research tools and Vertex stub.
- `backend/field_schema.py`: canonical RS fields.
- `backend/firestore/writer.py`: persistence helpers.
- `backend/gcs/connector.py`: storage helpers.
- `backend/observability/`: tracing, metrics, callbacks, cost, and safety.
- `backend/privacy/redactor.py`: PII redaction.

## Frontend Map

- `frontend/app/page.tsx`: main chat workspace and session orchestration.
- `frontend/app/components/RsLiveTemplate.tsx`: live RS field preview and direct inputs.
- `frontend/app/components/FileUpload.tsx`: upload UI.
- `frontend/app/components/BpmnPanel.tsx`: BPMN generation panel.
- `frontend/app/components/DataflowPanel.tsx`: dataflow generation panel.
- `frontend/app/components/AnalysisPanel.tsx`: final analysis view.
- `frontend/app/generated/rsSchema.ts`: generated RS schema.
- `frontend/app/i18n/`: Czech/English translations and locale context.
- `frontend/lib/api.ts`: backend client functions.
- `frontend/lib/useWebSocket.ts`: voice WebSocket hook.
- `frontend/lib/useAudioRecorder.ts` and `useAudioPlayer.ts`: PCM audio pipeline.

## Verification Guidance

- Backend API or workflow changes: run focused backend pytest files first, then broader tests if risk is high.
- Schema changes: regenerate `frontend/app/generated/rsSchema.ts`, then run backend schema/workflow tests and frontend tests touching `RsLiveTemplate`.
- Frontend UI changes: run Jest tests and, when a browser is available, inspect the local app for layout, streaming states, and mobile behavior.
- Document or diagram changes: test the relevant endpoint path and verify generated content is non-empty and structurally valid.
- Observability, privacy, auth, or persistence changes: review failure modes carefully and avoid logging raw sensitive data.

## Common Pitfalls

- The project has documentation drift. Trust `backend/config.py`, `backend/field_schema.py`, `frontend/package.json`, and the implementation when docs disagree.
- Some references still say 22 fields; current generated schema is 28 fields.
- ADK session state is in-memory. Firestore state does not fully restore every live ADK runner context after restart.
- `search_vertex_ai` is a compatibility stub; current research is GCS-backed.
- PDF and Office uploads are not text-extracted in the finalizer path today.
- `downloadPdf()` in the frontend is misnamed and currently downloads DOCX.
- Frontend environment examples may not list every runtime variable used by code.
