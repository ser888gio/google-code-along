Deploying to Google Cloud Run
Here's how to deploy your backend to Cloud Run:

Prerequisites
Google Cloud CLI installed and authenticated (gcloud auth login)
A GCP project with billing enabled
Enable required APIs:

gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com
Steps
1. Create a Dockerfile in /backend
Let me check what your backend looks like first.

Bash List backend directory
IN
ls c:/Users/nicas/Desktop/google-code-along/backend/

OUT
__pycache__/
agent/
bigquery/
bpmn/
context/
dataflow/
firestore/
generation/
main.py
requirements.txt
sr.json
template/
tests/
Globpattern: "backend/{requirements*.txt,pyproject.toml,Dockerfile,*.py,**/*.py}"
Found 101 files
Read c:\Users\nicas\Desktop\google-code-along\backend\main.py
Read c:\Users\nicas\Desktop\google-code-along\backend\requirements.txt
Read c:\Users\nicas\Desktop\google-code-along\backend\.env
Now I have the full picture. Here's how to deploy your backend to Cloud Run:

1. Create a Dockerfile
Write c:\Users\nicas\Desktop\google-code-along\backend\Dockerfile
13 lines
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
2. Create a .dockerignore
Write c:\Users\nicas\Desktop\google-code-along\backend\.dockerignore
7 lines
.venv/
__pycache__/
.env
*.pyc
.git/
tests/
3. Deploy Commands
Run these from the backend/ directory:


# Set your project
gcloud config set project vw-skda-fhackton-156

# Deploy directly from source (Cloud Build builds the container for you)
gcloud run deploy rs-generator-backend \
  --source . \
  --region europe-central2 \
  --allow-unauthenticated \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=vw-skda-fhackton-156,GOOGLE_CLOUD_REGION=europe-central2,VERTEX_AI_SEARCH_DATASTORE_ID=sn-hackathon-skoda_1773834948735,GCS_BUCKET_NAME=code_along_input_business_persona,FIRESTORE_COLLECTION=srs_sessions,BQ_DATASET=rs_generator,BQ_TABLE=srs_sessions"
Important Notes
API key: Your .env has a GEMINI_API_KEY. For Cloud Run, you should use Secret Manager instead of env vars for secrets:


# Create the secret
echo -n "(the gemini api key)" | gcloud secrets create gemini-api-key --data-file=-

# Grant Cloud Run access
gcloud secrets add-iam-policy-binding gemini-api-key \
  --member="serviceAccount:YOUR_PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

# Add to deploy command:
--set-secrets "GEMINI_API_KEY=gemini-api-key:latest"
Service account permissions: The default Compute Engine service account needs these roles:

roles/aiplatform.user (Vertex AI)
roles/storage.objectAdmin (GCS uploads)
roles/datastore.user (Firestore)
roles/bigquery.dataEditor (BigQuery)
roles/discoveryengine.viewer (Vertex AI Search)
After deploying, Cloud Run gives you a URL like https://rs-generator-backend-xxxxx-ew.a.run.app. Update your frontend to point to that URL instead of localhost.

The .env is excluded via .dockerignore — all config goes through --set-env-vars and --set-secrets.