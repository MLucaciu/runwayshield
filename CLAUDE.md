# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Runway Shield** — Airport runway monitoring and hazard detection system built for HackTech Oradea. Uses YOLO object detection with ByteTrack tracking on camera feeds to detect runway hazards, with a Flask API backend and React frontend dashboard.

## Commands

### Backend (Flask, Python 3.10+)
```bash
cd backend
pip install -r requirements.txt   # install deps
python app.py                     # run dev server on :5000
pytest                            # run all tests
pytest tests/test_app.py::test_status  # run single test
```

### Frontend (React 19, CRA)
```bash
cd frontend
npm install       # install deps
npm start         # dev server on :3000 (proxies /api to :5000)
npm test          # run tests (jest, interactive)
npm run build     # production build
```

### Dev Container (Docker)
Open in VS Code/Cursor → "Dev Containers: Reopen in Container". Auto-installs all deps.

## Architecture

- **`backend/app.py`** — Flask API server with CORS. Serves REST endpoints under `/api/`. Runs on port 5000.
- **`backend/tests/`** — Pytest tests using Flask's test client.
- **`frontend/`** — Create React App project. `package.json` has `"proxy": "http://localhost:5000"` so `/api/*` calls forward to Flask in dev.
- **`frontend/src/App.js`** — Main React component; fetches `/api/status` and renders dashboard UI.
- **`models_testing/yolo.py`** — Standalone YOLO11 + ByteTrack script for camera feed processing with object tracking and trajectory visualization. Uses `ultralytics` library (not in backend requirements — separate experiment). Expects MJPEG camera stream URL and `yolo11n-seg.pt` model file in project root.
- **`backend/templates/`** — Jinja2 templates directory (currently empty).
- **`backend/videos/`** — Video storage directory (currently empty).

## Key Details

- Backend uses `flask-cors` — all origins allowed.
- Frontend proxy means no CORS config needed in dev for API calls.
- YOLO model file (`yolo11n-seg.pt`) is gitignored / not in repo — must be downloaded separately for `models_testing/`.
- Python venv is at `.venv/` (Python 3.11).
