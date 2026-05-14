# Deployment Guide

## Overview

The application consists of two independently deployable services: **backend** and **frontend**. Both are containerized with Docker and deployed to **Google Cloud Run** in the `europe-west4` region.

Automated deployment runs from **GitHub Actions** on every push to the `develop` branch. The workflow is defined in `.github/workflows/cicd.yaml`.

---

## Infrastructure Summary

| Component | Service | Region / Scope |
|---|---|---|
| Backend API | Cloud Run | `europe-west4` |
| Frontend | Cloud Run | `europe-west4` |
| Container Registry | Artifact Registry | `europe-west4` |
| Session Storage | Firestore | Same GCP project |
| File Storage | Cloud Storage | Same GCP project |
| Runtime Secrets | Secret Manager | Same GCP project |
| Observability | Cloud Logging, Cloud Trace, Cloud Monitoring, BigQuery | Same GCP project |
| CI/CD | GitHub Actions | GitHub repository |

Current checked-in CI values:

| Setting | Value |
|---|---|
| CI project ID | `vw-skda-fskoda-sandbox-jzf` |
| Artifact Registry repository | `business-persona-ai-repo` |
| Backend Cloud Run service | `business-persona-ai-backend` |
| Frontend Cloud Run service | `business-persona-ai-frontend` |

`deploy.sh` currently uses a different hardcoded project ID: `vw-skda-fhackton-156`. Align this before using the script for the same environment as CI.

---

## Automated Deployment (GitHub Actions)

### Trigger

Every push to the `develop` branch triggers the full CI/CD pipeline defined in `.github/workflows/cicd.yaml`.

### Pipeline Steps

```text
1. Checkout code
2. Authenticate to GCP with Workload Identity Federation
3. Configure Docker for Artifact Registry
4. Build and push backend image
5. Remove any stale plaintext GOOGLE_API_KEY env var from the backend service
6. Deploy backend to Cloud Run with runtime env vars and Secret Manager secrets
7. Build and push frontend image with backend URL build args
8. Deploy frontend to Cloud Run
```

### GCP Authentication

The pipeline uses **Workload Identity Federation**, so GitHub Actions does not need a long-lived service account JSON key. The GitHub repository is federated with a GCP Workload Identity Pool and impersonates a deploy service account.

Required GitHub Actions secrets:

| Secret | Description |
|---|---|
| `WIF_PROVIDER` | Full Workload Identity Provider resource name |
| `SA_EMAIL` | Service account email that the pipeline impersonates |
| `ADMIN_BEARER_TOKEN` | Static bearer token baked into the frontend build for admin API calls |

Required GCP Secret Manager secrets referenced by the workflow:

| Secret Manager secret | Runtime variable |
|---|---|
| `GOOGLE_API_KEY` | `GOOGLE_API_KEY` |
| `GCS_BUCKET_NAME` | `GCS_BUCKET_NAME` |
| `FIRESTORE_COLLECTION` | `FIRESTORE_COLLECTION` |
| `FIRESTORE_DATABASE` | `FIRESTORE_DATABASE` |
| `ADMIN_BEARER_TOKEN` | `ADMIN_BEARER_TOKEN` |

The CI workflow also sets these backend runtime environment variables directly:

```text
GOOGLE_CLOUD_PROJECT=<workflow PROJECT_ID>
APP_ENV=production
BIGQUERY_DATASET=observability
```

### Required CORS Configuration

The frontend browser client calls the backend URL directly through `NEXT_PUBLIC_API_URL`. The backend CORS allow-list defaults to only:

```text
http://localhost:3000
```

For production, set backend `ALLOWED_ORIGINS` to the deployed frontend origin, for example:

```text
ALLOWED_ORIGINS=https://business-persona-ai-frontend-xxxxx-ew.a.run.app
```

If multiple origins are needed, use a comma-separated list:

```text
ALLOWED_ORIGINS=https://frontend.example.com,https://www.frontend.example.com
```

Without this setting, browser requests from the deployed frontend to the deployed backend can fail CORS checks.

### Image Tags

CI images are tagged with the full Git commit SHA (`github.sha`) and pushed to:

