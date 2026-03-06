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
# Configure cameras here.  Each key is the camera_id used in API URLs.
# Set CAMERA_<ID>_URL env vars, or edit this dict directly.
CAMERA_CONFIG = {
    "camera_1": os.environ.get("CAMERA_1_URL", "0"),  # "0" = local webcam
}

cameras: dict[str, CameraStream] = {}


def start_cameras():
    for cam_id, url in CAMERA_CONFIG.items():
        cam = CameraStream(camera_id=cam_id, url=url, video_dir="videos")
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
            "buffer_start": cam.buffer_start_time().isoformat() if cam.buffer_start_time() else None,
            "segments": cam.list_segments(),
        }
        for cam_id, cam in cameras.items()
    })


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
    target_prefix = from_ts.strftime("%Y%m%dT")
    for seg_name in cam.list_segments():
        # Segment name: 20260306T140200Z.mp4 — find the one covering from_ts
        seg_ts_str = seg_name.replace(".mp4", "").rstrip("Z")
        try:
            seg_ts = datetime.strptime(seg_ts_str, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        seg_end = seg_ts + timedelta(seconds=cam.segment_seconds)
        if seg_ts <= from_ts and from_ts <= seg_end:
            path = cam.segment_path(seg_name)
            if os.path.isfile(path):
                return send_file(path, mimetype="video/mp4")

    return jsonify({"error": "No footage available for the requested time range"}), 404


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    start_cameras()
    app.run(host="0.0.0.0", port=8081, debug=True, threaded=True)
