# Runway Shield — Requirements

## 1. System Overview

Airport runway monitoring and hazard detection system. Fixed IP cameras feed video through YOLO instance segmentation to detect runway incursions (animals, people, FOD). Environmental sensors provide weather context. The system classifies alerts by severity, requires user validation, and triggers appropriate actions.

Two notification types:
- **Runway Incursion** — object detected on/near runway by camera
- **Environment** — hazardous weather condition from sensors

Live dashboard shows annotated video, runway map with detected objects, and real-time alerts. All data is stored for historical playback, heatmaps, and reporting.

## 2. Input Sources

### IP Cameras
- Fixed position cameras streaming MJPEG
- Captured via OpenCV `VideoCapture`
- Multiple cameras supported (`camera_1`, `camera_2`, etc.)

### ESPHome Sensors
- Humidity, temperature, rain sensors
- Communication via **ESPHome REST API** (read sensors, send commands)

### Prometheus
- Sensor data stored in Prometheus for time-series queries
- Used for historical sensor data correlation with alerts

## 3. Video Processing Pipeline

- **Frame capture**: OpenCV reads MJPEG streams from IP cameras (threaded reader as in `models_testing/yolo.py`)
- **Model**: YOLO instance segmentation (`yolo11n-seg.pt`) from `models_testing/` directory
  - Bounding boxes around detected objects
  - Pixel-level segmentation masks with labels
- **Tracking**: ByteTrack (`model.track(frame, persist=True, tracker="bytetrack.yaml")`) for object tracking across frames
  - Trajectory history per track ID
  - Direction/velocity arrows for trajectory prediction
- **Motion detection**: frame differencing for supplementary movement detection
- **Coordinate mapping**: pixel coordinates → static runway map `{x, y}` positions

## 4. Notification Data Model

Single `notifications` table (SQLite):

| Field | Type | Nullable | Notes |
|---|---|---|---|
| `id` | integer PK | no | Auto-increment |
| `type` | enum | no | `incursion`, `environment` |
| `severity` | enum | no | `low`, `medium`, `severe` |
| `status` | enum | no | `pending`, `valid`, `invalid` |
| `validated_by` | string | yes | Null until validated |
| `validated_at` | datetime | yes | Null until validated |
| `action_taken` | enum | yes | `deploy_robot`, `enhance_image`, `night_to_day` |
| `action_at` | datetime | yes | When action was triggered |
| `timestamp_start` | datetime | no | First detection frame / sensor trigger |
| `timestamp_end` | datetime | yes | Null = still active (ongoing detection) |
| `source` | string | no | `camera_1`, `camera_2`, `robot_1`, `esphome_sensor_1` |
| `classification` | string | no | Incursion: `dog`, `person`, `fod`, `bird`, `vehicle`. Environment: `low_temp`, `high_temp`, `high_humidity`, `rain` |
| `runway_location` | JSON | yes | `{x, y}` on runway map — incursion only |
| `track_id` | integer | yes | ByteTrack object ID — incursion only |
| `sensor_value` | float | yes | Actual reading — environment only |
| `sensor_unit` | string | yes | `°C`, `%`, `mm/h` — environment only |
| `created_at` | datetime | no | Record creation time |

### Timestamp semantics
- `timestamp_start` = first frame the object was detected / sensor crossed threshold
- `timestamp_end` = last frame detected / sensor returned to normal (null while ongoing)

## 5. Alert Severity & Actions

After user validation, actions per severity:

| Severity | Action | Description |
|---|---|---|
| Severe | `deploy_robot` | Send ESPHome command to dispatch inspection robot |
| Medium | `enhance_image` | Apply 2-4X image enhancement on detection area |
| Low | `night_to_day` | Apply night-to-day filter for improved visibility |

## 6. API Endpoints

### Implemented

#### Camera list
`GET /api/cameras`
- Returns JSON array of camera objects: `id`, `name`, `stream_url`, `online`, `connected`, `location`, `buffer_start`, `segments`

#### System status
`GET /api/status`
- Returns system health, online cameras

#### Live stream (API 1 — ring buffer)
`GET /api/stream/<camera_id>/live?offset=<seconds>`
- MJPEG stream from the ring buffer
- `offset=0` (default): real-time live feed
- `offset=N` (max 30): persistent N-second delay — continuously serves the frame from N seconds ago (YouTube Live-style rewind)

#### Historical playback (API 2 — disk segments)
`GET /api/stream/<camera_id>/history?t=<unix_timestamp>`
- Returns the MP4 segment file covering the given timestamp
- Backend matches timestamp against wall-clock-aligned segment filenames

#### Notification stubs
- `GET /api/notifications/live` — returns `[]` (stub)
- `GET /api/notifications/history` — returns `[]` (stub)

### Planned (not yet implemented)

#### Validate notification
`PATCH /api/notifications/<id>/validate`
- Body: `{ "status": "valid" | "invalid", "validated_by": "username" }`

#### Trigger action
`POST /api/notifications/<id>/action`
- Body: `{ "action": "deploy_robot" | "enhance_image" | "night_to_day" }`
- Sends ESPHome command if applicable (e.g., robot dispatch)

#### Heatmap
- Endpoint returning aggregated `{x, y, count}` data for historical debris/hazard locations

#### Sensor data
- Proxy to Prometheus or direct ESPHome REST API reads

## 7. Live Streaming

- **Video**: MJPEG stream served from Flask backend (annotations not yet applied)
- **Real-time events** (planned): Socket.IO (Flask-SocketIO) pushes:
  - New/updated notifications
  - Map object position updates
  - Alert feed updates