```text
europe-west4-docker.pkg.dev/{PROJECT_ID}/{REPOSITORY}/backend:{GITHUB_SHA}
europe-west4-docker.pkg.dev/{PROJECT_ID}/{REPOSITORY}/frontend:{GITHUB_SHA}
```

Manual `deploy.sh` images are tagged as `latest` under service-specific image names:

```text
europe-west4-docker.pkg.dev/{PROJECT_ID}/{SERVICE_NAME}-repo/{SERVICE_NAME}-backend:latest
europe-west4-docker.pkg.dev/{PROJECT_ID}/{SERVICE_NAME}-repo/{SERVICE_NAME}-frontend:latest
```

---

## Manual Deployment (`deploy.sh`)

For ad-hoc deploys:

```bash
bash deploy.sh
bash deploy.sh --frontend-only
```

The script currently:

1. Sets the active GCP project, Cloud Run region, and Cloud Build region.
2. Enables a subset of required Google Cloud APIs.
3. Creates the Artifact Registry repository if needed.
4. Uses **Cloud Build** via `gcloud builds submit` to build and push backend and frontend images.
5. Runs `gcloud run deploy` for each service.

It does **not** build locally with `docker build`; the local Docker daemon is not required for this script.

### Manual Deployment Prerequisites

- `gcloud` CLI installed and authenticated.
- Cloud Build permissions in the target project.
- Artifact Registry repository available or creatable.
- Required APIs enabled.
- Runtime secrets and environment variables configured.
- `ADMIN_BEARER_TOKEN` exported locally if admin auth should work and if the frontend image should receive the admin token build arg.

### Manual Deployment Caveats

The checked-in `deploy.sh` backend deployment currently sets:

```text
GCS_BUCKET_NAME=<PROJECT_ID>-bucket
GOOGLE_CLOUD_PROJECT=<PROJECT_ID>
APP_ENV=production
BIGQUERY_DATASET=observability
ADMIN_BEARER_TOKEN=<optional local env var>
```

Production startup also requires:

```text
GOOGLE_API_KEY
FIRESTORE_COLLECTION
FIRESTORE_DATABASE
```

Add these to the script, pass them with `--set-secrets`, or configure them on the Cloud Run service before relying on manual deploys.

---

## Docker Images

### Backend

The backend Dockerfile:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
COPY . .
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

- Base image: `python:3.12-slim`
- Dependencies are installed with hash verification.
- The app listens on `0.0.0.0:8080`.

### Frontend

The frontend Dockerfile is a three-stage Node 22 Alpine build:

```dockerfile
FROM node:22-alpine AS deps
FROM node:22-alpine AS builder
FROM node:22-alpine AS runner

ARG NEXT_PUBLIC_API_URL=http://localhost:8080
ARG NEXT_PUBLIC_WS_URL=ws://localhost:8080
ARG NEXT_PUBLIC_ADMIN_API_TOKEN=

EXPOSE 3000
CMD ["node", "server.js"]
```

- Base image: `node:22-alpine`
- `NEXT_PUBLIC_*` values are build args baked into the Next.js client bundle during `next build`.
- Output is a Next.js standalone runtime image.
- The container listens on port `3000`.

Important Cloud Run note: Cloud Run sends requests to the configured container port and injects the `PORT` environment variable. The default service port is `8080` unless configured otherwise. Because this frontend image listens on `3000`, deploy the frontend Cloud Run service with container port `3000` or update the runtime to honor Cloud Run's `PORT`.

---

## Local Development

### Option 1: Full Docker Compose Stack

```bash
cp backend/.env.example backend/.env
# Fill in backend/.env.
# Place a GCP service account JSON or ADC-compatible credentials at ./gcp-key.json.
docker-compose up --build
```

Services:

| Service | Local URL |
|---|---|
| Backend | `http://localhost:8080` |
| Frontend | `http://localhost:3000` |

The backend container mounts `gcp-key.json` read-only at `/tmp/gcp-credentials.json` and sets `GOOGLE_APPLICATION_CREDENTIALS` to that path.

### Option 2: Native Dev Servers

```bash
bash dev.sh
```

Current `dev.sh` starts:

```bash
cd backend && uvicorn main:app --reload
cd frontend && npm run dev
```

