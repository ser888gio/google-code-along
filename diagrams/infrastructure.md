# Infrastructure Documentation

## Overview

The RS Generator runs entirely on **Google Cloud Platform** in project `vw-skda-fskoda-sandbox-jzf`, region `europe-west4`. Two containerized **Cloud Run services** (backend + frontend) serve traffic, two **Cloud Run Jobs** run scheduled safety tasks, and the data plane is **Firestore + Cloud Storage + BigQuery**. Images are built and deployed by **GitHub Actions** into **Artifact Registry**, authenticated via **Workload Identity Federation** (no static keys), with runtime secrets in **Secret Manager**. The only external dependency is the **Gemini API** (direct API key).

## Components

### Compute

- **`business-persona-ai-backend`** — Cloud Run service. Container `python:3.12-slim`, runs `uvicorn main:app` on port **8080**. Installs hash-pinned deps (`pip install --require-hashes`). `backend/Dockerfile`, `.github/workflows/cicd.yaml:87-104`.
- **`business-persona-ai-frontend`** — Cloud Run service. Multi-stage `node:22-alpine` build producing a Next.js **standalone** server (`node server.js`) on port **3000**. `frontend/Dockerfile`, `.github/workflows/cicd.yaml:136-144`.
- **`rs-safety-anomaly-metrics`** — Cloud Run **Job** (`kind: Job`). Reuses the backend image; runs `python -m observability.safety_anomalies`, scanning BigQuery over a 36h lookback and writing the `safety_anomalous_sessions` table. `infra/safety/anomaly-metric-job.yaml`.
- **`rs-redteam-daily`** — Cloud Run **Job**. Reuses the backend image; runs `python -m observability.redteam.run_redteam` against the staging backend URL with a required block rate of 1.0. `infra/safety/redteam-job.yaml`.

### Data Stores

- **Firestore** — operational store (`FIRESTORE_DATABASE` / `FIRESTORE_COLLECTION`): sessions, redacted messages, discovery/workflow state, final analysis, feedback. Secrets injected at runtime. `cicd.yaml:102-103`.
- **Cloud Storage (GCS)** — bucket `GCS_BUCKET_NAME`: user uploads, generated `rs_template.docx`, `analyses/{id}/final_analysis.json`, and the `knowledge_base/` corpus. `cicd.yaml:101`.
- **BigQuery** — dataset `observability` (`BIGQUERY_DATASET`). Views `messages_view`, `feedback_view` flatten the Firestore export; the `safety_anomalous_sessions` table is written by the anomaly Job. `infra/firestore-bigquery/*.sql`, `cicd.yaml:98`.

### Build & Registry

- **Artifact Registry** — Docker repository `business-persona-ai-repo` in `europe-west4`. Holds `backend:<sha>` and `frontend:<sha>` images. GHA build cache via `type=gha`. `cicd.yaml:16-18,75,129`.

### Networking

- Cloud Run provides managed **HTTPS** endpoints for both services. The browser calls the frontend over HTTPS and the backend directly over **HTTPS + WSS** (voice WebSocket).
- The frontend is built with `NEXT_PUBLIC_API_URL` / `NEXT_PUBLIC_WS_URL` resolved from the backend's Cloud Run URL at deploy time. `cicd.yaml:109-132`.
- Backend CORS is restricted to `ALLOWED_ORIGINS` (`backend/main.py:19-28`).

### Security

- **Workload Identity Federation** — GitHub Actions authenticates with `WIF_PROVIDER` + `SA_EMAIL`; no long-lived service-account keys. `cicd.yaml:45-52`.
- **Secret Manager** — backend secrets `GOOGLE_API_KEY`, `GCS_BUCKET_NAME`, `FIRESTORE_COLLECTION`, `FIRESTORE_DATABASE`, `ADMIN_BEARER_TOKEN` (frontend gets `ADMIN_API_TOKEN`). A pipeline step strips any plaintext `GOOGLE_API_KEY` env var before deploy. `cicd.yaml:79-104,143-144`.
- **Runtime identity** — Cloud Run services use their runtime service account for Firestore/GCS/BigQuery access.
- **Admin protection** — IAP header or bearer token guards `/admin/*`.

### External Services

- **Gemini API** — direct API-key mode (`GOOGLE_GENAI_USE_VERTEXAI=0`); all LLM inference (orchestrator, audio, discovery, finalizer, diagram scoring).
- **GitHub Actions** — CI/CD runner (`ubuntu-latest`).

### Observability

- **Cloud Monitoring** — `infra/monitoring/`: `dashboard.json`, `alert-policies.yaml`, `log-based-metrics.yaml`.
- **Cloud Trace** — OpenTelemetry exporters set up in `backend/observability/tracing.py` (`setup_telemetry`).
- **Firestore → BigQuery** export feeds the `observability` dataset views consumed by admin screens and the safety Job.

## Relationships

| From | To | Protocol / Purpose |
|---|---|---|
| User browser | Frontend service | HTTPS (UI) |
| User browser | Backend service | HTTPS + WSS (chat SSE, REST, voice) |
| Frontend service | Backend service | build-time `NEXT_PUBLIC_API_URL` wiring |
| Backend service | Gemini API | HTTPS (API key from Secret Manager) |
| Backend service | Firestore | gRPC/HTTPS (durable state) |
| Backend service | GCS | HTTPS (uploads, artifacts, KB) |
| Backend service | BigQuery | admin metrics queries |
| Firestore | BigQuery | managed export → views |
| Anomaly Job | BigQuery | read sessions, write `safety_anomalous_sessions` |
| Red-team Job | Backend (staging) | HTTPS probe, asserts block rate |
| Secret Manager | Backend service | secret injection at deploy |
| GitHub Actions | Artifact Registry | push images (WIF auth) |
| GitHub Actions | Cloud Run | deploy services |
| Cloud Run | Cloud Monitoring / Trace | metrics, logs, spans |

## Environment Differences

- **Production** (`develop` → Cloud Run): `APP_ENV=production`, secrets from Secret Manager, WIF auth.
- **Staging**: targeted by the safety Jobs (`APP_ENV=staging`, `REDTEAM_TARGET_URL=https://BACKEND_STAGING_URL`).
- **Local**: `docker-compose.yml` runs backend (8080) + frontend (3000); GCP access via a mounted `gcp-key.json` (`GOOGLE_APPLICATION_CREDENTIALS`). Minimum env is `GOOGLE_API_KEY`.

## Unverified Items

- **Job scheduling**: the Jobs are named `*-daily` and use a lookback window, implying Cloud Scheduler triggers, but no scheduler/cron resource is committed in-repo — UNVERIFIED whether scheduling is managed via Terraform/console outside this repo.
- **Placeholders** (`BACKEND_IMAGE`, `PROJECT_ID`, `DATASET`, `BACKEND_STAGING_URL`) in the Job manifests are substituted by an out-of-repo apply step — UNVERIFIED how they are templated at deploy time.
</content>