- **Evidence linking**: notifications store `source` + `timestamp_start`/`timestamp_end`; the UI resolves this to the correct video stream for playback

## 8. Video Storage & Playback

Two-layer design to support both near-live rewind and historical playback:

### Layer 1 — In-memory ring buffer (implemented)
- `collections.deque` per camera holding the last **45 seconds** of frames (`buffer_seconds=45`)
- Each entry: `(UTC datetime, jpeg_bytes)` — pre-encoded JPEG for fast serving
- Buffer sized dynamically: `buffer_seconds * measured_fps` (fps auto-measured on camera start)
- **Persistent delay**: `get_frame_at(target_ts)` binary-search-like lookup returns the frame closest to a target timestamp, enabling YouTube Live-style continuous delayed playback
- No disk I/O, instant response

### Layer 2 — Disk segments (implemented)
- OpenCV `VideoWriter` writes **30-second MP4 chunks** per camera
- **Wall-clock aligned**: segments start at `:00` and `:30` second boundaries
  - Camera starting at 17:25 → first segment named `...T172500Z.mp4`, rotates at 17:30
  - `_segment_boundary_for()` computes slot start, `_next_segment_boundary()` computes rotation time
- Segment path: `videos/{camera_id}/raw/{YYYYMMDDTHHMMSSZ}.mp4`
- FPS auto-measured from actual camera feed (not hardcoded) to ensure correct segment duration
- Annotated segments planned: `videos/{camera_id}/annotated/{timestamp}.mp4`

### Camera resilience (implemented)
- **Startup retries**: 3 attempts with 2s delay between retries
- **Disconnect detection**: after 50 consecutive read failures (~0.5s), the segment is finalized and camera marked `connected=False`
- **Auto-reconnect**: when disconnected, attempts to reopen the camera every 2s
- **Reconnect recovery**: on successful reconnect, logs the event and resumes recording to a new segment
- `connected` status exposed via `/api/cameras` for frontend status display

### Annotations (planned — SQLite)

`detections` table — decoupled from video files:

| Field | Type | Notes |
|---|---|---|
| `id` | integer PK | Auto-increment |
| `camera_id` | string | `camera_1`, `camera_2`, etc. |
| `timestamp` | datetime | Frame timestamp |
| `frame_number` | integer | Frame index within the segment |
| `detections_json` | JSON | Array of `{class, confidence, bbox, track_id, mask_polygon}` |

This allows the UI to re-render annotations on raw video during playback, or play the pre-annotated version directly.

### Processing flow

```
IP Camera (MJPEG) or webcam (device index)
  → OpenCV VideoCapture (threaded, with retry + reconnect)
  → measure fps on start
  → encode frame to JPEG
  → ring buffer (deque, 45s)              ← Layer 1 (live + offset)
  → VideoWriter (raw 30s MP4 → disk)      ← Layer 2 (historical)
  → MJPEG live stream endpoint
  [planned] → YOLO .track(frame) → annotated frame
  [planned] → VideoWriter (annotated 30s MP4 → disk)
  [planned] → insert detection metadata → SQLite
  [planned] → emit Socket.IO event (if notification triggered)
```

## 9. Frontend (implemented)

Jinja2 template served at `/` with:
- **Camera selector** dropdown (shows camera name from config)
- **Live/delayed MJPEG viewer** (`<img>` tag pointing at API 1)
- **Historical MP4 player** (`<video>` tag pointing at API 2) with auto-advance to next segment on `ended` event
- **Seek controls**: LIVE, -5s, -10s, -30s, -120s buttons + custom offset input
  - 0-30s offset → API 1 (persistent delay via ring buffer)
  - >30s offset → API 2 (MP4 segment from disk)
- **Segment list** with click-to-play and progress bar
- **Connection status** polling every 3s, segment list refresh every 10s

## 10. Metadata Storage

- **SQLite** (planned): notifications, detections (per-frame), sensor readings, map coordinates
- **Filesystem** (implemented): video segments (`videos/{camera_id}/raw/{timestamp}.mp4`)

## 11. Map & Heatmap

- **Static runway image** with defined coordinate system
- **Live view**: detected objects plotted on map in real-time with labels and track trails
- **Heatmap**: accumulated historical detection positions rendered as heat overlay
- All map data stored for historical review

## 12. ESPHome Integration

- **Inbound**: poll sensor data (humidity, temp, rain) via ESPHome REST API
- **Outbound**: send notifications/commands to ESPHome devices
  - Robot dispatch on severe alerts
  - Alarm triggers
  - Status queries

## 13. Reports

- Daily and weekly report generation
- Summary: detection counts by type/severity, alert response times, weather conditions, heatmap snapshots

## 14. Tech Stack

| Layer | Technology |
|---|---|
| Backend | Flask, Flask-CORS (Flask-SocketIO planned) |
| ML / Vision | Ultralytics YOLO (from `models_testing/`), ByteTrack, OpenCV |
| Database | SQLite (planned) |
| Frontend | Jinja2 template (React planned), Socket.IO client (planned) |
| Sensors | ESPHome REST API |
| Metrics | Prometheus |
| Video streaming | MJPEG (live), MP4 segments (historical) |

## 15. Configuration

| Env var | Default | Description |
|---|---|---|
| `CAMERA_1_URL` | `0` (webcam) | IP camera URL or device index |
| `PORT` | `8081` | Backend server port |
