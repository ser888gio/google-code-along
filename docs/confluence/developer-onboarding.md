# Developer Onboarding

## Overview

This guide is the shortest path from a fresh clone to a working local RS Generator environment. It complements the deeper [Architecture](architecture.md), [Frontend](frontend.md), [Backend](backend.md), and [Deployment](deployment.md) pages.

The repository is a monorepo with:

- `backend/`: FastAPI, Google ADK, Gemini, Firestore, GCS, observability, document generation.
- `frontend/`: Next.js 16, React 19, Tailwind CSS 4, Skoda theme, Mermaid rendering, voice-mode browser hooks.
- `infra/`: Cloud Monitoring, BigQuery views, safety jobs, and deployment support.
- `docs/`: planning notes and Confluence-ready documentation.

---

## Prerequisites

Install these before starting:

| Tool | Required version / note |
|---|---|
| Python | 3.12 |
| Node.js | 22 or newer |
| npm | 10.2.3 or newer |
| Docker Desktop | Optional, needed for Docker Compose and image builds |
| Google Cloud CLI | Needed for deployed GCP access and manual deployment |
| Git | Standard repo workflow |
| pre-commit | Recommended before first commit |

You also need access to a GCP project with:

- Gemini API key available as `GOOGLE_API_KEY`.
- Firestore database.
- GCS bucket.
- Optional BigQuery views for observability and safety analysis.
- Optional Cloud Monitoring/Trace for observability.

---

## Repository Layout

