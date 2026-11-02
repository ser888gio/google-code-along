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
| Backend runtime service account | `persona-ai-backend-runtime@vw-skda-fskoda-sandbox-jzf.iam.gserviceaccount.com` |
| Frontend runtime service account | `persona-ai-frontend-runtime@vw-skda-fskoda-sandbox-jzf.iam.gserviceaccount.com` |
| CI deploy service account | `github-actions-deployer@vw-skda-fskoda-sandbox-jzf.iam.gserviceaccount.com` |
| Firestore database | `ai-business-person-firestore` (`europe-west4`, PITR and delete protection on) |
| Firestore session collection | `ai-business-person-collection` |
| GCS bucket | `ai-business-person-bucket` (EU multi-region) |

`vw-skda-fskoda-sandbox-jzf` is a shared sandbox project used by many teams. Do not use the default compute service account for this app, and filter by these names when inspecting resources.

The Gemini API key in the `GOOGLE_API_KEY` secret is a key from the `vw-skda-fhackton-156` project (display name `BusinessPersonaAI-2026-11`), so Gemini usage is billed there.

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
5. Deploy backend to Cloud Run (env vars and secrets overwritten from the workflow)
6. Deploy the rs-user-simulation job and rs-safety-anomaly-metrics job
7. Build and push frontend image with backend URL build args
8. Deploy frontend to Cloud Run
```

The backend deploy uses `env_vars_update_strategy: overwrite` and `secrets_update_strategy: overwrite`. The workflow is the single source of truth: any env var or secret added by hand in the console is removed on the next deploy. Add new runtime configuration to `.github/workflows/cicd.yaml` (and `deploy.sh`), never only in the console.

### GCP Authentication

The pipeline uses **Workload Identity Federation**, so GitHub Actions does not need a long-lived service account JSON key. The GitHub repository is federated with a GCP Workload Identity Pool and impersonates a deploy service account.

Required GitHub Actions secrets:

| Secret | Description |
|---|---|
| `WIF_PROVIDER` | Full Workload Identity Provider resource name |
| `SA_EMAIL` | Service account email that the pipeline impersonates |

Required GCP Secret Manager secrets referenced by the workflow:

| Secret Manager secret | Runtime variable |
|---|---|
| `GOOGLE_API_KEY` | `GOOGLE_API_KEY` |
| `GCS_BUCKET_NAME` | `GCS_BUCKET_NAME` |
| `FIRESTORE_COLLECTION` | `FIRESTORE_COLLECTION` |
| `FIRESTORE_DATABASE` | `FIRESTORE_DATABASE` |

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

CI sets `ALLOWED_ORIGINS` to both URLs of the deployed frontend:

```text
ALLOWED_ORIGINS=https://business-persona-ai-frontend-4nbdz3xjxa-ez.a.run.app,https://business-persona-ai-frontend-184082972607.europe-west4.run.app
```

In the workflow's `env_vars` block the comma must be escaped as `\,`; in `deploy.sh` the list uses the `^|^` delimiter prefix. Without this setting, browser requests from the deployed frontend to the deployed backend fail CORS checks.

### Image Tags

CI images are tagged with the full Git commit SHA (`github.sha`) and pushed to:

```text
europe-west4-docker.pkg.dev/{PROJECT_ID}/{REPOSITORY}/backend:{GITHUB_SHA}
europe-west4-docker.pkg.dev/{PROJECT_ID}/{REPOSITORY}/frontend:{GITHUB_SHA}
```

Manual `deploy.sh` images go to the same packages with a `manual-<timestamp>` tag:

```text
europe-west4-docker.pkg.dev/{PROJECT_ID}/{REPOSITORY}/backend:manual-20261102160000
europe-west4-docker.pkg.dev/{PROJECT_ID}/{REPOSITORY}/frontend:manual-20261102160000
```

CI pushes with `provenance: false`, so each push is one image manifest. The repository has a cleanup policy that keeps the 30 newest versions per package and deletes the rest (older pushes stored three versions each, so this keeps at least the 10 newest images). Roll back only to images inside that window.

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

### Manual Deployment Caveats

`deploy.sh` mirrors the CI configuration: same project, repository, runtime service accounts, Secret Manager secrets, `ALLOWED_ORIGINS`, and one backend instance with 1 GiB. Keep the two in sync when either changes. `deploy.sh` does not deploy the simulation or anomaly jobs.

Behind the corporate Zscaler proxy, `gcloud` fails with `CERTIFICATE_VERIFY_FAILED` because its bundled Python does not trust the Zscaler root CA. Export `Zscaler Root CA` from the Windows certificate store, append it to a copy of `google-cloud-sdk/lib/third_party/certifi/cacert.pem`, and point gcloud at it:

```bash
gcloud config set core/custom_ca_certs_file <path-to-combined-bundle.pem>
```

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
EXPOSE 3000
CMD ["node", "server.js"]
```

