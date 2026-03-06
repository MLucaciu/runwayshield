# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Runway Shield** — Airport runway monitoring and hazard detection system built for HackTech Oradea. Uses YOLO object detection with ByteTrack tracking on camera feeds to detect runway hazards, with a Flask API backend and React frontend dashboard.

## Commands

### Backend (Flask + Gunicorn, Python 3.10+)
```bash
cd backend
pip install -r requirements.txt   # install deps
./run.sh                          # production: gunicorn on :8081 (gthread, 1 worker, 16 threads)
python app.py                     # dev server on :8081 (Flask threaded, supports debugger)
pytest                            # run all tests
pytest tests/test_app.py::test_status  # run single test
```

**Important:** Must use 1 gunicorn worker (`-w 1`) — cameras are in-process state and cannot be shared across processes. Concurrency is handled by threads (default 16), not workers. The `run.sh` script is pre-configured correctly.

Environment variables for `run.sh`: `PORT` (default 8081), `WORKERS` (default 1, do not increase), `THREADS` (default 16).

### Frontend (React 19, CRA)
```bash
cd frontend
npm install       # install deps
npm start         # dev server on :3000 (proxies /api to :8081)
npm test          # run tests (jest, interactive)
npm run build     # production build
```

### Dev Container (Docker)
Open in VS Code/Cursor → "Dev Containers: Reopen in Container". Auto-installs all deps.

## Architecture

- **`backend/app.py`** — Flask API server with CORS. Serves REST endpoints under `/api/`. Runs on port 8081.
- **`backend/run.sh`** — Gunicorn startup script (gthread worker, 1 process, 16 threads). Use this for production/demo.
- **`backend/tests/`** — Pytest tests using Flask's test client.
- **`frontend/`** — Create React App project. `package.json` has `"proxy": "http://localhost:8081"` so `/api/*` calls forward to Flask in dev.
- **`frontend/src/App.js`** — Main React component; fetches `/api/status` and renders dashboard UI.
- **`models_testing/yolo.py`** — Standalone YOLO11 + ByteTrack script for camera feed processing with object tracking and trajectory visualization. Uses `ultralytics` library (not in backend requirements — separate experiment). Expects MJPEG camera stream URL and `yolo11n-seg.pt` model file in project root.
- **`backend/templates/`** — Jinja2 templates directory (currently empty).
- **`backend/videos/`** — Video storage directory (currently empty).

## Key Details

- Backend uses `flask-cors` — all origins allowed.
- Frontend proxy means no CORS config needed in dev for API calls.
- YOLO model file (`yolo11n-seg.pt`) is gitignored / not in repo — must be downloaded separately for `models_testing/`.
- Python venv is at `.venv/` (Python 3.11).
