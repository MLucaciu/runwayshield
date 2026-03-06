#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

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
