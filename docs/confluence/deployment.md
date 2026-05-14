# Deployment Guide

## Overview

The application consists of two independently deployable services — **backend** and **frontend** — both containerized with Docker and deployed to **Google Cloud Run** in the `europe-west4` region. Deployment is automated via **GitHub Actions** on every push to the `develop` branch.

---

## Infrastructure Summary

| Component | Service | Region |
|---|---|---|
| Backend API | Cloud Run | `europe-west4` |
| Frontend | Cloud Run | `europe-west4` |
| Container Registry | Artifact Registry | `europe-west4` |
| Session Storage | Firestore | (same project) |
| File Storage | Cloud Storage | (same project) |
| Secrets | Secret Manager | (same project) |
| Observability | Cloud Monitoring + BigQuery | (same project) |
| CI/CD | GitHub Actions | — |

---

## Automated Deployment (GitHub Actions)

### Trigger

Every push to the `develop` branch triggers the full CI/CD pipeline defined in `.github/workflows/cicd.yaml`.

### Pipeline Steps

```
1. Checkout code
2. Authenticate to GCP (Workload Identity Federation — no long-lived keys)
3. Configure Docker for Artifact Registry
4. Build & push backend image
5. Deploy backend to Cloud Run
6. Build & push frontend image (with backend URL as build arg)
7. Deploy frontend to Cloud Run
```

### GCP Authentication

The pipeline uses **Workload Identity Federation** so that GitHub Actions never stores a service account JSON key. The GitHub repository is federated with a GCP Workload Identity Pool.

Required GitHub Actions secrets:

| Secret | Description |
|---|---|
| `WIF_PROVIDER` | Full Workload Identity Provider resource name |
| `SA_EMAIL` | Service account email that the pipeline impersonates |
| `GOOGLE_API_KEY` | Gemini API key |
| `GCS_BUCKET_NAME` | Cloud Storage bucket name |
| `FIRESTORE_COLLECTION` | Firestore collection name |
| `FIRESTORE_DATABASE` | Firestore database ID |
| `ADMIN_BEARER_TOKEN` | Static bearer token for the admin API |

### Image Tags

Images are tagged with the short Git commit SHA and pushed to:

```
europe-west4-docker.pkg.dev/{PROJECT_ID}/{REPO}/backend:{SHA}
europe-west4-docker.pkg.dev/{PROJECT_ID}/{REPO}/frontend:{SHA}
```

---

## Manual Deployment (`deploy.sh`)

For ad-hoc deploys (e.g., hotfixes without waiting for CI):

```bash
bash deploy.sh              # deploys both backend and frontend
bash deploy.sh --frontend-only   # redeploys only the frontend
```

The script:

1. Builds images locally using `docker build`
2. Pushes to Artifact Registry
3. Runs `gcloud run deploy` for each service

**Prerequisites:**

- `gcloud` CLI installed and authenticated (`gcloud auth login`)
- Docker daemon running
- Active GCP project set: `gcloud config set project {PROJECT_ID}`

---

## Docker Images

### Backend

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
COPY . .
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

- Base: `python:3.12-slim`
- Dependencies installed with hash verification (`--require-hashes`)
- Runs on port `8080` (Cloud Run default)

### Frontend

Multi-stage build:

```dockerfile
FROM node:22-alpine AS deps      # install node_modules
FROM node:22-alpine AS builder   # next build (standalone mode)
FROM node:22-alpine AS runner    # minimal production image

ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_WS_URL
ARG NEXT_PUBLIC_ADMIN_API_TOKEN

EXPOSE 3000
```

- Base: `node:22-alpine`
- Build args baked into the image at build time (Next.js requires this for `NEXT_PUBLIC_*` variables)
- Output: Next.js standalone bundle (minimal image, no full `node_modules`)
- Runs on port `3000`

---

## Local Development

### Option 1: Full Docker Compose stack

```bash
cp backend/.env.example backend/.env   # fill in all values
# Place a GCP service account JSON at ./gcp-key.json
docker-compose up --build
```

Services:

| Service | Local URL |
|---|---|
| Backend | `http://localhost:8080` |
| Frontend | `http://localhost:3000` |

The backend container mounts `gcp-key.json` as read-only at `/tmp/gcp-credentials.json` and sets `GOOGLE_APPLICATION_CREDENTIALS` accordingly.

### Option 2: Native dev servers

```bash
bash dev.sh
```

This script starts both the Python uvicorn server and the Next.js dev server in parallel with hot reload.

Manual equivalent:

```bash
# Terminal 1 — Backend
cd backend
cp .env.example .env
.venv/Scripts/python -m uvicorn main:app --host 0.0.0.0 --port 8080 --reload

# Terminal 2 — Frontend
cd frontend
cp .env.local.example .env.local
npm install
npm run dev
```

---

## Cloud Run Configuration

Both services are deployed as Cloud Run services. Key settings:

| Setting | Backend | Frontend |
|---|---|---|
| Port | 8080 | 3000 |
| Region | `europe-west4` | `europe-west4` |
| Min instances | 0 (scales to zero) | 0 |
| Max instances | Configured per environment | Configured per environment |
| Memory | As required by `gemini-adk` workload | 512 Mi |
| CPU | 1–2 vCPU | 1 vCPU |
| Allow unauthenticated | Yes (public app) | Yes (public app) |

**Environment variables injected at Cloud Run deploy time** (via `gcloud run deploy --set-env-vars`):

Backend: `GOOGLE_API_KEY`, `GCS_BUCKET_NAME`, `FIRESTORE_COLLECTION`, `FIRESTORE_DATABASE`, `ADMIN_BEARER_TOKEN`, `APP_ENV=production`

