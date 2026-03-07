# Runway Shield

Airport runway monitoring and hazard detection system — HackTech Oradea.

Uses YOLO object detection with ByteTrack tracking on live camera feeds to detect runway hazards, with a Flask API backend and React frontend dashboard.

## Prerequisites

- **Python 3.10+** — [python.org/downloads](https://www.python.org/downloads/)
- **Node.js 18+** — [nodejs.org](https://nodejs.org/)
- **FFmpeg** — required for video segment recording
- (Optional) [Docker](https://docs.docker.com/get-docker/) for the Dev Container

### YOLO Model

Download the YOLO11n segmentation model and place it in the `backend/` directory (or project root):

```bash
cd backend
# Download yolo11n-seg.pt from Ultralytics
# https://docs.ultralytics.com/models/yolo11/
```

If the model file is not present, the app starts normally with detection disabled.
Set `YOLO_MODEL_PATH` to override the default path.

## Getting started

```bash
git clone <repo-url>
cd runwayshield
```

### Option A — Run locally

#### 1. Backend

```bash
cd backend
pip install -r requirements.txt
python app.py          # dev server on :8081

# or production:
./run.sh               # gunicorn on :8081
```

#### 2. Frontend

```bash
cd frontend
npm install
npm start              # dev server on :3000, proxies /api to :8081
```

#### 3. Open the app

Go to **http://localhost:3000**.

---

### Option B — Dev Container (Docker)

1. Open in VS Code / Cursor
2. **Dev Containers: Reopen in Container**
3. Backend: `cd /workspace/backend && python app.py`
4. Frontend: `cd /workspace/frontend && npm start`
5. Open **http://localhost:3000**

---

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /api/status` | System health check |
| `GET /api/cameras` | List cameras with status and detection info |
| `GET /api/stream/<id>/live` | Live MJPEG stream. `?annotated=1` for YOLO overlay, `?offset=N` for N-second delay |
| `GET /api/stream/<id>/history?t=<unix>` | Historical MP4 segment. `?annotated=1` for annotated version |
| `GET /api/detections/<id>` | Query detection history from SQLite. `?limit=N`, `?from=<iso>`, `?to=<iso>` |
| `GET /api/notifications/history` | Alert history |
| `GET /api/notifications/live` | Live alerts |
| `GET /api/airport-info` | Airport and runway metadata |

### Camera Emulator (optional)

Loops a video file as an MJPEG stream to emulate a live camera. See [`cam_emulator/README.md`](cam_emulator/README.md) for details.

```bash
cd cam_emulator
pip install -r requirements.txt
./run.sh               # MJPEG stream on :8554

# Then point the backend at it:
CAMERA_1_URL=http://localhost:8554/video
```

## Running tests

```bash
cd backend && pytest
cd frontend && npm test
```

## Project structure

```
backend/
  app.py              Flask API server
  camera.py           Camera capture, ring buffer, segment recording
  detector.py         YOLO segmentation + ByteTrack wrapper
  detections_db.py    SQLite storage for detections
  run.sh              Gunicorn startup script
  requirements.txt    Python dependencies
  data/               SQLite database (auto-created, gitignored)
  videos/             Video segments (auto-created, gitignored)
  tests/              Pytest tests
frontend/
  src/App.js          Main React dashboard component
  src/                Components & styles
  public/             Static assets
cam_emulator/         Standalone MJPEG camera emulator (loops a video file)
models_testing/       Standalone ML experiments
.devcontainer/        Dev Container config
```

## Ports

| Service  | Port | URL                  |
|----------|------|----------------------|
| Frontend       | 3000 | http://localhost:3000 |
| Backend        | 8081 | http://localhost:8081 |
| Cam Emulator   | 8554 | http://localhost:8554 |

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `PORT` | `8081` | Backend server port |
| `WORKERS` | `1` | Gunicorn workers (keep at 1) |
| `THREADS` | `16` | Gunicorn threads |
| `YOLO_MODEL_PATH` | `yolo11n-seg.pt` | Path to YOLO model file |
| `CAMERA_1_URL` | `0` | Camera 1 source (device index or URL) |
| `CAMERA_2_URL` | `http://10.1.0.74:8080/video` | Camera 2 source |