- Base image: `node:22-alpine`
- `NEXT_PUBLIC_*` values are build args baked into the Next.js client bundle during `next build`.
- Output is a Next.js standalone runtime image.
- The image defaults to port `3000` for local runs. On Cloud Run the service uses container port `8080`; Cloud Run injects `PORT=8080`, which overrides the image's `ENV PORT=3000`, and the Next.js standalone server listens on `PORT`.

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
| Container port | `8080` | `8080` (via injected `PORT`) |
| Region | `europe-west4` | `europe-west4` |
| Min instances | `0` | `0` |
| Max instances | `1` | `100` |
| Memory | `1 GiB` | `512 MiB` |
| CPU | `1` | `1` |
| Concurrency | `80` | `80` |
| Request timeout | `300s` | `300s` |
| Service account | `persona-ai-backend-runtime` | `persona-ai-frontend-runtime` |
| Allow unauthenticated | Yes | Yes |

The backend is capped at one instance because ADK sessions are in memory: a request routed to another instance would lose live agent context. Raise this only after ADK sessions are persisted. A restart (including every deploy) still drops in-flight sessions.

Backend runtime configuration:

| Variable | Source | Notes |
|---|---|---|
| `GOOGLE_API_KEY` | Secret Manager | Required in production |
| `GCS_BUCKET_NAME` | Secret Manager | Required in production |
| `FIRESTORE_COLLECTION` | Secret Manager | Required in production |
| `FIRESTORE_DATABASE` | Secret Manager | Required in production |
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

Enable point-in-time recovery and delete protection on the database (both are on for `ai-business-person-firestore`):

```bash
gcloud firestore databases update --database={FIRESTORE_DATABASE} --enable-pitr --delete-protection
```

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

The app uses two dedicated runtime service accounts. Never switch it back to the shared default compute account (`184082972607-compute@developer.gserviceaccount.com`), which many teams use and which holds broad admin roles.

`persona-ai-backend-runtime` runs the backend service, the `rs-user-simulation` and `rs-safety-anomaly-metrics` jobs, and calls their Cloud Scheduler triggers:

| Role | Scope | Reason |
|---|---|---|
| `roles/datastore.user` | Project | Firestore read/write |
| `roles/storage.objectAdmin` | Bucket `ai-business-person-bucket` | Uploads, generated docs, analyses, simulation results |
| `roles/secretmanager.secretAccessor` | Secrets `GOOGLE_API_KEY`, `GCS_BUCKET_NAME`, `FIRESTORE_COLLECTION`, `FIRESTORE_DATABASE` | Runtime secrets |
| `roles/bigquery.jobUser` | Project | Observability and safety queries |
| `roles/logging.logWriter` | Project | Cloud Logging |
| `roles/cloudtrace.agent` | Project | Export traces to Cloud Trace |
| `roles/monitoring.metricWriter` | Project | Export custom metrics |
| `roles/run.invoker` | Jobs `rs-user-simulation`, `rs-safety-anomaly-metrics` | Cloud Scheduler starts the jobs as this account (granted by CI) |

Job-level IAM can only be set with `run.admin`, so the job invoker bindings are granted by CI (`github-actions-deployer`), not by hand.

`persona-ai-frontend-runtime` runs the frontend and has no roles: the Next.js server needs no Google Cloud access.

CI/CD deploy service account (`github-actions-deployer`):

