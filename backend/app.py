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
        cam = CameraStream(camera_id=cam_id, url=cfg["url"], video_dir="videos")
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
# Live MJPEG stream
# ---------------------------------------------------------------------------

@app.route("/api/stream/<camera_id>/live")
def live_stream(camera_id):
    cam = cameras.get(camera_id)
    if not cam:
        return jsonify({"error": "Camera not found"}), 404

    def generate():
        while True:
            jpeg = cam.wait_for_frame(timeout=1.0)
            if jpeg:
                yield (b"--frame\r\n"
                       b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n")

    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


# ---------------------------------------------------------------------------
# Unified playback (ring buffer or disk segments)
# ---------------------------------------------------------------------------

@app.route("/api/stream/<camera_id>/playback")
def playback(camera_id):
    cam = cameras.get(camera_id)
    if not cam:
        return jsonify({"error": "Camera not found"}), 404

    from_str = request.args.get("from")
    to_str = request.args.get("to")
    if not from_str or not to_str:
        return jsonify({"error": "Missing 'from' and 'to' query params (ISO 8601 UTC)"}), 400

    try:
        from_ts = datetime.fromisoformat(from_str).replace(tzinfo=timezone.utc)
        to_ts = datetime.fromisoformat(to_str).replace(tzinfo=timezone.utc)
    except ValueError:
        return jsonify({"error": "Invalid timestamp format. Use ISO 8601."}), 400

    # Try ring buffer first
    buffer_start = cam.buffer_start_time()
    if buffer_start and from_ts >= buffer_start:
        frames = cam.get_buffer_frames(from_ts, to_ts)
        if frames:
            def generate():
                for _ts, jpeg in frames:
                    yield (b"--frame\r\n"
                           b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n")
                    time.sleep(1 / cam.fps)
            return Response(generate(),
                            mimetype="multipart/x-mixed-replace; boundary=frame")

    # Fall back to disk segment
    for seg_name in cam.list_segments():
        seg_ts_str = seg_name.replace(".mp4", "").rstrip("Z")
        try:
            seg_ts = datetime.strptime(seg_ts_str, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        seg_end = seg_ts + timedelta(seconds=cam.segment_seconds)
        if seg_ts <= from_ts <= seg_end:
            path = cam.segment_path(seg_name)
            if os.path.isfile(path):
                return send_file(path, mimetype="video/mp4")

    return jsonify({"error": "No footage available for the requested time range"}), 404


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True, threaded=True)
