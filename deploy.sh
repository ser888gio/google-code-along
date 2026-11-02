#!/bin/bash

# Exit on error
set -e

# --- Configuration ---
# Keep in sync with .github/workflows/cicd.yaml (same project, repo, accounts and runtime settings).
export PROJECT_ID=vw-skda-fskoda-sandbox-jzf
export REGION=europe-west4
export SERVICE_NAME=business-persona-ai
export BACKEND_SA=persona-ai-backend-runtime@$PROJECT_ID.iam.gserviceaccount.com
export FRONTEND_SA=persona-ai-frontend-runtime@$PROJECT_ID.iam.gserviceaccount.com
export ALLOWED_ORIGINS=https://business-persona-ai-frontend-4nbdz3xjxa-ez.a.run.app,https://business-persona-ai-frontend-184082972607.europe-west4.run.app
IMAGE_TAG="manual-$(date +%Y%m%d%H%M%S)"

# --- Argument Parsing ---
FRONTEND_ONLY=false
for arg in "$@"
do
    if [ "$arg" == "--frontend-only" ]
    then
        FRONTEND_ONLY=true
    fi
done

# --- Helper Functions ---
deploy_backend() {
    echo "--- Backend Deployment ---"
    BACKEND_SERVICE_NAME="$SERVICE_NAME-backend"
    BACKEND_IMAGE_TAG="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/backend:$IMAGE_TAG"

    echo "Building and pushing the backend Docker image..."
    gcloud builds submit backend --tag $BACKEND_IMAGE_TAG --default-buckets-behavior=regional-user-owned-bucket

    echo "Deploying the backend to Cloud Run..."
    # ^|^ switches the list delimiter so ALLOWED_ORIGINS can contain commas.
    BACKEND_ENV_VARS="^|^GOOGLE_CLOUD_PROJECT=$PROJECT_ID|APP_ENV=production|BIGQUERY_DATASET=observability|ALLOWED_ORIGINS=$ALLOWED_ORIGINS"
    BACKEND_SECRETS="GOOGLE_API_KEY=GOOGLE_API_KEY:latest,GCS_BUCKET_NAME=GCS_BUCKET_NAME:latest,FIRESTORE_COLLECTION=FIRESTORE_COLLECTION:latest,FIRESTORE_DATABASE=FIRESTORE_DATABASE:latest"

    # max-instances=1: ADK sessions are in memory, so all requests must hit one instance.
    gcloud run deploy $BACKEND_SERVICE_NAME \
        --image $BACKEND_IMAGE_TAG \
        --platform managed \
        --allow-unauthenticated \
        --service-account="$BACKEND_SA" \
        --max-instances=1 \
        --memory=1Gi \
        --set-env-vars="$BACKEND_ENV_VARS" \
        --set-secrets="$BACKEND_SECRETS"

    # Get the backend URL
    BACKEND_URL=$(gcloud run services describe $BACKEND_SERVICE_NAME --platform managed --format 'value(status.url)')
    echo "Backend URL: $BACKEND_URL"
}

deploy_frontend() {
    echo "--- Frontend Deployment ---"
    # NEXT_PUBLIC_* is baked at build time; an empty value makes the browser call the frontend origin and 404.
    if [ -z "$BACKEND_URL" ]; then
        echo "ERROR: BACKEND_URL is empty; refusing to build frontend." >&2
        return 1
    fi
    FRONTEND_SERVICE_NAME="$SERVICE_NAME-frontend"
    FRONTEND_IMAGE_TAG="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/frontend:$IMAGE_TAG"

    echo "Building and pushing the frontend Docker image..."
    FRONTEND_BUILD_CONFIG="$(mktemp)"
    cat > "$FRONTEND_BUILD_CONFIG" << EOL
steps:
  - name: gcr.io/cloud-builders/docker
    args:
      - build
      - --build-arg
      - NEXT_PUBLIC_API_URL=$BACKEND_URL
      - --build-arg
      - NEXT_PUBLIC_WS_URL=wss://${BACKEND_URL#https://}
      - "-t"
      - "$FRONTEND_IMAGE_TAG"
      - "."
images:
  - $FRONTEND_IMAGE_TAG
EOL
    if ! gcloud builds submit frontend \
        --config "$FRONTEND_BUILD_CONFIG" \
        --default-buckets-behavior=regional-user-owned-bucket
    then
        rm -f "$FRONTEND_BUILD_CONFIG"
        return 1
    fi
    rm -f "$FRONTEND_BUILD_CONFIG"

    echo "Deploying the frontend to Cloud Run..."
    gcloud run deploy $FRONTEND_SERVICE_NAME \
        --image $FRONTEND_IMAGE_TAG \
        --platform managed \
        --allow-unauthenticated \
        --service-account="$FRONTEND_SA"

    # Get the frontend URL
    FRONTEND_URL=$(gcloud run services describe $FRONTEND_SERVICE_NAME --platform managed --format 'value(status.url)')
    echo "Frontend URL: $FRONTEND_URL"
}


# --- Main Execution ---
gcloud config set project $PROJECT_ID
gcloud config set run/region $REGION
gcloud config set builds/region $REGION

# Enable necessary services
echo "Enabling necessary Google Cloud services..."
gcloud services enable \
    run.googleapis.com \
    artifactregistry.googleapis.com \
    cloudbuild.googleapis.com \
    logging.googleapis.com \
    monitoring.googleapis.com \
    cloudtrace.googleapis.com

# Create an Artifact Registry repository
REPO_NAME="$SERVICE_NAME-repo"
echo "Creating Artifact Registry repository '$REPO_NAME' if it doesn't exist..."
gcloud artifacts repositories create $REPO_NAME \
    --repository-format=docker \
    --location=$REGION \
    --description="Docker repository for $SERVICE_NAME" || echo "Repository '$REPO_NAME' already exists."

if [ "$FRONTEND_ONLY" = "false" ]; then
    deploy_backend
    deploy_frontend
else
    # If deploying frontend only, get the URL of the existing backend
    BACKEND_SERVICE_NAME="$SERVICE_NAME-backend"
    echo "Fetching backend URL for '$BACKEND_SERVICE_NAME'..."
    BACKEND_URL=$(gcloud run services describe $BACKEND_SERVICE_NAME --platform managed --format 'value(status.url)')
    deploy_frontend
fi

# --- Final Output ---
echo ""
echo "✅ Deployment successful!"
echo ""
if [ "$FRONTEND_ONLY" = "false" ]; then
    echo "Backend URL: $BACKEND_URL"
fi
echo "Frontend URL: $FRONTEND_URL"
