import time
import threading
from datetime import datetime, timedelta

import cv2
from flask import Flask, Response, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ---------------------------------------------------------------------------
# Camera registry — add real MJPEG URLs here; the UI auto-discovers them
# ---------------------------------------------------------------------------
CAMERAS = {
    "camera_r1_1": {
        "name": "Camera R1-1",
        "url": "",  # e.g. "http://192.168.1.10:8080/video"
        "location": {"lat": 47.0365, "lng": 21.9484},
    },
    "camera_r1_2": {
        "name": "Camera R1-2",
        "url": "",
        "location": {"lat": 47.0362, "lng": 21.9500},
    },
}

# ---------------------------------------------------------------------------
# Thread-safe frame readers (one per camera)
# ---------------------------------------------------------------------------
_captures = {}
_frames = {}
_locks = {}


def _reader_loop(cam_id, url):
    cap = cv2.VideoCapture(url)
    while True:
        ok, frame = cap.read()
        if not ok:
            cap.release()
            time.sleep(2)
            cap = cv2.VideoCapture(url)
            continue
        with _locks[cam_id]:
            _frames[cam_id] = frame


def _ensure_reader(cam_id):
    if cam_id in _captures:
        return
    url = CAMERAS[cam_id]["url"]
    if not url:
        return
    _locks[cam_id] = threading.Lock()
    _frames[cam_id] = None
    _captures[cam_id] = True
    t = threading.Thread(target=_reader_loop, args=(cam_id, url), daemon=True)
    t.start()


def _generate_mjpeg(cam_id):
    _ensure_reader(cam_id)
    while True:
        frame = None
        if cam_id in _locks:
            with _locks[cam_id]:
                frame = _frames.get(cam_id)
        if frame is not None:
            _, buf = cv2.imencode(".jpg", frame)
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"
            )
        time.sleep(0.033)  # ~30 fps cap


# ---------------------------------------------------------------------------
# Placeholder notification data
# ---------------------------------------------------------------------------
SAMPLE_NOTIFICATIONS = [
    {
        "id": 1,
        "type": "incursion",
        "severity": "severe",
        "status": "pending",
        "source": "camera_r1_1",
        "classification": "vehicle",
        "timestamp_start": (datetime.utcnow() - timedelta(minutes=3)).isoformat() + "Z",
        "timestamp_end": None,
        "runway_location": {"x": 320, "y": 180},
    },
    {
        "id": 2,
        "type": "incursion",
        "severity": "medium",
        "status": "pending",
        "source": "camera_r1_2",
        "classification": "bird",
        "timestamp_start": (datetime.utcnow() - timedelta(minutes=8)).isoformat() + "Z",
        "timestamp_end": (datetime.utcnow() - timedelta(minutes=5)).isoformat() + "Z",
        "runway_location": {"x": 510, "y": 90},
    },
    {
        "id": 3,
        "type": "environment",
        "severity": "low",
        "status": "valid",
        "source": "esphome_sensor_1",
        "classification": "high_humidity",
        "timestamp_start": (datetime.utcnow() - timedelta(minutes=20)).isoformat() + "Z",
        "timestamp_end": None,
        "sensor_value": 87.3,
        "sensor_unit": "%",
    },
    {
        "id": 4,
        "type": "incursion",
        "severity": "severe",
        "status": "pending",
        "source": "camera_r1_1",
        "classification": "person",
        "timestamp_start": (datetime.utcnow() - timedelta(seconds=45)).isoformat() + "Z",
        "timestamp_end": None,
        "runway_location": {"x": 400, "y": 220},
    },
]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/api/status")
def status():
    return jsonify({
        "message": "Runway Shield is online. All systems operational.",
        "status": "ok",
    })


@app.route("/api/cameras")
def cameras():
    out = []
    for cid, meta in CAMERAS.items():
        out.append({
            "id": cid,
            "name": meta["name"],
            "stream_url": f"/api/cameras/{cid}/stream",
            "location": meta["location"],
            "online": bool(meta["url"]),
        })
    return jsonify(out)


@app.route("/api/cameras/<cam_id>/stream")
def camera_stream(cam_id):
    if cam_id not in CAMERAS:
        return jsonify({"error": "Camera not found"}), 404
    if not CAMERAS[cam_id]["url"]:
        return jsonify({"error": "Camera URL not configured"}), 503
    return Response(
        _generate_mjpeg(cam_id),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/api/notifications/live")
def notifications_live():
    active = [n for n in SAMPLE_NOTIFICATIONS if n.get("timestamp_end") is None]
    return jsonify(active)


@app.route("/api/notifications/history")
def notifications_history():
    return jsonify(SAMPLE_NOTIFICATIONS)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