| Role | Reason |
|---|---|
| `roles/run.admin` | Deploy services and jobs, set job-level invoker bindings |
| `roles/iam.serviceAccountUser` | Deploy revisions as the runtime service accounts |
| `roles/artifactregistry.writer` | Push images |
| `roles/monitoring.dashboardEditor` | Create and update the checked-in Cloud Monitoring dashboard |
| `roles/cloudscheduler.admin` | Optional: only needed to create missing scheduler triggers (CI warns without it) |

Grant the dashboard role to the GitHub Actions deploy service account before
changing `infra/monitoring/dashboard.json`:

```bash
gcloud projects add-iam-policy-binding {PROJECT_ID} \
  --member="serviceAccount:{SA_EMAIL}" \
  --role="roles/monitoring.dashboardEditor"
```

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

Create log-based metrics following `infra/monitoring/README.md`. Both exist in the project:

```text
firestore_unavailable_total
bridge_injection_failure_total
```

The alert policy in `infra/monitoring/alert-policies.yaml` is not applied yet; it needs a notification channel ID first.

### BigQuery Observability Views

**Status: blocked by an organization policy.** The `observability` dataset exists (`europe-west4`, empty), but the `firestore-bigquery-export` extension cannot be installed in `vw-skda-fskoda-sandbox-jzf`. The extension creates a Cloud Tasks queue, and Cloud Tasks rejects the VW organization's `constraints/gcp.resourceLocations` policy:

```text
Invalid Cloud Tasks location constraint org policy. Either both the locations 'us-central1' and
'us-central2' should be included in the policy, or both locations should be excluded from the policy.
```

The GCP platform team has to add `us-central2` to the policy, or remove `us-central1` from it. Until then the `rs-safety-anomaly-metrics` scheduler trigger is paused, because its source table does not exist. Once the policy is fixed, install the extensions with these settings:

| Parameter | Sessions instance | Feedback instance |
|---|---|---|
| Instance ID | `firestore-bq-sessions` | `firestore-bq-feedback` |
| `DATABASE` / `DATABASE_REGION` | `ai-business-person-firestore` / `europe-west4` | same |
| `COLLECTION_PATH` | `ai-business-person-collection` | `feedback` |
| `DATASET_ID` / `DATASET_LOCATION` | `firestore_export` / `europe-west4` | same |
| `TABLE_ID` | `srs_sessions` (matches the view SQL) | `feedback` |
| Function location | `europe-west1` (`europe-west4` is not offered) | same |

Version 0.3.x has no built-in backfill. Import existing documents with the `fs-bq-import-collection` script after installing. Then grant `persona-ai-backend-runtime` `roles/bigquery.dataViewer` on `firestore_export` and `roles/bigquery.dataEditor` on `observability`, create the views below, create the anomaly scheduled query (02:00 Europe/Prague, running as `persona-ai-backend-runtime`), and resume the trigger:

```bash
gcloud scheduler jobs resume rs-safety-anomaly-metrics --location=europe-west4
```

Observability and safety analysis use these views by default:

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

### Cloud Run Rejects A Revision: Permission Denied On Secret

The revision's service account cannot read a secret it references. Grant `roles/secretmanager.secretAccessor` on that secret to the runtime account, or remove the stale reference from the workflow. A failed update still writes the new spec to the service; traffic stays on the last ready revision.

### Frontend Shows Blank Page Or Calls The Wrong Backend

Check that `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_WS_URL` were set correctly at image build time. Next.js bakes `NEXT_PUBLIC_*` values into the client bundle during `next build`.

### Gemini API 403 Errors

Verify that `GOOGLE_API_KEY` is valid and the Gemini API is enabled:

```bash
gcloud services enable generativelanguage.googleapis.com
```

### Live Session Context Is Lost

The backend uses in-memory ADK sessions. Firestore persists messages and RS field state, but a backend restart or a request routed to another backend instance can lose live ADK context. Keep this in mind for diagram generation, voice mode, and in-flight finalization.

### Cost Circuit Breaker Triggered

A session is halted when cumulative Gemini costs exceed `$5.00` by default. Configure with:

```text
COST_CIRCUIT_BREAKER_USD=5.0
```

Set `COST_CIRCUIT_BREAKER_USD=0` only for controlled testing where disabling the guard is intentional.
