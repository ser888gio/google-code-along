# Infrastructure Overview (Simplified)

## System Summary

The RS Generator is a fully serverless **Google Cloud** application in project `vw-skda-fskoda-sandbox-jzf` (`europe-west4`): two Cloud Run services front a Firestore + GCS + BigQuery data plane, built and shipped by GitHub Actions. The only external dependency is the Gemini API.

## Major Components

### Frontend Service (Cloud Run — Node.js)
**Purpose**: Serves the Next.js standalone UI on port 3000 over managed HTTPS.

### Backend Service (Cloud Run — Python/FastAPI)
**Purpose**: API + SSE + WebSocket on port 8080; talks to Gemini and the data plane.

### Safety Jobs (Cloud Run Jobs)
**Purpose**: Scheduled anomaly-metrics and daily red-team runs reusing the backend image.
**Contains**: `rs-safety-anomaly-metrics`, `rs-redteam-daily`.

### Firestore (Document Database)
**Purpose**: Durable session, field, workflow, analysis, and feedback state.

### Cloud Storage (GCS Bucket)
**Purpose**: Uploads, generated DOCX/JSON artifacts, and the knowledge-base corpus.

### BigQuery (Analytics — `observability`)
**Purpose**: Flattened message/feedback views and the safety-anomalies table for admin and safety jobs.

### Artifact Registry + GitHub Actions (CI/CD)
**Purpose**: Build/push Docker images and deploy both services via Workload Identity Federation.

### Gemini API (External LLM)
**Purpose**: All model inference via direct API key from Secret Manager.

## Data Flow

1. A user's browser hits the **Frontend service** (HTTPS) and calls the **Backend service** directly (HTTPS + WSS).
2. The backend invokes the **Gemini API** and reads/writes **Firestore** and **GCS**.
3. **Firestore** exports to **BigQuery**; admin screens and the **safety Jobs** query those views.
4. On push to `develop`, **GitHub Actions** builds images into **Artifact Registry** and deploys both Cloud Run services.

## Key Boundaries

| Boundary | Inside | Outside |
|----------|--------|---------|
| GCP project (`europe-west4`) | Cloud Run services & Jobs, Firestore, GCS, BigQuery, Secret Manager, Artifact Registry | Users, GitHub Actions, Gemini API |
| Cloud Run (managed HTTPS) | Backend + frontend containers | Public internet |
| Secret Manager | API keys, bucket/DB names, admin token | Application code / repo |
</content>
