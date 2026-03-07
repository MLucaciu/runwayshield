"""
Windows equivalent of run.sh — uses Waitress (pure-Python WSGI server)
with a thread pool matching the Linux gunicorn gthread configuration.

Waitress uses a channel-based async acceptor with a thread pool for request
handling, which closely mirrors gunicorn's gthread worker (1 process, N
threads sharing in-process state like cameras).

Usage:
    python run_windows.py
    # or with overrides:
    set PORT=8081 && set THREADS=16 && python run_windows.py
"""

import os
import sys

# Force unbuffered stdout/stderr so print() from Flask threads appears immediately
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(line_buffering=True)
os.environ["PYTHONUNBUFFERED"] = "1"

os.environ.setdefault("CAMERA_2_URL", "http://localhost:8554/video")
os.environ.setdefault("MQTT_BROKER_PORT", "53776")

from waitress import serve
from app import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8081))
    threads = int(os.environ.get("THREADS", 32))

    print(f"Starting Runway Shield backend on port {port} "
          f"(waitress, {threads} threads)...")
    print(f"  CAMERA_2_URL = {os.environ.get('CAMERA_2_URL', '(not set)')}")
    print(f"  MQTT_BROKER_HOST = {os.environ.get('MQTT_BROKER_HOST', 'localhost')}"
          f":{os.environ.get('MQTT_BROKER_PORT', '1883')}")

    serve(
        app,
        host="0.0.0.0",
        port=port,
        threads=threads,
        channel_timeout=86400,      # 24h — effectively no timeout (matches gunicorn --timeout 0)
        recv_bytes=65536,
        url_scheme="http",
    )
