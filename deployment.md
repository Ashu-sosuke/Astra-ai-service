# Deployment Instructions - SOS Intelligence AI Microservice

## Prerequisites
- Google Cloud SDK (`gcloud`) installed
- Docker installed (for local testing)
- A Google Cloud Project with Billing enabled

## 1. Local Testing
Build and run the Docker container locally to verify functionality.

```bash
docker build -t sos-ai-service .
docker run -p 8080:8080 sos-ai-service
```

Test the health endpoint:
```bash
curl http://localhost:8080/health
```

## 2. Deploy to Google Cloud Run

### Step 1: Initialize gcloud
```bash
gcloud auth login
gcloud config set project [YOUR_PROJECT_ID]
```

### Step 2: Build and Push Image to Artifact Registry
Enable the Artifact Registry API if not already enabled.

```bash
# Create repository (run once)
gcloud artifacts repositories create sos-repo --repository-format=docker \
    --location=us-central1 --description="SOS App Repository"

# Configure Docker to use gcloud credentials
gcloud auth configure-docker us-central1-docker.pkg.dev

# Build and Push
gcloud builds submit --tag us-central1-docker.pkg.dev/[YOUR_PROJECT_ID]/sos-repo/ai-service:v1 .
```

### Step 3: Deploy to Cloud Run
Deploy the service with appropriate memory and CPU settings.

> [!IMPORTANT]
> This service uses ML models (Whisper + DistilBERT). Recommend at least **4GB RAM** and **2 CPUs**.

```bash
gcloud run deploy sos-ai-service \
    --image us-central1-docker.pkg.dev/[YOUR_PROJECT_ID]/sos-repo/ai-service:v1 \
    --platform managed \
    --region us-central1 \
    --allow-unauthenticated \
    --memory 4Gi \
    --cpu 2 \
    --concurrency 10 \
    --min-instances 0 \
    --max-instances 10
```

## Scaling Configuration
- **Min Instances**: 0 (to save cost) or 1 (to avoid cold starts ~10s).
- **Max Instances**: 10 (limit scaling for safety).
- **Concurrency**: 10 (FastAPI is async, but model inference is CPU bound. Adjust based on load testing.)

## Environment Variables
Set these via Cloud Console or `--set-env-vars`:
- `WHISPER_MODEL_SIZE`: "tiny" (default)
- `ENABLE_EMOTION_DETECTION`: "true"
