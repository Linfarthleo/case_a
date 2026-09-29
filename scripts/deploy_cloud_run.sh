#!/usr/bin/env bash
# Build and deploy to Google Cloud Run.
# Usage: PROJECT_ID=my-project REGION=us-central1 ./scripts/deploy_cloud_run.sh
# Secrets (e.g. LLM_API_KEY) come from Secret Manager, never from this script or the image.
set -euo pipefail

: "${PROJECT_ID:?PROJECT_ID is required}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-secure-rag-agent}"
REPO="${REPO:-containers}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${SERVICE}:$(git rev-parse --short HEAD)"

gcloud builds submit --project "${PROJECT_ID}" --tag "${IMAGE}" .

SECRET_FLAGS=()
if [[ "${LLM_PROVIDER:-mock}" != "mock" ]]; then
  # gcloud secrets create llm-api-key --data-file=-   (one-time, outside this script)
  SECRET_FLAGS=(--set-secrets "LLM_API_KEY=llm-api-key:latest")
fi

gcloud run deploy "${SERVICE}" \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --image "${IMAGE}" \
  --port 8080 \
  --cpu 1 --memory 512Mi \
  --min-instances 0 --max-instances 5 \
  --concurrency 40 \
  --timeout 30 \
  --set-env-vars "APP_ENV=${APP_ENV:-dev},LLM_PROVIDER=${LLM_PROVIDER:-mock},LLM_MODEL=${LLM_MODEL:-mock-model-v1},OTEL_ENABLED=true" \
  "${SECRET_FLAGS[@]}" \
  --allow-unauthenticated   # app-level auth (Bearer) is enforced by the service itself

gcloud run services describe "${SERVICE}" --project "${PROJECT_ID}" --region "${REGION}" \
  --format 'value(status.url)'