```text
/
|-- backend/
|   |-- main.py                         # FastAPI entry point
|   |-- agent/                          # ADK orchestrator, audio, discovery, finalizer agents
|   |-- field_schema.py                 # Canonical 28-field RS schema
|   |-- generation/                     # Markdown, PDF, DOCX, RS-template export
|   |-- firestore/                      # Firestore persistence helpers
|   |-- gcs/                            # GCS connector
|   |-- observability/                  # Metrics, tracing, safety, cost controls
|   `-- tests/
|-- frontend/
|   |-- app/
|   |   |-- page.tsx                    # Main chat workspace
|   |   |-- components/                 # RS preview, diagrams, uploads, analysis
|   |   |-- generated/rsSchema.ts       # Generated from backend field schema
|   |-- lib/                            # API client, WebSocket, audio hooks
|   |-- public/                         # Static image and AudioWorklet processors
|   `-- __tests__/
|-- infra/
|-- docs/
|-- docker-compose.yml
|-- deploy.sh
`-- dev.sh
```

---

## Local Backend Setup

Create and install into the backend virtual environment:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Create `backend/.env` from the example if present, or fill the required variables manually:

```text
GOOGLE_API_KEY=...
GCS_BUCKET_NAME=...
FIRESTORE_COLLECTION=...
FIRESTORE_DATABASE=...
GOOGLE_CLOUD_PROJECT=...
GOOGLE_GENAI_USE_VERTEXAI=0
ALLOWED_ORIGINS=http://localhost:3000
```

Start the backend:

```powershell
cd backend
.venv\Scripts\python.exe -m uvicorn main:app --reload --host 127.0.0.1 --port 8080
```

Health check:

```powershell
Invoke-WebRequest http://127.0.0.1:8080/health
```

Expected JSON:

```json
{"status":"ok"}
```

---

## Local Frontend Setup

Install dependencies:

```powershell
cd frontend
npm ci
```

Create `frontend/.env.local`:

```text
NEXT_PUBLIC_API_URL=http://localhost:8080
NEXT_PUBLIC_WS_URL=ws://localhost:8080
NEXT_SERVER_ACTION_ALLOWED_ORIGINS=localhost:3000
```

Start the frontend:

```powershell
cd frontend
npm run dev
```

Open:

```text
http://localhost:3000
```

Voice mode works only in a secure browser context: HTTPS or localhost.

---

## Docker Compose Setup

The full local stack can also be started with Docker Compose:

```powershell
docker compose up --build
```

Use this path when validating container behavior, production-like environment variable injection, or frontend-to-backend networking. Native dev servers are usually faster for everyday frontend/backend coding.

---

## Schema Generation

`backend/field_schema.py` is the canonical source for RS fields, sections, direct-input metadata, and validation hints.

After changing `backend/field_schema.py`, regenerate the frontend schema:

```powershell
cd backend
.venv\Scripts\python.exe scripts\generate_frontend_schema.py
```

This updates:

```text
frontend/app/generated/rsSchema.ts
```

Do not edit `frontend/app/generated/rsSchema.ts` by hand. Manual changes will be overwritten by the generator.

After generation, check:

- `RsLiveTemplate.tsx` still renders all sections.
- `FIELD_LABEL_KEYS` and locale JSON files include labels for any new fields.
- Direct-chat patterns still match the intended direct-input fields.

---

## Running Tests

Backend:

```powershell
cd backend
.venv\Scripts\python.exe -m pytest tests
```

Frontend:

```powershell
cd frontend
npm test
```

Frontend lint and dead-code checks:

```powershell
cd frontend
npm run lint
npm run knip
```

Pre-commit hooks:

```powershell
pre-commit install
pre-commit run --all-files
```

---

## Common Development Tasks

| Task | Files usually involved |
|---|---|
| Add or rename an RS field | `backend/field_schema.py`, generated `frontend/app/generated/rsSchema.ts`, `RsLiveTemplate.tsx`, `app/i18n/*.json`, tests |
| Change chat behavior | `backend/prompts/agent.py`, `backend/agent/discovery_agent.py`, `backend/answer_classifier.py`, `backend/main.py` |
| Change extraction behavior | `backend/context/extractor.py`, `backend/agent/discovery_agent.py`, `backend/field_schema.py` |
| Change final analysis | `backend/agent/finalizer_agent.py`, `frontend/app/components/AnalysisPanel.tsx`, `frontend/lib/api.ts` |
| Change document export | `backend/generation/*`, `backend/main.py`, frontend download button wiring |
| Change diagram behavior | `backend/bpmn/*`, `backend/dataflow/*`, `frontend/app/components/*Panel.tsx`, `MermaidDiagram.tsx` |
| Change voice mode | `backend/audio_websocket.py`, `backend/main.py`, `frontend/lib/useWebSocket.ts`, audio hooks, AudioWorklet files |

---

## Debugging Checklist

If chat does not work:

1. Check `GET /health`.
2. Confirm `NEXT_PUBLIC_API_URL` points to the backend port.
3. Check backend logs for safety, cost circuit, Gemini, Firestore, or GCS errors.
4. Confirm `GOOGLE_API_KEY` is present and `GOOGLE_GENAI_USE_VERTEXAI=0`.
5. Confirm browser requests are not blocked by CORS. `ALLOWED_ORIGINS` must include the frontend origin.

If the Preview panel does not update:

1. Confirm the chat SSE stream finished.
2. Confirm the frontend called `POST /context/extract`.
3. Check whether extraction hit the cost circuit breaker.
4. Check Firestore writes for `discovery_state_json`.
5. If the backend restarted, remember that ADK sessions are in memory; saved Firestore state may still be available, but live session context is gone.

If document generation fails:

1. Confirm the session has enough field coverage.
2. For RS-template DOCX, inspect saved discovery fields.
3. For legacy PDF/DOCX, confirm the relevant compiler path can reconstruct content from the live ADK session.
4. Check GCS write permissions for `sessions/{session_id}/rs_template.docx`.

If voice mode fails:

1. Use localhost or HTTPS.
2. Grant microphone permission in the browser.
3. Check `NEXT_PUBLIC_WS_URL`.
4. Confirm `/ws/{user_id}/{session_id}` connects.
5. Inspect backend logs for Gemini Live API errors.

---

## Known Local Drift Risks

- Some older comments and planning docs still refer to 22 fields, Gemini 1.5, Vertex AI, or Vercel. The current Confluence docs describe the newer Cloud Run, Gemini API key, and 28-field implementation.
- ADK sessions are in memory. Restarting the backend loses live agent context even though Firestore persists messages and field state.
- `.env.local.example` may lag behind the current frontend variables.
- Uploaded PDF, DOCX, and image files are stored and listed, but the finalizer currently reads only plain text extensions for file content.
