import atexit
import os
import time
from datetime import datetime, timedelta, timezone

from flask import Flask, Response, jsonify, render_template, request, send_file
from flask_cors import CORS

from camera import CameraStream
from detector import Detector
from detections_db import DetectionsDB
from notifications_db import NotificationsDB
from mqtt_client import MQTTNotificationClient

app = Flask(__name__)
CORS(app)

# ---------------------------------------------------------------------------
# Camera registry
# ---------------------------------------------------------------------------
CAMERA_CONFIG = {
    "camera_1": {
        "url": os.environ.get("CAMERA_1_URL", "0"),
        "name": "Runway Main",
        "location": {"lat": 47.0365, "lng": 21.9484},
    },
    "camera_2": {
        "url": os.environ.get("CAMERA_2_URL", "http://10.1.0.74:8080/video"),
        "name": "Runway Side",
        "location": {"lat": 49.0365, "lng": 21.9484},
    },
}

cameras: dict[str, CameraStream] = {}
_cameras_started = False

YOLO_MODEL = os.environ.get("YOLO_MODEL_PATH", "yolo11n-seg.pt")
MQTT_BROKER_HOST = os.environ.get("MQTT_BROKER_HOST", "localhost")
MQTT_BROKER_PORT = int(os.environ.get("MQTT_BROKER_PORT", "1883"))
SOURCE_IP = os.environ.get("SOURCE_IP", None)  # auto-detected if not set

_detections_db = None
_notifications_db = None
_mqtt_client = None


def _shutdown():
    for cam_id, cam in cameras.items():
        print(f"[camera] {cam_id} shutting down…")
        cam.stop()
    if _mqtt_client:
        _mqtt_client.stop()

atexit.register(_shutdown)


def start_cameras():
    global _cameras_started, _detections_db, _notifications_db, _mqtt_client
    if _cameras_started:
        return
    _cameras_started = True

    # Initialise databases
    _detections_db = DetectionsDB(os.path.join("data", "detections.db"))
    _notifications_db = NotificationsDB(os.path.join("data", "notifications.db"))

    # Start MQTT client
    _mqtt_client = MQTTNotificationClient(
        _notifications_db,
        broker_host=MQTT_BROKER_HOST,
        broker_port=MQTT_BROKER_PORT,
        source_ip=SOURCE_IP,
    )
    _mqtt_client.start()
    try:
        _test_detector = Detector(YOLO_MODEL)
        del _test_detector
        print(f"[yolo] Model ready: {YOLO_MODEL}")
        yolo_ok = True
    except Exception as e:
        print(f"[yolo] Could not load model ({YOLO_MODEL}): {e}")
        yolo_ok = False

    for cam_id, cfg in CAMERA_CONFIG.items():
        detector = Detector(YOLO_MODEL) if yolo_ok else None
        cam = CameraStream(camera_id=cam_id, url=cfg["url"], video_dir="videos",
                           buffer_seconds=45, detector=detector,
                           detections_db=_detections_db,
                           mqtt_client=_mqtt_client)
        try:
            cam.start()
            cameras[cam_id] = cam
            print(f"[camera] {cam_id} started ({cfg['url']})")
        except ConnectionError as e:
            print(f"[camera] {cam_id} failed to start: {e}")


# When Werkzeug's debug reloader is active, the module is imported twice: once in
# the watcher parent and once in the child that serves (WERKZEUG_RUN_MAIN="true").
# Only open cameras in the serving process to avoid double-grabbing the source.
@app.before_request
def _ensure_cameras():
    start_cameras()


def _camera_json(cam_id):
    """Build the camera object the React frontend expects."""
    cfg = CAMERA_CONFIG.get(cam_id, {})
    cam = cameras.get(cam_id)
    online = cam is not None
    return {
        "id": cam_id,
        "name": cfg.get("name", cam_id),
        "stream_url": f"/api/stream/{cam_id}/live",
        "annotated_stream_url": f"/api/stream/{cam_id}/live?annotated=1",
        "online": online,
        "connected": cam.connected if cam else False,
        "detection_enabled": cam.has_detector if cam else False,
        "location": cfg.get("location"),
        "buffer_start": cam.buffer_start_time().isoformat() if cam and cam.buffer_start_time() else None,
        "segments": cam.list_segments() if cam else [],
        "annotated_segments": cam.list_segments(annotated=True) if cam else [],
    }


# ---------------------------------------------------------------------------
# Index (Jinja2 template fallback)
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/test-delay")
def test_delay():
    return """<!DOCTYPE html>
<html><head><title>5s delay test</title></head>
<body style="margin:0;background:#000;display:flex;justify-content:center;align-items:center;height:100vh;">
<img src="/api/stream/camera_1/live?offset=5" style="max-width:100%;max-height:100%;">
</body></html>"""


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

@app.route("/api/status")
def status():
    return jsonify({
        "message": "Runway Shield is online. All systems operational.",
        "status": "ok",
        "cameras": {cam_id: {"url": CAMERA_CONFIG[cam_id]["url"]} for cam_id in cameras},
    })


# ---------------------------------------------------------------------------
# Camera list — returns JSON array for the React frontend
# ---------------------------------------------------------------------------

@app.route("/api/cameras")
def list_cameras():
    result = []
    for cam_id in CAMERA_CONFIG:
        result.append(_camera_json(cam_id))
    return jsonify(result)


