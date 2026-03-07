#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

export CAMERA_1_URL="${CAMERA_1_URL:-http://localhost:8554/video}"
export CAMERA_2_URL="${CAMERA_2_URL:-http://localhost:8555/video}"
export YOLO_MODEL_PATH="yolo26s.pt"

PORT="${PORT:-8081}"
WORKERS="${WORKERS:-1}"

THREADS="${THREADS:-100}"

echo "Starting Runway Shield backend on port $PORT ($WORKERS worker, $THREADS threads, WebSocket enabled)..."
exec gunicorn \
  -w "$WORKERS" \
  --threads "$THREADS" \
  --bind "0.0.0.0:$PORT" \
  --timeout 0 \
  --log-level info \
  app:app