Bare `uvicorn main:app --reload` defaults to `http://127.0.0.1:8000`. This matches the current `frontend/.env.local.example`, which sets:

```text
NEXT_PUBLIC_API_URL=http://localhost:8000
```

If you want native local development on port `8080`, start the backend manually:

```bash
cd backend
cp .env.example .env
.venv/Scripts/python -m uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

Then configure the frontend with:

```text
NEXT_PUBLIC_API_URL=http://localhost:8080
NEXT_PUBLIC_WS_URL=ws://localhost:8080
```

Frontend:

```bash
cd frontend
cp .env.local.example .env.local
npm install
npm run dev
```

---

## Cloud Run Configuration

Both services are deployed as Cloud Run services.

| Setting | Backend | Frontend |
|---|---|---|
| Container port | `8080` | `3000` |
| Region | `europe-west4` | `europe-west4` |
| Min instances | `0` by default | `0` by default |
| Max instances | Should be set deliberately | Should be set deliberately |
| Memory | Size for ADK/Gemini workload | `512 MiB` default unless changed |
| CPU | `1` default unless changed | `1` default unless changed |
| Allow unauthenticated | Yes for the public app | Yes for the public app |

Recommended backend operational settings:

- Set `ALLOWED_ORIGINS` to the frontend origin.
- Set a request timeout long enough for SSE streaming and finalization-triggering turns.
- Keep backend scaling conservative until ADK sessions are persistent. The backend currently uses in-memory ADK sessions; a restart or routing related requests to a different instance can lose live agent context.
- Consider `max-instances=1` for demos that depend on uninterrupted live sessions, or implement persistent ADK sessions before scaling horizontally.

Backend runtime configuration:

| Variable | Source | Notes |
|---|---|---|
| `GOOGLE_API_KEY` | Secret Manager | Required in production |
| `GCS_BUCKET_NAME` | Secret Manager | Required in production |
| `FIRESTORE_COLLECTION` | Secret Manager | Required in production |
| `FIRESTORE_DATABASE` | Secret Manager | Required in production |
| `ADMIN_BEARER_TOKEN` | Secret Manager | Required for production admin bearer auth |
| `GOOGLE_CLOUD_PROJECT` | Env var | Required for Firestore, BigQuery, trace links |
| `APP_ENV` | Env var | Set to `production` |
| `BIGQUERY_DATASET` | Env var | Defaults to `observability` |
| `ALLOWED_ORIGINS` | Env var | Required for deployed frontend CORS |
| `COST_CIRCUIT_BREAKER_USD` | Env var | Optional; defaults to `5.0` |

Frontend build-time configuration:

| Build arg | Notes |
|---|---|
| `NEXT_PUBLIC_API_URL` | Backend Cloud Run HTTPS URL |
| `NEXT_PUBLIC_WS_URL` | Backend WebSocket URL, usually `wss://<backend-host>` |
| `NEXT_PUBLIC_ADMIN_API_TOKEN` | Admin bearer token sent by frontend admin pages |

Because these are `NEXT_PUBLIC_*` values, they are visible in the browser bundle. Do not put private server-only secrets in frontend build args.

---

## GCP Services Setup (One-Time)

Enable the required APIs before first deployment:

```bash
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com \
  firestore.googleapis.com \
  storage.googleapis.com \
  secretmanager.googleapis.com \
  generativelanguage.googleapis.com \
  bigquery.googleapis.com \
  logging.googleapis.com \
  monitoring.googleapis.com \
  cloudtrace.googleapis.com
```

### Artifact Registry

```bash
gcloud artifacts repositories create {REPOSITORY} \
  --repository-format=docker \
  --location=europe-west4
```

### Firestore

```bash
gcloud firestore databases create \
  --database={FIRESTORE_DATABASE} \
  --location=europe-west4
```

The app stores session documents in the configured `FIRESTORE_COLLECTION` and feedback in a top-level `feedback` collection.

### Cloud Storage

```bash
gsutil mb -l europe-west4 gs://{GCS_BUCKET_NAME}
```

Expected bucket prefixes:

```text
sessions/{session_id}/
analyses/{session_id}/
knowledge_base/templates/
knowledge_base/guidelines/
knowledge_base/examples/
```

