import os
import time
from datetime import datetime, timedelta, timezone

from flask import Flask, Response, jsonify, render_template, request, send_file
from flask_cors import CORS

from camera import CameraStream

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
}

cameras: dict[str, CameraStream] = {}
_cameras_started = False


def start_cameras():
    global _cameras_started
    if _cameras_started:
        return
    _cameras_started = True
    for cam_id, cfg in CAMERA_CONFIG.items():
        cam = CameraStream(camera_id=cam_id, url=cfg["url"], video_dir="videos",
                           buffer_seconds=45)
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
        "online": online,
        "connected": cam.connected if cam else False,
        "location": cfg.get("location"),
        "buffer_start": cam.buffer_start_time().isoformat() if cam and cam.buffer_start_time() else None,
        "segments": cam.list_segments() if cam else [],
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
# Notifications (stub endpoints the React dashboard calls)
# ---------------------------------------------------------------------------

@app.route("/api/notifications/history")
def notifications_history():
    return jsonify([])


@app.route("/api/notifications/live")
def notifications_live():
    return jsonify([])


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

    offset = min(request.args.get("offset", 0, type=float), 30)

    def generate():
        if offset <= 0:
            # Real-time: serve frames as they arrive
            while True:
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

    t = request.args.get("t", type=float)
    if t is None:
        return jsonify({"error": "Missing 't' query param (unix timestamp)"}), 400

    target = datetime.fromtimestamp(t, tz=timezone.utc)

    for seg_name in cam.list_segments():
        seg_ts_str = seg_name.replace(".mp4", "").rstrip("Z")
        try:
            seg_ts = datetime.strptime(seg_ts_str, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        seg_end = seg_ts + timedelta(seconds=cam.segment_seconds)
        if seg_ts <= target < seg_end:
            path = cam.segment_path(seg_name)
            if os.path.isfile(path):
                return send_file(path, mimetype="video/mp4")

    return jsonify({"error": "No segment found for the given timestamp"}), 404


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True, threaded=True)
