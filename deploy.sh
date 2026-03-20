#!/bin/bash

# Exit on error
set -e

# --- Configuration ---
export PROJECT_ID=vw-skda-fhackton-156
export REGION=europe-west4
export SERVICE_NAME=business-persona-ai

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
    BACKEND_IMAGE_TAG="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/$BACKEND_SERVICE_NAME:latest"

    echo "Building and pushing the backend Docker image..."
    gcloud builds submit backend --tag $BACKEND_IMAGE_TAG --default-buckets-behavior=regional-user-owned-bucket

    echo "Deploying the backend to Cloud Run..."
    gcloud run deploy $BACKEND_SERVICE_NAME \
        --image $BACKEND_IMAGE_TAG \
        --platform managed \
        --region $REGION \
        --allow-unauthenticated \
        --set-env-vars="GOOGLE_GENAI_USE_VERTEXAI=1,GOOGLE_CLOUD_PROJECT=$PROJECT_ID,GOOGLE_CLOUD_REGION=europe-central2,GCS_BUCKET_NAME=code_along_input_business_persona,FIRESTORE_COLLECTION=srs_sessions,FIRESTORE_DATABASE=businesspersona"

    # Get the backend URL
    BACKEND_URL=$(gcloud run services describe $BACKEND_SERVICE_NAME --platform managed --format 'value(status.url)')
    echo "Backend URL: $BACKEND_URL"
}

deploy_frontend() {
    echo "--- Frontend Deployment ---"
    FRONTEND_SERVICE_NAME="$SERVICE_NAME-frontend"
    FRONTEND_IMAGE_TAG="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/$FRONTEND_SERVICE_NAME:latest"

    echo "Building and pushing the frontend Docker image..."
    # Temporarily create a Dockerfile for the frontend
    cat > frontend/Dockerfile << EOL
# Use the official Node.js 20 image.
FROM node:20-slim

# Create and change to the app directory.
WORKDIR /app

# Copy application dependency manifests to the container image.
# A wildcard is used to ensure both package.json AND package-lock.json are copied.
# Copying this first prevents re-running npm install on every code change.
COPY package*.json ./

# Install production dependencies.
RUN npm install

# Copy local code to the container image.
COPY . .

# Build the Next.js app.
RUN npm run build

# Run the web service on container startup.
CMD ["npm", "start"]
EOL

    gcloud builds submit frontend --tag $FRONTEND_IMAGE_TAG --default-buckets-behavior=regional-user-owned-bucket

    # Clean up the temporary Dockerfile
    rm frontend/Dockerfile

    echo "Deploying the frontend to Cloud Run..."
    gcloud run deploy $FRONTEND_SERVICE_NAME \
        --image $FRONTEND_IMAGE_TAG \
        --platform managed \
        --region $REGION \
        --allow-unauthenticated \
        --set-env-vars="BACKEND_URL=$BACKEND_URL"

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
    cloudbuild.googleapis.com

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
echo ""
echo "Note: You may need to configure a GCS bucket named '$PROJECT_ID-bucket' and grant the backend service account access to it."
