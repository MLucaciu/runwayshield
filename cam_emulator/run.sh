#!/usr/bin/env bash
# Start the camera emulator (two feeds: port 8554 + 8555)
#
# Automatically creates a venv and installs dependencies if needed.
set -e
cd "$(dirname "$0")"

VENV_DIR=".venv"

# Create venv if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

# Activate venv
source "$VENV_DIR/bin/activate"

# Install requirements if opencv is not available
if ! python -c "import cv2" 2>/dev/null; then
    echo "Installing dependencies..."
    pip install -r requirements.txt
fi

exec python emulator.py "$@"
