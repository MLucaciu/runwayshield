#!/usr/bin/env bash
set -e

PYTHON="/usr/local/bin/python3"
PIP="$PYTHON -m pip"
BACKEND_DIR="/workspace/backend"
FRONTEND_DIR="/workspace/frontend"

# --- Python / pip dependencies ---

if ! $PYTHON -c "import torch" 2>/dev/null; then
    echo "==> Installing torch + torchvision (CPU) ..."
    $PIP install --root-user-action=ignore \
        torch torchvision --index-url https://download.pytorch.org/whl/cpu
else
    echo "==> torch already installed, skipping."
fi

if $PIP show flask gunicorn ultralytics opencv-python-headless numpy > /dev/null 2>&1; then
    echo "==> All Python requirements already satisfied, skipping."
else
    echo "==> Installing Python packages from requirements.txt ..."
    $PIP install --root-user-action=ignore -r "$BACKEND_DIR/requirements.txt"
fi

# --- Node / npm dependencies ---

if [ -d "$FRONTEND_DIR/node_modules" ]; then
    echo "==> node_modules exists, skipping npm install."
else
    echo "==> Installing frontend npm packages ..."
    (cd "$FRONTEND_DIR" && npm install)
fi
