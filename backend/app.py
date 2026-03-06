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
    "camera_1": os.environ.get("CAMERA_1_URL", "0"),
}

cameras: dict[str, CameraStream] = {}


def start_cameras():
    for cam_id, url in CAMERA_CONFIG.items():
        cam = CameraStream(camera_id=cam_id, url=url, video_dir="videos",
                           buffer_seconds=45)
        try:
            cam.start()
            cameras[cam_id] = cam
            print(f"[camera] {cam_id} started ({url})")
        except ConnectionError as e:
            print(f"[camera] {cam_id} failed to start: {e}")


# ---------------------------------------------------------------------------
# Index
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
        "cameras": {
            cam_id: {"url": cam.url} for cam_id, cam in cameras.items()
        },
    })


# ---------------------------------------------------------------------------
# Camera list
# ---------------------------------------------------------------------------

@app.route("/api/cameras")
def list_cameras():
    return jsonify({
        cam_id: {
            "url": cam.url,
            "connected": cam.connected,
            "segments": cam.list_segments(),
        }
        for cam_id, cam in cameras.items()
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
    start_cameras()
    app.run(host="0.0.0.0", port=8081, debug=True, threaded=True)