Frontend: `NEXT_PUBLIC_API_URL` (the backend Cloud Run service URL), `NEXT_PUBLIC_WS_URL`, `NEXT_PUBLIC_ADMIN_API_TOKEN`

---

## GCP Services Setup (One-Time)

The following GCP services must be enabled and configured before the first deployment:

### APIs to Enable

```bash
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  firestore.googleapis.com \
  storage.googleapis.com \
  secretmanager.googleapis.com \
  bigquery.googleapis.com \
  monitoring.googleapis.com \
  cloudbuild.googleapis.com \
  iam.googleapis.com
```

### Artifact Registry

```bash
gcloud artifacts repositories create {REPO_NAME} \
  --repository-format=docker \
  --location=europe-west4
```

### Firestore

```bash
gcloud firestore databases create \
  --database={FIRESTORE_DATABASE} \
  --location=europe-west4
```

Indexes are created automatically by the Firestore client on first query.

### Cloud Storage

```bash
gsutil mb -l europe-west4 gs://{GCS_BUCKET_NAME}
```

After creation, create the knowledge base directory structure:

```bash
gsutil cp -r knowledge_base/ gs://{GCS_BUCKET_NAME}/knowledge_base/
```

### Workload Identity Federation (for GitHub Actions)

```bash
# Create the pool
gcloud iam workload-identity-pools create github-pool \
  --location=global \
  --display-name="GitHub Actions Pool"

# Create the OIDC provider
gcloud iam workload-identity-pools providers create-oidc github-provider \
  --location=global \
  --workload-identity-pool=github-pool \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository"

# Bind the service account
gcloud iam service-accounts add-iam-policy-binding {SA_EMAIL} \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/{PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-pool/attribute.repository/{GITHUB_ORG}/{REPO}"
```

### Service Account Permissions

The service account used by Cloud Run (and impersonated by GitHub Actions) needs:

| Role | Reason |
|---|---|
| `roles/datastore.user` | Firestore read/write |
| `roles/storage.objectAdmin` | GCS read/write |
| `roles/secretmanager.secretAccessor` | Read secrets |
| `roles/bigquery.dataEditor` | Write observability data |
| `roles/run.developer` | Deploy Cloud Run services (CI/CD SA only) |
| `roles/artifactregistry.writer` | Push images (CI/CD SA only) |

---

## Observability Setup

### Cloud Monitoring

Import the pre-built dashboard:

```bash
gcloud monitoring dashboards create \
  --config-from-file=infra/monitoring/dashboard.json
```

Import alert policies:

```bash
gcloud alpha monitoring policies import \
  --policy-from-file=infra/monitoring/alert-policies.yaml
```

Create log-based metrics:

```bash
# Follow instructions in infra/monitoring/README.md
```

### BigQuery Observability Views

```bash
bq mk --dataset {PROJECT_ID}:{BIGQUERY_DATASET}

bq query --use_legacy_sql=false < infra/firestore-bigquery/messages_view.sql
bq query --use_legacy_sql=false < infra/firestore-bigquery/feedback_view.sql
bq query --use_legacy_sql=false < infra/safety/anomalous_sessions.sql
```

---

## Secrets Management

In production, secrets are stored in **Google Cloud Secret Manager** and referenced in the Cloud Run deploy command. Do not store secrets in environment files committed to the repository.

To create a secret:

```bash
echo -n "your-secret-value" | gcloud secrets create GOOGLE_API_KEY --data-file=-
```

To reference in Cloud Run:

```bash
gcloud run deploy backend \
  --set-secrets=GOOGLE_API_KEY=GOOGLE_API_KEY:latest
```

---

## Rollback

To roll back to a previous revision:

```bash
# List revisions
gcloud run revisions list --service=backend --region=europe-west4

# Route 100% traffic to a specific revision
gcloud run services update-traffic backend \
  --to-revisions={REVISION_NAME}=100 \
  --region=europe-west4
```

---

## Knowledge Base Population

The quality of RS generation improves when the `knowledge_base/` folder in GCS contains historical RS examples. After gathering sanitized examples (task 2.2 in CLAUDE.md), upload them:

```bash
gsutil -m cp -r local_examples/ gs://{GCS_BUCKET_NAME}/knowledge_base/examples/
gsutil -m cp rs_template.docx gs://{GCS_BUCKET_NAME}/knowledge_base/templates/
```

---

## Health Check

Both Cloud Run services expose the root path as a health check:

- Backend: `GET https://{BACKEND_URL}/` → `{"status": "ok"}`
- Frontend: `GET https://{FRONTEND_URL}/` → Next.js HTML page

Cloud Run uses these for readiness and liveness probes.

---

## Common Issues

### Backend fails to start — missing credentials

Ensure `GOOGLE_APPLICATION_CREDENTIALS` is set and the file exists (local) or that the Cloud Run service account has the correct IAM roles (production).

### Frontend shows blank page

Check that `NEXT_PUBLIC_API_URL` was set correctly at image **build time** (not just at runtime). Next.js bakes `NEXT_PUBLIC_*` variables into the static bundle during `next build`.

### Gemini API 403 errors

Verify `GOOGLE_API_KEY` is valid and that the Gemini API is enabled in the GCP project:

```bash
gcloud services enable generativelanguage.googleapis.com
```

### Cost circuit breaker triggered

A session is halted when cumulative Gemini costs exceed $5 USD. The limit is configurable in `backend/config.py`. For demo/testing, increase or disable the limit temporarily.
