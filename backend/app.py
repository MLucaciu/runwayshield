import atexit
import os
import time
from datetime import datetime, timedelta, timezone

import cv2
import numpy as np

from flask import Flask, Response, jsonify, render_template, request, send_file
from flask_cors import CORS

from camera import CameraStream
from detector import Detector
from detections_db import DetectionsDB
from notifications_db import NotificationsDB
from mqtt_client import MQTTNotificationClient
from alerts_db import AlertsDB
from zone_checker import ZoneChecker
from alert_manager import AlertManager
from esp_sensor_client import ESPSensorClient

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
        "url": os.environ.get("CAMERA_2_URL", "http://10.94.117.76:8080/video"),
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
_alerts_db = None
_mqtt_client = None
_zone_checker = None
_alert_manager = None
_esp_sensor = None


def _shutdown():
    for cam_id, cam in cameras.items():
        print(f"[camera] {cam_id} shutting down…")
        cam.stop()
    if _mqtt_client:
        _mqtt_client.stop()
    if _esp_sensor:
        _esp_sensor.stop()

atexit.register(_shutdown)


def start_cameras():
    global _cameras_started, _detections_db, _notifications_db, _mqtt_client
    global _alerts_db, _zone_checker, _alert_manager, _esp_sensor
    if _cameras_started:
        return
    _cameras_started = True

    # Initialise databases
    _detections_db = DetectionsDB(os.path.join("data", "detections.db"))
    _notifications_db = NotificationsDB(os.path.join("data", "notifications.db"))
    _alerts_db = AlertsDB(os.path.join("data", "alerts.db"))
    _alerts_db.clear_all()
    print("[alerts] Cleared alerts table on startup")

    # Start MQTT client
    _mqtt_client = MQTTNotificationClient(
        _notifications_db,
        broker_host=MQTT_BROKER_HOST,
        broker_port=MQTT_BROKER_PORT,
        source_ip=SOURCE_IP,
    )
    _mqtt_client.start()

    # Start ESP sensor MQTT client
    _esp_sensor = ESPSensorClient(
        broker_host=MQTT_BROKER_HOST,
        broker_port=MQTT_BROKER_PORT,
    )
    _esp_sensor.start()

    # Zone checking and alert management
    _zone_checker = ZoneChecker()
    _alert_manager = AlertManager(_alerts_db, mqtt_client=_mqtt_client, esp_sensor=_esp_sensor)

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
                           mqtt_client=_mqtt_client,
                           zone_checker=_zone_checker,
                           alert_manager=_alert_manager)
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


@app.route("/reports")
def reports_page():
    return render_template("reports.html")


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
# Alerts — zone-based alerts with lifecycle management
# ---------------------------------------------------------------------------

@app.route("/api/alerts/live")
def alerts_live():
    if not _alerts_db:
        return jsonify([])
    return jsonify(_alerts_db.query_live())


@app.route("/api/alerts/history")
def alerts_history():
    if not _alerts_db:
        return jsonify([])
    return jsonify(_alerts_db.query_history(
        limit=request.args.get("limit", 100, type=int),
        camera_id=request.args.get("camera_id"),
        zone_id=request.args.get("zone_id"),
        object_type=request.args.get("object_type"),
        severity=request.args.get("severity"),
        from_ts=request.args.get("from"),
        to_ts=request.args.get("to"),
    ))


@app.route("/api/alerts/reports")
def alerts_reports():
    if not _alerts_db:
        return jsonify([])
    return jsonify(_alerts_db.query_reports(
        limit=request.args.get("limit", 500, type=int),
        camera_id=request.args.get("camera_id"),
        zone_id=request.args.get("zone_id"),
        object_type=request.args.get("object_type"),
        severity=request.args.get("severity"),
        from_ts=request.args.get("from"),
        to_ts=request.args.get("to"),
    ))


@app.route("/api/alerts/<int:alert_id>")
def get_alert(alert_id):
    if not _alerts_db:
        return jsonify({"error": "Alerts not initialised"}), 503
    alert = _alerts_db.get_by_id(alert_id)
    if not alert:
        return jsonify({"error": "Alert not found"}), 404
    alert["logs"] = _alerts_db.get_logs(alert_id)
    return jsonify(alert)


@app.route("/api/alerts/<int:alert_id>/acknowledge", methods=["PATCH"])
def acknowledge_alert(alert_id):
    if not _alert_manager:
        return jsonify({"error": "Alert manager not initialised"}), 503
    data = request.get_json(force=True)
    username = data.get("acknowledged_by", "anonymous")
    result = _alert_manager.acknowledge(alert_id, username)
    if not result:
        return jsonify({"error": "Alert not found or already acknowledged/closed"}), 404

    # If no more active severe/high alerts remain, turn off LED + buzzer
    if _esp_sensor and _alerts_db:
        remaining = [a for a in _alerts_db.query_live()
                     if a["status"] == "active" and a["severity"] in ("severe", "high")]
        if not remaining:
            _esp_sensor.set_led(False)
            _esp_sensor.set_buzzer(False)

    return jsonify(result)