# ---------------------------------------------------------------------------
# Notifications — backed by SQLite, broadcast via MQTT
# ---------------------------------------------------------------------------

@app.route("/api/notifications/history")
def notifications_history():
    if not _notifications_db:
        return jsonify([])
    limit = request.args.get("limit", 100, type=int)
    from_ts = request.args.get("from")
    to_ts = request.args.get("to")
    return jsonify(_notifications_db.query_history(limit=limit, from_ts=from_ts, to_ts=to_ts))


@app.route("/api/notifications/live")
def notifications_live():
    if not _notifications_db:
        return jsonify([])
    return jsonify(_notifications_db.query_live())


@app.route("/api/notifications", methods=["POST"])
def create_notification():
    if not _mqtt_client:
        return jsonify({"error": "MQTT not initialised"}), 503
    data = request.get_json(force=True)
    camera_id = data.get("camera_id", "")
    classification = data.get("classification", "Unknown event")
    severity = data.get("severity", "low")
    notif_type = data.get("type", "detection")
    notification = _mqtt_client.publish_notification(
        camera_id=camera_id,
        classification=classification,
        severity=severity,
        notif_type=notif_type,
    )
    return jsonify(notification), 201


@app.route("/api/notifications/<notif_id>/resolve", methods=["POST"])
def resolve_notification(notif_id):
    if not _mqtt_client:
        return jsonify({"error": "MQTT not initialised"}), 503
    _mqtt_client.resolve_notification(notif_id)
    return jsonify({"status": "resolved"})


# ---------------------------------------------------------------------------
# Airport info — placeholder environmental & runway data
# TODO: integrate real weather API and runway management system
# ---------------------------------------------------------------------------

@app.route("/api/airport-info")
def airport_info():
    return jsonify({
        "name": "Aeroportul Internațional Oradea",
        "code": "OMR",
        "environmental": {
            "temperature": 20,
            "temperature_unit": "C",
            "wind_speed": 7,
            "wind_unit": "km/h",
        },
        "runway_status": {
            "live_incidents": 3,
            "past_24hr": 7,
            "surface_condition": "Dry",
        },
    })


# ---------------------------------------------------------------------------
# API 1 — Live stream (MJPEG, ring buffer, offset 0-30s)
# GET /api/stream/<camera_id>/live?offset=<seconds>
#   offset=0 (default) → real-time live
#   offset=5           → always 5s behind live, persistently
# ---------------------------------------------------------------------------

@app.route("/api/stream/<camera_id>/live")
def live_stream(camera_id):
    cam = cameras.get(camera_id)
    if not cam:
        return jsonify({"error": "Camera not found"}), 404

    annotated = request.args.get("annotated", "0") == "1"
    offset = min(request.args.get("offset", 0, type=float), 30)

    def generate():
        if offset <= 0:
            # Real-time: serve frames as they arrive
            while True:
                if annotated and cam.has_detector:
                    jpeg = cam.wait_for_annotated_frame(timeout=1.0)
                else:
                    jpeg = cam.wait_for_frame(timeout=1.0)
                if jpeg:
                    yield (b"--frame\r\n"
                           b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n")
        else:
            # Delayed: continuously serve the frame from `offset` seconds ago
            last_jpeg = None
            while True:
                target = datetime.now(timezone.utc) - timedelta(seconds=offset)
                jpeg = cam.get_frame_at(target)
                if jpeg and jpeg is not last_jpeg:
                    last_jpeg = jpeg
                    yield (b"--frame\r\n"
                           b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n")
                time.sleep(1 / cam.fps)

    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


# ---------------------------------------------------------------------------
# API 2 — Historical playback (MP4 segment by unix timestamp)
# GET /api/stream/<camera_id>/history?t=<unix_timestamp>
#   Returns the MP4 segment that covers the given timestamp.
# ---------------------------------------------------------------------------

@app.route("/api/stream/<camera_id>/history")
def history_stream(camera_id):
    cam = cameras.get(camera_id)
    if not cam:
        return jsonify({"error": "Camera not found"}), 404

    annotated = request.args.get("annotated", "0") == "1"
    t = request.args.get("t", type=float)
    if t is None:
        return jsonify({"error": "Missing 't' query param (unix timestamp)"}), 400

    target = datetime.fromtimestamp(t, tz=timezone.utc)

    for seg_name in cam.list_segments(annotated=annotated):
        seg_ts_str = seg_name.replace(".mp4", "").rstrip("Z")
        try:
            seg_ts = datetime.strptime(seg_ts_str, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        seg_end = seg_ts + timedelta(seconds=cam.segment_seconds)
        if seg_ts <= target < seg_end:
            path = cam.segment_path(seg_name, annotated=annotated)
            if os.path.isfile(path):
                return send_file(path, mimetype="video/mp4")

    return jsonify({"error": "No segment found for the given timestamp"}), 404


# ---------------------------------------------------------------------------
# Detections — query YOLO detection history from SQLite
# ---------------------------------------------------------------------------

@app.route("/api/detections/<camera_id>")
def get_detections(camera_id):
    if not _detections_db:
        return jsonify([])
    limit = request.args.get("limit", 100, type=int)
    from_ts = request.args.get("from")
    to_ts = request.args.get("to")
    results = _detections_db.query(camera_id, limit=limit,
                                   from_ts=from_ts, to_ts=to_ts)
    return jsonify(results)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8081))
    app.run(host="0.0.0.0", port=port, debug=True, threaded=True)
