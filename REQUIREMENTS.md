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

### Live notifications
`GET /api/notifications/live`
- Returns all active notifications (`timestamp_end IS NULL`)
- Also pushed in real-time via Socket.IO

### Historical notifications
`GET /api/notifications/history`
- Query params: `type`, `severity`, `source`, `status`, `from`, `to`
- Paginated, sorted by `timestamp_start` desc

### Validate notification
`PATCH /api/notifications/<id>/validate`
- Body: `{ "status": "valid" | "invalid", "validated_by": "username" }`

### Trigger action
`POST /api/notifications/<id>/action`
- Body: `{ "action": "deploy_robot" | "enhance_image" | "night_to_day" }`
- Sends ESPHome command if applicable (e.g., robot dispatch)

### Video / stream
- Live annotated MJPEG stream per camera
- Historical playback resolved by `source` + timestamp range

### Heatmap
- Endpoint returning aggregated `{x, y, count}` data for historical debris/hazard locations

### Sensor data
- Proxy to Prometheus or direct ESPHome REST API reads

## 7. Live Streaming

- **Video**: MJPEG stream with YOLO annotations served from Flask backend
- **Real-time events**: Socket.IO (Flask-SocketIO) pushes:
  - New/updated notifications
  - Map object position updates
  - Alert feed updates
- **Evidence linking**: notifications store `source` + `timestamp_start`/`timestamp_end`; the UI resolves this to the correct video stream for playback

## 8. Video Storage & Playback

Two-layer design to support both near-live rewind and historical playback:

### Layer 1 — In-memory ring buffer (near-live rewind)
- `collections.deque` per camera holding the last **30 seconds** of frames
- Each entry: `(timestamp, jpeg_bytes)` — pre-encoded JPEG for fast serving
- ~900 frames at 30fps, ~45MB per camera
- When user seeks back 1-30s from live, frames are served from this buffer as an MJPEG burst
- No disk I/O, instant response

### Layer 2 — Disk segments (historical playback)
- OpenCV `VideoWriter` writes **30-second MP4 chunks** per camera
- **Both raw and annotated** video saved:
  - Raw: `videos/{camera_id}/raw/{timestamp_start}.mp4`
  - Annotated: `videos/{camera_id}/annotated/{timestamp_start}.mp4`
- When a segment completes (30s elapsed), the writer finalizes it and starts a new one
- For playback, UI resolves `camera_id` + `timestamp` → correct segment file

### Annotations (SQLite)

`detections` table — decoupled from video files:

| Field | Type | Notes |
|---|---|---|
| `id` | integer PK | Auto-increment |
| `camera_id` | string | `camera_1`, `camera_2`, etc. |
| `timestamp` | datetime | Frame timestamp |
| `frame_number` | integer | Frame index within the segment |
| `detections_json` | JSON | Array of `{class, confidence, bbox, track_id, mask_polygon}` |

This allows the UI to re-render annotations on raw video during playback, or play the pre-annotated version directly.

### Video API endpoints

- `GET /api/stream/<camera_id>/live` — MJPEG live stream (annotated)
- `GET /api/stream/<camera_id>/playback?from=<ts>&to=<ts>&type=raw|annotated` — unified playback endpoint. Backend transparently resolves the source:
  - If `from` is within last 30s → serve from ring buffer
  - If `from` is older → serve from disk segments
  - If range spans both → stitch buffer + disk seamlessly
  - Response format is the same regardless of source (MJPEG stream)

### Processing flow

```
IP Camera (MJPEG)
  → OpenCV reader thread (MJPEGCamera)
  → YOLO .track(frame) → annotated frame
  → ring buffer (deque, 30s)
  → VideoWriter (raw 30s MP4 chunk → disk)
  → VideoWriter (annotated 30s MP4 chunk → disk)
  → MJPEG live stream endpoint
  → insert detection metadata → SQLite
  → emit Socket.IO event (if notification triggered)
```

## 9. Metadata Storage

- **SQLite**: notifications, detections (per-frame), sensor readings, map coordinates
- **Filesystem**: video segments (`videos/{camera_id}/{raw|annotated}/{timestamp}.mp4`)

## 9. Map & Heatmap

- **Static runway image** with defined coordinate system
- **Live view**: detected objects plotted on map in real-time with labels and track trails
- **Heatmap**: accumulated historical detection positions rendered as heat overlay
- All map data stored for historical review

## 10. ESPHome Integration

- **Inbound**: poll sensor data (humidity, temp, rain) via ESPHome REST API
- **Outbound**: send notifications/commands to ESPHome devices
  - Robot dispatch on severe alerts
  - Alarm triggers
  - Status queries

## 11. Reports

- Daily and weekly report generation
- Summary: detection counts by type/severity, alert response times, weather conditions, heatmap snapshots

## 12. Tech Stack

| Layer | Technology |
|---|---|
| Backend | Flask, Flask-SocketIO |
| ML / Vision | Ultralytics YOLO (from `models_testing/`), ByteTrack, OpenCV |
| Database | SQLite |
| Frontend | React, Socket.IO client |
| Sensors | ESPHome REST API |
| Metrics | Prometheus |
| Video streaming | MJPEG |