@app.route("/api/alerts/<int:alert_id>/logs")
def get_alert_logs(alert_id):
    if not _alerts_db:
        return jsonify([])
    return jsonify(_alerts_db.get_logs(alert_id))


@app.route("/api/zones")
def get_zones():
    if not _zone_checker:
        return jsonify({})
    camera_id = request.args.get("camera_id")
    if camera_id:
        return jsonify(_zone_checker.get_zones(camera_id))
    return jsonify(_zone_checker.get_zones())


# ---------------------------------------------------------------------------
# Airport info — live sensor data from ESP32-S3 via MQTT
# ---------------------------------------------------------------------------

def _surface_condition(rain_detected, humidity):
    if rain_detected:
        return "Wet — Rain detected"
    if humidity is not None and humidity > 85:
        return "Damp"
    return "Dry"


@app.route("/api/airport-info")
def airport_info():
    readings = _esp_sensor.get_readings() if _esp_sensor else {}

    temp = readings.get("bme_temperature", readings.get("aht_temperature"))
    humidity = readings.get("bme_humidity", readings.get("aht_humidity"))
    pressure = readings.get("bme_pressure")
    rain_raw = readings.get("rain_sensor")
    rain_detected = rain_raw == "ON" if rain_raw is not None else None

    live_count = len(_alerts_db.query_live()) if _alerts_db else 0
    hist_count = len(_alerts_db.query_history(limit=1000,
        from_ts=(datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    )) if _alerts_db else 0

    return jsonify({
        "name": "Aeroportul Internațional Oradea",
        "code": "OMR",
        "environmental": {
            "temperature": round(temp, 1) if temp is not None else None,
            "temperature_unit": "°C",
            "humidity": round(humidity, 1) if humidity is not None else None,
            "humidity_unit": "%",
            "pressure": round(pressure, 1) if pressure is not None else None,
            "pressure_unit": "hPa",
            "rain_detected": rain_detected,
        },
        "runway_status": {
            "live_incidents": live_count,
            "past_24hr": hist_count,
            "surface_condition": _surface_condition(rain_detected, humidity),
        },
    })


# ---------------------------------------------------------------------------
# Zone overlay drawing helper
# ---------------------------------------------------------------------------

_ZONE_COLORS = {
    "severe": (0, 0, 255),    # red in BGR
    "medium": (0, 165, 255),  # orange
    "low":    (255, 180, 0),  # cyan-ish blue
    None:     (0, 255, 0),    # green default
}


def _draw_zones_on_jpeg(jpeg_bytes, camera_id):
    """Decode JPEG, draw zone polygons, re-encode. Returns new JPEG bytes."""
    if not _zone_checker:
        return jpeg_bytes
    zones = _zone_checker.get_zones(camera_id)
    if not zones:
        return jpeg_bytes

    arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None:
        return jpeg_bytes

    overlay = frame.copy()
    for zone in zones:
        pts = np.array(zone["polygon"], dtype=np.int32)
        color = _ZONE_COLORS.get(zone.get("severity_override"), _ZONE_COLORS[None])
        cv2.fillPoly(overlay, [pts], color)
        cv2.polylines(frame, [pts], isClosed=True, color=color, thickness=2)
        M = cv2.moments(pts)
        if M["m00"] != 0:
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])
            cv2.putText(frame, zone.get("name", zone["id"]),
                        (cx - 40, cy), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, (255, 255, 255), 1, cv2.LINE_AA)

    alpha = 0.2
    cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)

    _, out = cv2.imencode(".jpg", frame)
    return out.tobytes()


# ---------------------------------------------------------------------------
# API 1 — Live stream (MJPEG, ring buffer, offset 0-30s)
# GET /api/stream/<camera_id>/live?offset=<seconds>
#   offset=0 (default) → real-time live
#   offset=5           → always 5s behind live, persistently
#   zones=1            → draw zone boundary polygons on each frame
# ---------------------------------------------------------------------------

@app.route("/api/stream/<camera_id>/live")
def live_stream(camera_id):
    cam = cameras.get(camera_id)
    if not cam:
        return jsonify({"error": "Camera not found"}), 404

    annotated = request.args.get("annotated", "0") == "1"
    show_zones = request.args.get("zones", "0") == "1"
    offset = min(request.args.get("offset", 0, type=float), 30)

    def generate():
        if offset <= 0:
            while True:
                if annotated and cam.has_detector:
                    jpeg = cam.wait_for_annotated_frame(timeout=1.0)
                else:
                    jpeg = cam.wait_for_frame(timeout=1.0)
                if jpeg:
                    if show_zones:
                        jpeg = _draw_zones_on_jpeg(jpeg, camera_id)
                    yield (b"--frame\r\n"
                           b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n")
        else:
            last_jpeg = None
            while True:
                target = datetime.now(timezone.utc) - timedelta(seconds=offset)
                jpeg = cam.get_frame_at(target)
                if jpeg and jpeg is not last_jpeg:
                    last_jpeg = jpeg
                    out = _draw_zones_on_jpeg(jpeg, camera_id) if show_zones else jpeg
                    yield (b"--frame\r\n"
                           b"Content-Type: image/jpeg\r\n\r\n" + out + b"\r\n")
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
