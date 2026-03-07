#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

export CAMERA_2_URL="${CAMERA_2_URL:-http://10.94.117.111:8554/video}"

PORT="${PORT:-8081}"
WORKERS="${WORKERS:-1}"

THREADS="${THREADS:-16}"

echo "Starting Runway Shield backend on port $PORT ($WORKERS worker, $THREADS threads)..."
exec gunicorn \
  -k gthread \
  -w "$WORKERS" \
  --threads "$THREADS" \
  --bind "0.0.0.0:$PORT" \
  --timeout 0 \
  --log-level info \
  app:app