There is no checked-in root `knowledge_base/` directory in this repo. Create these prefixes by uploading curated files, for example:

```bash
gsutil -m cp local_templates/* gs://{GCS_BUCKET_NAME}/knowledge_base/templates/
gsutil -m cp local_guidelines/* gs://{GCS_BUCKET_NAME}/knowledge_base/guidelines/
gsutil -m cp local_examples/* gs://{GCS_BUCKET_NAME}/knowledge_base/examples/
```

### Secret Manager

Create required secrets:

```bash
echo -n "your-gemini-api-key" | gcloud secrets create GOOGLE_API_KEY --data-file=-
echo -n "your-bucket-name" | gcloud secrets create GCS_BUCKET_NAME --data-file=-
echo -n "srs_sessions" | gcloud secrets create FIRESTORE_COLLECTION --data-file=-
echo -n "your-firestore-database" | gcloud secrets create FIRESTORE_DATABASE --data-file=-
echo -n "your-admin-token" | gcloud secrets create ADMIN_BEARER_TOKEN --data-file=-
```

To update an existing secret:

```bash
echo -n "new-value" | gcloud secrets versions add GOOGLE_API_KEY --data-file=-
```

### Workload Identity Federation (for GitHub Actions)

```bash
gcloud iam workload-identity-pools create github-pool \
  --location=global \
  --display-name="GitHub Actions Pool"

gcloud iam workload-identity-pools providers create-oidc github-provider \
  --location=global \
  --workload-identity-pool=github-pool \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository"

gcloud iam service-accounts add-iam-policy-binding {SA_EMAIL} \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/{PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-pool/attribute.repository/{GITHUB_ORG}/{REPO}"
```

### Service Account Permissions

Use separate service accounts for CI/CD and runtime if possible.

Runtime Cloud Run service account:

| Role | Reason |
|---|---|
| `roles/datastore.user` | Firestore read/write |
| `roles/storage.objectAdmin` | GCS uploads, generated docs, final analysis JSON |
| `roles/secretmanager.secretAccessor` | Secret Manager runtime secrets |
| `roles/bigquery.jobUser` | Run admin BigQuery queries |
| BigQuery dataset-level data viewer/editor as appropriate | Read admin views and write observability/anomaly outputs if used |
| `roles/logging.logWriter` | Cloud Logging, usually covered by default service identity behavior |
| `roles/cloudtrace.agent` | Export traces to Cloud Trace |
| `roles/monitoring.metricWriter` | Export custom metrics to Cloud Monitoring |

CI/CD deploy service account:

| Role | Reason |
|---|---|
| `roles/run.developer` | Deploy Cloud Run services |
| `roles/iam.serviceAccountUser` | Deploy revisions as the runtime service account |
| `roles/artifactregistry.writer` | Push images |
| `roles/secretmanager.secretAccessor` | Attach Secret Manager secrets during deploy |
| `roles/cloudbuild.builds.editor` | Needed if using `deploy.sh` / Cloud Build |

---

## Observability Setup

### Cloud Monitoring

The backend exports OpenTelemetry traces and metrics to Cloud Trace and Cloud Monitoring when GCP credentials are available.

Import the dashboard:

```bash
gcloud monitoring dashboards create \
  --config-from-file=infra/monitoring/dashboard.json
```

Import alert policies:

```bash
gcloud alpha monitoring policies create \
  --policy-from-file=infra/monitoring/alert-policies.yaml
```

Create log-based metrics following `infra/monitoring/README.md`. The current metrics are:

```text
extract_timeout_total
firestore_unavailable_total
bridge_injection_failure_total
```

### BigQuery Admin and Observability Views

The admin UI expects these views by default:

```text
{PROJECT_ID}.observability.messages
{PROJECT_ID}.observability.feedback
```

Before creating the views, install Firebase `firestore-bigquery-export` extension instances for:

1. The configured Firestore session collection, for example `srs_sessions`.
2. The top-level `feedback` collection.

Then replace placeholders in:

```text
infra/firestore-bigquery/messages_view.sql
infra/firestore-bigquery/feedback_view.sql
infra/safety/anomalous_sessions.sql
```

Create the dataset and views:

