# Whole-App Architecture

The RS Generator is a cloud-native, AI-first application on Google Cloud Platform, deployed as **two Cloud Run services** in `europe-west4`: a Next.js frontend and a Python/FastAPI backend.

## Components

- **Business User** — interacts through the browser over HTTPS.
- **Frontend Service (Cloud Run)** — Next.js 16 / React 19 / TypeScript two-panel workspace.
- **Backend Service (Cloud Run)** — FastAPI + uvicorn (Python 3.12) hosting the Google ADK runtime.
- **Firestore** — durable session, discovery, workflow, final-analysis, and feedback state.
- **Cloud Storage (GCS)** — uploads (`sessions/`), generated artifacts, `analyses/`, and `knowledge_base/`.
- **Gemini API** — direct API-key usage (`GOOGLE_GENAI_USE_VERTEXAI=0`), not Vertex AI.
- **BigQuery Views** — Firestore export for observability/safety analytics.
- **Cloud Trace + Monitoring** — OpenTelemetry-exported spans and metrics.
- **Secret Manager** — injects `GOOGLE_API_KEY`, GCS bucket, Firestore collection/database into the backend.

## Runtime data flow

1. Browser → Frontend over HTTPS.
2. Frontend → Backend via **SSE** `POST /chat/stream`, HTTP (uploads/discovery/diagrams/docs/feedback), and **WebSocket** `/ws/{user}/{session}` for voice.
3. Backend → Gemini (`generate_content` / Live), Firestore, GCS, and Cloud Trace/Monitoring.
4. Firestore → BigQuery export views.

## Deploy flow

`git push develop` → **GitHub Actions** (`.github/workflows/cicd.yaml`) authenticates via Workload Identity Federation → builds/pushes images to **Artifact Registry** → deploys both Cloud Run services. A dashboard-update step is included when `infra/monitoring/dashboard.json` changes.