```bash
bq mk --dataset {PROJECT_ID}:{BIGQUERY_DATASET}

bq query --use_legacy_sql=false < infra/firestore-bigquery/messages_view.sql
bq query --use_legacy_sql=false < infra/firestore-bigquery/feedback_view.sql
bq query --use_legacy_sql=false < infra/safety/anomalous_sessions.sql
```

The SQL files contain `PROJECT_ID` placeholders and expected Firestore export table names. Replace them for your environment before running.

---

## Rollback

To roll back a Cloud Run service to a previous revision:

```bash
gcloud run revisions list \
  --service=business-persona-ai-backend \
  --region=europe-west4

gcloud run services update-traffic business-persona-ai-backend \
  --to-revisions={REVISION_NAME}=100 \
  --region=europe-west4
```

Use the corresponding frontend service name for frontend rollback:

```bash
gcloud run revisions list \
  --service=business-persona-ai-frontend \
  --region=europe-west4
```

---

## Knowledge Base Population

The research tools can list curated reference files in GCS under:

```text
knowledge_base/templates/
knowledge_base/guidelines/
knowledge_base/examples/
```

Upload sanitized examples and supporting documents:

```bash
gsutil -m cp local_examples/* gs://{GCS_BUCKET_NAME}/knowledge_base/examples/
gsutil -m cp local_guidelines/* gs://{GCS_BUCKET_NAME}/knowledge_base/guidelines/
gsutil -m cp local_templates/* gs://{GCS_BUCKET_NAME}/knowledge_base/templates/
```

Current retrieval is lightweight GCS listing/search. The app does not currently provision Vertex AI Search or vector embeddings as part of deployment.

---

## Health Check

Backend health endpoint:

```text
GET https://{BACKEND_URL}/health -> {"status":"ok"}
```

Frontend root:

```text
GET https://{FRONTEND_URL}/ -> Next.js HTML page
```

Cloud Run considers a revision ready when the container starts and listens on the configured port. It does not use these HTTP paths as liveness/readiness probes unless explicit probes are configured.

---

## Common Issues

### Backend Fails to Start: Missing Configuration

Production startup validates:

```text
GOOGLE_API_KEY
GOOGLE_CLOUD_PROJECT
GCS_BUCKET_NAME
FIRESTORE_COLLECTION
FIRESTORE_DATABASE
```

Set them through Secret Manager and Cloud Run env vars before deploying with `APP_ENV=production`.

### Browser Requests Fail With CORS Errors

Set backend `ALLOWED_ORIGINS` to the deployed frontend origin. The default is only `http://localhost:3000`.

### Frontend Cloud Run Revision Does Not Become Ready

The frontend image listens on port `3000`. Configure the Cloud Run frontend service to send traffic to container port `3000`, or update the frontend runtime to listen on the injected `PORT`.

### Frontend Shows Blank Page Or Calls The Wrong Backend

Check that `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_WS_URL` were set correctly at image build time. Next.js bakes `NEXT_PUBLIC_*` values into the client bundle during `next build`.

### Gemini API 403 Errors

Verify that `GOOGLE_API_KEY` is valid and the Gemini API is enabled:

```bash
gcloud services enable generativelanguage.googleapis.com
```

### Admin Pages Return BigQuery Errors

Confirm that:

- Firestore-to-BigQuery export extension instances are installed.
- `messages` and `feedback` views exist in `BIGQUERY_DATASET`.
- `BIGQUERY_MESSAGES_VIEW` and `BIGQUERY_FEEDBACK_VIEW` are correct if overriding defaults.
- The backend runtime service account can run BigQuery jobs and read the dataset/views.

### Live Session Context Is Lost

The backend uses in-memory ADK sessions. Firestore persists messages and RS field state, but a backend restart or a request routed to another backend instance can lose live ADK context. Keep this in mind for diagram generation, voice mode, and in-flight finalization.

### Cost Circuit Breaker Triggered

A session is halted when cumulative Gemini costs exceed `$5.00` by default. Configure with:

```text
COST_CIRCUIT_BREAKER_USD=5.0
```

Set `COST_CIRCUIT_BREAKER_USD=0` only for controlled testing where disabling the guard is intentional.
